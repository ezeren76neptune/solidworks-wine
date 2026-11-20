/* swfiledlg.dll: Wine's Open/Save dialogs replaced by the desktop's own (KDE) file dialog.
 *
 * Registered (HKLM\Software\Classes\CLSID, see sync-filedlg in bin/sw-wine) as the
 * server for CLSID_FileOpenDialog and CLSID_FileSaveDialog, the Vista-style dialogs
 * SOLIDWORKS uses for Open, Save As and Export. Each object wraps Wine's real dialog
 * (created through comdlg32's own DllGetClassObject) and forwards every call to it,
 * recording what the application configures (title, file types, folder, file name,
 * options, event sinks). Show() instead runs kdialog, the KDE file dialog (the one
 * Dolphin and every KDE application use), through /bin/sh, waits for it while the
 * owner window stays disabled and keeps repainting, then answers GetResult,
 * GetResults, GetFileName, GetFolder and GetFileTypeIndex from the chosen path(s).
 * The file type index is taken from the extension of the chosen file, since kdialog
 * does not report the selected filter. If kdialog cannot be started, Wine's own
 * dialog is shown as before.
 *
 * IFileDialogCustomize and other interfaces are the inner dialog's: controls an
 * application adds keep their default values, as if the user left them alone.
 *
 * Built by build-pe.sh with MinGW. Exports DllGetClassObject, DllCanUnloadNow. */
#define COBJMACROS
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <objbase.h>
#include <shlobj.h>
#include <shobjidl.h>
#include <shlwapi.h>

static const CLSID clsid_open = {0xdc1c5a9c, 0xe88a, 0x4dde, {0xa5, 0xa1, 0x60, 0xf8, 0x2a, 0x20, 0xae, 0xf7}};
static const CLSID clsid_save = {0xc0b4e2f3, 0xba21, 0x4773, {0x8d, 0xba, 0x33, 0x5e, 0xc9, 0x46, 0xeb, 0x8b}};

#define MAX_SINKS 8

struct dialog
{
    IFileDialog IFileDialog_iface;      /* IFileOpenDialog or IFileSaveDialog vtable */
    LONG ref;
    BOOL save;
    IFileDialog *inner;
    WCHAR *title, *filename;
    COMDLG_FILTERSPEC *filters;
    UINT nfilters;
    FILEOPENDIALOGOPTIONS options;
    IShellItem *folder, *default_folder;
    IFileDialogEvents *sinks[MAX_SINKS];
    DWORD cookies[MAX_SINKS];
    IShellItem **results;
    UINT nresults;
};

static struct dialog *impl(IFileDialog *iface)
{
    return CONTAINING_RECORD(iface, struct dialog, IFileDialog_iface);
}

static void *alloc(SIZE_T size) { return HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, size); }
static void release(void *p) { if (p) HeapFree(GetProcessHeap(), 0, p); }

static WCHAR *strdupW(const WCHAR *s)
{
    WCHAR *r;
    if (!s || !(r = alloc((lstrlenW(s) + 1) * sizeof(WCHAR)))) return NULL;
    lstrcpyW(r, s);
    return r;
}

static void clear_results(struct dialog *d)
{
    for (UINT i = 0; i < d->nresults; i++) IShellItem_Release(d->results[i]);
    release(d->results);
    d->results = NULL;
    d->nresults = 0;
}

static void free_filters(struct dialog *d)
{
    for (UINT i = 0; i < d->nfilters; i++)
    {
        release((void *)d->filters[i].pszName);
        release((void *)d->filters[i].pszSpec);
    }
    release(d->filters);
    d->filters = NULL;
    d->nfilters = 0;
}

/* ---- growable UTF-8 buffer for the shell command ---- */

struct buf { char *p; SIZE_T len, size; };

static void buf_add(struct buf *b, const char *s, SIZE_T n)
{
    if (b->len + n + 1 > b->size)
    {
        SIZE_T size = max(b->size * 2, b->len + n + 256);
        char *p = alloc(size);
        if (!p) return;
        if (b->p) { memcpy(p, b->p, b->len); release(b->p); }
        b->p = p;
        b->size = size;
    }
    memcpy(b->p + b->len, s, n);
    b->len += n;
    b->p[b->len] = 0;
}

static void buf_str(struct buf *b, const char *s) { buf_add(b, s, strlen(s)); }

/* append a UTF-16 string as a single-quoted shell word */
static void buf_quoteW(struct buf *b, const WCHAR *s)
{
    int n = WideCharToMultiByte(CP_UTF8, 0, s, -1, NULL, 0, NULL, NULL);
    char *u = alloc(n + 1);
    if (!u) return;
    WideCharToMultiByte(CP_UTF8, 0, s, -1, u, n, NULL, NULL);
    buf_str(b, "'");
    for (char *c = u; *c; c++)
    {
        if (*c == '\'') buf_str(b, "'\\''");
        else buf_add(b, c, 1);
    }
    buf_str(b, "'");
    release(u);
}

static void buf_quoteA(struct buf *b, const char *s)
{
    buf_str(b, "'");
    for (; *s; s++)
    {
        if (*s == '\'') buf_str(b, "'\\''");
        else buf_add(b, s, 1);
    }
    buf_str(b, "'");
}

/* ---- path conversion through Wine's kernel32 ---- */

static char *unix_path(const WCHAR *dos)
{
    static char *(CDECL *get_unix)(const WCHAR *);
    if (!get_unix) get_unix = (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "wine_get_unix_file_name");
    return get_unix ? get_unix(dos) : NULL;   /* HeapAlloc'ed on the process heap */
}

static WCHAR *dos_path(const char *unix)
{
    static WCHAR *(CDECL *get_dos)(const char *);
    if (!get_dos) get_dos = (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "wine_get_dos_file_name");
    return get_dos ? get_dos(unix) : NULL;
}

static WCHAR *item_path(IShellItem *item)
{
    WCHAR *path = NULL, *r;
    if (!item || FAILED(IShellItem_GetDisplayName(item, SIGDN_FILESYSPATH, &path))) return NULL;
    r = strdupW(path);
    CoTaskMemFree(path);
    return r;
}

static IShellItem *path_item(const WCHAR *path)
{
    IShellItem *item = NULL;
    PIDLIST_ABSOLUTE pidl;

    if (SUCCEEDED(SHCreateItemFromParsingName(path, NULL, &IID_IShellItem, (void **)&item))) return item;
    /* a file about to be saved does not exist yet: use a simple ID list */
    if ((pidl = SHSimpleIDListFromPath(path)))
    {
        SHCreateItemFromIDList(pidl, &IID_IShellItem, (void **)&item);
        CoTaskMemFree(pidl);
    }
    return item;
}

/* "*.sldprt;*.prt" -> "*.sldprt *.prt" ("*.*" -> "*"); KDE matches patterns case-insensitively */
static void add_patterns(struct buf *b, const WCHAR *spec)
{
    const WCHAR *p = spec;
    BOOL first = TRUE;
    while (*p)
    {
        WCHAR pat[MAX_PATH];
        char u[MAX_PATH * 3];
        int n = 0;
        while (*p == ';' || *p == ' ') p++;
        while (*p && *p != ';' && n < MAX_PATH - 1) pat[n++] = *p++;
        pat[n] = 0;
        while (n && pat[n - 1] == ' ') pat[--n] = 0;
        if (!n) continue;
        if (!lstrcmpW(pat, L"*.*")) lstrcpyW(pat, L"*");
        WideCharToMultiByte(CP_UTF8, 0, pat, -1, u, sizeof(u), NULL, NULL);
        if (!first) buf_str(b, " ");
        buf_str(b, u);
        first = FALSE;
    }
}

/* kdialog filter list: "Name (*.a *.A)\nName2 (*.b *.B)", the current type first */
static void build_filter(struct dialog *d, struct buf *f, UINT current)
{
    for (UINT k = 0; k < d->nfilters; k++)
    {
        UINT i = k == 0 ? current : (k <= current ? k - 1 : k);
        const WCHAR *name = d->filters[i].pszName ? d->filters[i].pszName : L"";
        WCHAR clean[512];
        int n = 0;
        char u[1536];

        /* drop a trailing "(*.x;*.y)" from the name, kdialog shows the patterns itself */
        lstrcpynW(clean, name, ARRAYSIZE(clean));
        for (n = lstrlenW(clean); n > 0 && clean[n - 1] == ' '; n--) clean[n - 1] = 0;
        if (n && clean[n - 1] == ')')
        {
            WCHAR *open = wcsrchr(clean, '(');
            if (open && open > clean) { *open = 0; for (n = lstrlenW(clean); n > 0 && clean[n - 1] == ' '; n--) clean[n - 1] = 0; }
        }
        WideCharToMultiByte(CP_UTF8, 0, clean, -1, u, sizeof(u), NULL, NULL);
        if (k) buf_str(f, "\n");
        buf_str(f, u);
        buf_str(f, " (");
        add_patterns(f, d->filters[i].pszSpec ? d->filters[i].pszSpec : L"*");
        buf_str(f, ")");
    }
}

/* index (1-based) of the first file type whose spec matches the file's extension */
static UINT type_from_name(struct dialog *d, const WCHAR *path)
{
    const WCHAR *ext = PathFindExtensionW(path);
    if (!ext || !*ext) return 0;
    for (UINT i = 0; i < d->nfilters; i++)
    {
        const WCHAR *p = d->filters[i].pszSpec;
        while (p && *p)
        {
            WCHAR pat[MAX_PATH];
            int n = 0;
            while (*p == ';' || *p == ' ') p++;
            while (*p && *p != ';' && n < MAX_PATH - 1) pat[n++] = *p++;
            pat[n] = 0;
            if (pat[0] == '*' && pat[1] == '.' && !lstrcmpiW(pat + 1, ext)) return i + 1;
        }
    }
    return 0;
}

/* append s as one argument of a Windows command line (Wine splits it back into argv) */
static void buf_argv(struct buf *b, const char *s)
{
    buf_str(b, "\"");
    for (;;)
    {
        int slashes = 0;
        while (*s == '\\') { slashes++; s++; }
        if (!*s) { for (int i = 0; i < slashes * 2; i++) buf_str(b, "\\"); break; }
        if (*s == '"') { for (int i = 0; i < slashes * 2 + 1; i++) buf_str(b, "\\"); buf_str(b, "\""); }
        else { for (int i = 0; i < slashes; i++) buf_str(b, "\\"); buf_add(b, s, 1); }
        s++;
    }
    buf_str(b, "\"");
}

/* run kdialog; returns S_OK with d->results filled, HRESULT_FROM_WIN32(ERROR_CANCELLED), or E_FAIL if it could not run */
static HRESULT run_kdialog(struct dialog *d, HWND owner)
{
    WCHAR tmpdir[MAX_PATH], base[MAX_PATH], outW[MAX_PATH], doneW[MAX_PATH], *start = NULL, *cmdW = NULL;
    char *out = NULL, *done = NULL;
    struct buf cmd = {0}, filter = {0};
    STARTUPINFOW si = {sizeof(si)};
    PROCESS_INFORMATION pi;
    HRESULT hr = E_FAIL;
    UINT current = 0;
    HWND top = owner ? GetAncestor(owner, GA_ROOT) : NULL;
    BOOL disabled = FALSE;
    HANDLE file;
    int n;

    GetTempPathW(MAX_PATH, tmpdir);
    wsprintfW(base, L"%sswfiledlg-%lu-%lu", tmpdir, GetCurrentProcessId(), GetTickCount());
    wsprintfW(outW, L"%s.out", base);
    wsprintfW(doneW, L"%s.done", base);
    DeleteFileW(outW);
    DeleteFileW(doneW);
    if (!(out = unix_path(outW)) || !(done = unix_path(doneW))) goto end;

    /* starting folder and name */
    if (d->folder) start = item_path(d->folder);
    if (!start && d->default_folder) start = item_path(d->default_folder);
    if (!start)
    {
        IShellItem *cur = NULL;
        if (SUCCEEDED(IFileDialog_GetFolder(d->inner, &cur)) && cur) { start = item_path(cur); IShellItem_Release(cur); }
    }
    if (!start)
    {
        WCHAR docs[MAX_PATH];
        if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_PERSONAL, NULL, 0, docs))) start = strdupW(docs);
    }
    if (d->filename && *d->filename && !(d->options & FOS_PICKFOLDERS))
    {
        WCHAR *full = alloc((MAX_PATH * 2 + lstrlenW(d->filename)) * sizeof(WCHAR));
        if (full)
        {
            if (PathIsRelativeW(d->filename) && start) { lstrcpyW(full, start); PathAddBackslashW(full); lstrcatW(full, d->filename); }
            else lstrcpyW(full, d->filename);
            release(start);
            start = full;
        }
    }

    if (d->nfilters)
    {
        if (FAILED(IFileDialog_GetFileTypeIndex(d->inner, &current)) || !current || current > d->nfilters) current = 1;
        build_filter(d, &filter, current - 1);
    }

    buf_str(&cmd, "kdialog");
    if (top)
    {
        HANDLE xid = GetPropW(top, L"__wine_x11_whole_window");
        if (xid) { char a[64]; wsprintfA(a, " --attach=%lu", (unsigned long)(ULONG_PTR)xid); buf_str(&cmd, a); }
    }
    buf_str(&cmd, " --title ");
    buf_quoteW(&cmd, d->title ? d->title : d->save ? L"Save As" : (d->options & FOS_PICKFOLDERS) ? L"Select Folder" : L"Open");
    if (d->options & FOS_PICKFOLDERS) buf_str(&cmd, " --getexistingdirectory ");
    else if (d->save) buf_str(&cmd, " --getsavefilename ");
    else if (d->options & FOS_ALLOWMULTISELECT) buf_str(&cmd, " --multiple --separate-output --getopenfilename ");
    else buf_str(&cmd, " --getopenfilename ");
    if (start)
    {
        char *u = unix_path(start);
        if (u) { buf_quoteA(&cmd, u); release(u); }
        else buf_str(&cmd, "''");
    }
    else buf_str(&cmd, "''");
    if (filter.p && !(d->options & FOS_PICKFOLDERS)) { buf_str(&cmd, " "); buf_quoteA(&cmd, filter.p); }
    buf_str(&cmd, " > ");
    buf_quoteA(&cmd, out);
    buf_str(&cmd, "; echo $? > ");
    buf_quoteA(&cmd, done);
    buf_str(&cmd, ".tmp; mv ");
    buf_quoteA(&cmd, done);
    buf_str(&cmd, ".tmp ");
    buf_quoteA(&cmd, done);
    if (!cmd.p) goto end;

    {
        struct buf line = {0};
        buf_str(&line, "Z:\\bin\\sh -c ");
        buf_argv(&line, cmd.p);
        n = MultiByteToWideChar(CP_UTF8, 0, line.p, -1, NULL, 0);
        if ((cmdW = alloc(n * sizeof(WCHAR)))) MultiByteToWideChar(CP_UTF8, 0, line.p, -1, cmdW, n);
        release(line.p);
    }
    if (!cmdW || !CreateProcessW(NULL, cmdW, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) goto end;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    /* modal: keep the owner disabled, keep messages flowing so it repaints */
    if (top && IsWindowEnabled(top)) { EnableWindow(top, FALSE); disabled = TRUE; }
    while (GetFileAttributesW(doneW) == INVALID_FILE_ATTRIBUTES)
    {
        MSG msg;
        MsgWaitForMultipleObjects(0, NULL, FALSE, 50, QS_ALLINPUT);
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE))
        {
            if (msg.message == WM_QUIT) { PostQuitMessage((int)msg.wParam); goto wait_done; }
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
wait_done:
    if (disabled) EnableWindow(top, TRUE);
    if (top) SetForegroundWindow(top);

    hr = HRESULT_FROM_WIN32(ERROR_CANCELLED);
    file = CreateFileW(outW, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, 0, NULL);
    if (file != INVALID_HANDLE_VALUE)
    {
        DWORD size = GetFileSize(file, NULL), got = 0;
        char *text = alloc(size + 1);
        if (text && ReadFile(file, text, size, &got, NULL))
        {
            char *line = text, *nl;
            text[got] = 0;
            clear_results(d);
            d->results = alloc((got / 2 + 2) * sizeof(*d->results));
            while (d->results && line && *line)
            {
                if ((nl = strchr(line, '\n'))) *nl++ = 0;
                if (*line == '/')
                {
                    WCHAR *p = dos_path(line);
                    IShellItem *item = p ? path_item(p) : NULL;
                    if (item) d->results[d->nresults++] = item;
                    release(p);
                }
                line = nl;
            }
            if (d->nresults)
            {
                WCHAR *first = item_path(d->results[0]);
                UINT type = first ? type_from_name(d, first) : 0;
                if (type) IFileDialog_SetFileTypeIndex(d->inner, type);
                if (first)
                {
                    release(d->filename);
                    d->filename = strdupW(PathFindFileNameW(first));
                    if (d->filename) IFileDialog_SetFileName(d->inner, d->filename);
                }
                release(first);
                hr = S_OK;
            }
        }
        release(text);
        CloseHandle(file);
    }
    DeleteFileW(outW);
    DeleteFileW(doneW);

end:
    release(start);
    release(cmdW);
    release(cmd.p);
    release(filter.p);
    release(out);
    release(done);
    return hr;
}

/* ---- IFileDialog (shared by the open and save vtables) ---- */

static HRESULT WINAPI dlg_QueryInterface(IFileDialog *iface, REFIID riid, void **ppv)
{
    struct dialog *d = impl(iface);

    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IModalWindow) || IsEqualIID(riid, &IID_IFileDialog) ||
        (!d->save && IsEqualIID(riid, &IID_IFileOpenDialog)) || (d->save && IsEqualIID(riid, &IID_IFileSaveDialog)))
    {
        *ppv = iface;
        IFileDialog_AddRef(iface);
        return S_OK;
    }
    return IFileDialog_QueryInterface(d->inner, riid, ppv);
}

static ULONG WINAPI dlg_AddRef(IFileDialog *iface)
{
    return InterlockedIncrement(&impl(iface)->ref);
}

static ULONG WINAPI dlg_Release(IFileDialog *iface)
{
    struct dialog *d = impl(iface);
    ULONG ref = InterlockedDecrement(&d->ref);

    if (!ref)
    {
        for (int i = 0; i < MAX_SINKS; i++) if (d->sinks[i]) IFileDialogEvents_Release(d->sinks[i]);
        clear_results(d);
        free_filters(d);
        if (d->folder) IShellItem_Release(d->folder);
        if (d->default_folder) IShellItem_Release(d->default_folder);
        release(d->title);
        release(d->filename);
        IFileDialog_Release(d->inner);
        release(d);
    }
    return ref;
}

static HRESULT WINAPI dlg_Show(IFileDialog *iface, HWND owner)
{
    struct dialog *d = impl(iface);
    HRESULT hr;

    for (;;)
    {
        hr = run_kdialog(d, owner);
        if (hr == E_FAIL) return IFileDialog_Show(d->inner, owner);   /* kdialog unavailable: Wine's dialog */
        if (FAILED(hr)) return hr;
        /* let the application check the choice; S_FALSE keeps the dialog open */
        for (int i = 0; i < MAX_SINKS; i++)
        {
            if (d->sinks[i] && IFileDialogEvents_OnFileOk(d->sinks[i], iface) == S_FALSE)
            {
                hr = S_FALSE;
                break;
            }
        }
        if (hr != S_FALSE) return S_OK;
        clear_results(d);
    }
}

static HRESULT WINAPI dlg_SetFileTypes(IFileDialog *iface, UINT count, const COMDLG_FILTERSPEC *specs)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_SetFileTypes(d->inner, count, specs);

    if (SUCCEEDED(hr) && specs)
    {
        free_filters(d);
        d->filters = alloc(count * sizeof(*specs));
        for (UINT i = 0; d->filters && i < count; i++)
        {
            d->filters[i].pszName = strdupW(specs[i].pszName);
            d->filters[i].pszSpec = strdupW(specs[i].pszSpec);
        }
        if (d->filters) d->nfilters = count;
    }
    return hr;
}

static HRESULT WINAPI dlg_SetFileTypeIndex(IFileDialog *iface, UINT index)
{
    return IFileDialog_SetFileTypeIndex(impl(iface)->inner, index);
}

static HRESULT WINAPI dlg_GetFileTypeIndex(IFileDialog *iface, UINT *index)
{
    return IFileDialog_GetFileTypeIndex(impl(iface)->inner, index);
}

static HRESULT WINAPI dlg_Advise(IFileDialog *iface, IFileDialogEvents *sink, DWORD *cookie)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_Advise(d->inner, sink, cookie);

    if (SUCCEEDED(hr) && sink)
    {
        for (int i = 0; i < MAX_SINKS; i++)
        {
            if (d->sinks[i]) continue;
            d->sinks[i] = sink;
            IFileDialogEvents_AddRef(sink);
            d->cookies[i] = *cookie;
            break;
        }
    }
    return hr;
}

static HRESULT WINAPI dlg_Unadvise(IFileDialog *iface, DWORD cookie)
{
    struct dialog *d = impl(iface);

    for (int i = 0; i < MAX_SINKS; i++)
    {
        if (!d->sinks[i] || d->cookies[i] != cookie) continue;
        IFileDialogEvents_Release(d->sinks[i]);
        d->sinks[i] = NULL;
    }
    return IFileDialog_Unadvise(d->inner, cookie);
}

static HRESULT WINAPI dlg_SetOptions(IFileDialog *iface, FILEOPENDIALOGOPTIONS options)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_SetOptions(d->inner, options);
    if (SUCCEEDED(hr)) d->options = options;
    return hr;
}

static HRESULT WINAPI dlg_GetOptions(IFileDialog *iface, FILEOPENDIALOGOPTIONS *options)
{
    return IFileDialog_GetOptions(impl(iface)->inner, options);
}

static void set_item(IShellItem **slot, IShellItem *item)
{
    if (item) IShellItem_AddRef(item);
    if (*slot) IShellItem_Release(*slot);
    *slot = item;
}

static HRESULT WINAPI dlg_SetDefaultFolder(IFileDialog *iface, IShellItem *item)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_SetDefaultFolder(d->inner, item);
    if (SUCCEEDED(hr)) set_item(&d->default_folder, item);
    return hr;
}

static HRESULT WINAPI dlg_SetFolder(IFileDialog *iface, IShellItem *item)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_SetFolder(d->inner, item);
    if (SUCCEEDED(hr)) set_item(&d->folder, item);
    return hr;
}

static HRESULT parent_of(IShellItem *item, IShellItem **parent)
{
    return IShellItem_GetParent(item, parent);
}

static HRESULT WINAPI dlg_GetFolder(IFileDialog *iface, IShellItem **item)
{
    struct dialog *d = impl(iface);
    if (d->nresults && SUCCEEDED(parent_of(d->results[0], item))) return S_OK;
    return IFileDialog_GetFolder(d->inner, item);
}

static HRESULT WINAPI dlg_GetCurrentSelection(IFileDialog *iface, IShellItem **item)
{
    struct dialog *d = impl(iface);
    if (d->nresults) { *item = d->results[0]; IShellItem_AddRef(*item); return S_OK; }
    return IFileDialog_GetCurrentSelection(d->inner, item);
}

static HRESULT WINAPI dlg_SetFileName(IFileDialog *iface, const WCHAR *name)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_SetFileName(d->inner, name);
    if (SUCCEEDED(hr)) { release(d->filename); d->filename = strdupW(name); }
    return hr;
}

static HRESULT WINAPI dlg_GetFileName(IFileDialog *iface, WCHAR **name)
{
    struct dialog *d = impl(iface);
    if (d->nresults && d->filename)
    {
        SIZE_T size = (lstrlenW(d->filename) + 1) * sizeof(WCHAR);
        if (!(*name = CoTaskMemAlloc(size))) return E_OUTOFMEMORY;
        memcpy(*name, d->filename, size);
        return S_OK;
    }
    return IFileDialog_GetFileName(d->inner, name);
}

static HRESULT WINAPI dlg_SetTitle(IFileDialog *iface, const WCHAR *title)
{
    struct dialog *d = impl(iface);
    HRESULT hr = IFileDialog_SetTitle(d->inner, title);
    if (SUCCEEDED(hr)) { release(d->title); d->title = strdupW(title); }
    return hr;
}

static HRESULT WINAPI dlg_SetOkButtonLabel(IFileDialog *iface, const WCHAR *text)
{
    return IFileDialog_SetOkButtonLabel(impl(iface)->inner, text);
}

static HRESULT WINAPI dlg_SetFileNameLabel(IFileDialog *iface, const WCHAR *text)
{
    return IFileDialog_SetFileNameLabel(impl(iface)->inner, text);
}

static HRESULT WINAPI dlg_GetResult(IFileDialog *iface, IShellItem **item)
{
    struct dialog *d = impl(iface);
    if (d->nresults) { *item = d->results[0]; IShellItem_AddRef(*item); return S_OK; }
    return IFileDialog_GetResult(d->inner, item);
}

static HRESULT WINAPI dlg_AddPlace(IFileDialog *iface, IShellItem *item, FDAP fdap)
{
    return IFileDialog_AddPlace(impl(iface)->inner, item, fdap);
}

static HRESULT WINAPI dlg_SetDefaultExtension(IFileDialog *iface, const WCHAR *ext)
{
    return IFileDialog_SetDefaultExtension(impl(iface)->inner, ext);
}

static HRESULT WINAPI dlg_Close(IFileDialog *iface, HRESULT hr)
{
    return IFileDialog_Close(impl(iface)->inner, hr);
}

static HRESULT WINAPI dlg_SetClientGuid(IFileDialog *iface, REFGUID guid)
{
    return IFileDialog_SetClientGuid(impl(iface)->inner, guid);
}

static HRESULT WINAPI dlg_ClearClientData(IFileDialog *iface)
{
    return IFileDialog_ClearClientData(impl(iface)->inner);
}

static HRESULT WINAPI dlg_SetFilter(IFileDialog *iface, IShellItemFilter *filter)
{
    return IFileDialog_SetFilter(impl(iface)->inner, filter);
}

/* ---- IFileOpenDialog ---- */

static HRESULT WINAPI open_GetResults(IFileOpenDialog *iface, IShellItemArray **items)
{
    struct dialog *d = impl((IFileDialog *)iface);
    PIDLIST_ABSOLUTE *pidls;
    HRESULT hr = E_FAIL;
    UINT n = 0;

    if (!d->nresults)
    {
        IFileOpenDialog *open;
        if (FAILED(IFileDialog_QueryInterface(d->inner, &IID_IFileOpenDialog, (void **)&open))) return E_UNEXPECTED;
        hr = IFileOpenDialog_GetResults(open, items);
        IFileOpenDialog_Release(open);
        return hr;
    }
    if (!(pidls = alloc(d->nresults * sizeof(*pidls)))) return E_OUTOFMEMORY;
    for (UINT i = 0; i < d->nresults; i++)
        if (SUCCEEDED(SHGetIDListFromObject((IUnknown *)d->results[i], &pidls[n]))) n++;
    if (n) hr = SHCreateShellItemArrayFromIDLists(n, (PCIDLIST_ABSOLUTE_ARRAY)pidls, items);
    for (UINT i = 0; i < n; i++) CoTaskMemFree(pidls[i]);
    release(pidls);
    return hr;
}

static HRESULT WINAPI open_GetSelectedItems(IFileOpenDialog *iface, IShellItemArray **items)
{
    return open_GetResults(iface, items);
}

/* ---- IFileSaveDialog ---- */

static HRESULT save_inner(struct dialog *d, IFileSaveDialog **save)
{
    return IFileDialog_QueryInterface(d->inner, &IID_IFileSaveDialog, (void **)save);
}

static HRESULT WINAPI save_SetSaveAsItem(IFileSaveDialog *iface, IShellItem *item)
{
    IFileSaveDialog *s; HRESULT hr;
    if (FAILED(hr = save_inner(impl((IFileDialog *)iface), &s))) return hr;
    hr = IFileSaveDialog_SetSaveAsItem(s, item);
    IFileSaveDialog_Release(s);
    return hr;
}

static HRESULT WINAPI save_SetProperties(IFileSaveDialog *iface, IPropertyStore *store)
{
    IFileSaveDialog *s; HRESULT hr;
    if (FAILED(hr = save_inner(impl((IFileDialog *)iface), &s))) return hr;
    hr = IFileSaveDialog_SetProperties(s, store);
    IFileSaveDialog_Release(s);
    return hr;
}

static HRESULT WINAPI save_SetCollectedProperties(IFileSaveDialog *iface, IPropertyDescriptionList *list, BOOL append)
{
    IFileSaveDialog *s; HRESULT hr;
    if (FAILED(hr = save_inner(impl((IFileDialog *)iface), &s))) return hr;
    hr = IFileSaveDialog_SetCollectedProperties(s, list, append);
    IFileSaveDialog_Release(s);
    return hr;
}

static HRESULT WINAPI save_GetProperties(IFileSaveDialog *iface, IPropertyStore **store)
{
    IFileSaveDialog *s; HRESULT hr;
    if (FAILED(hr = save_inner(impl((IFileDialog *)iface), &s))) return hr;
    hr = IFileSaveDialog_GetProperties(s, store);
    IFileSaveDialog_Release(s);
    return hr;
}

static HRESULT WINAPI save_ApplyProperties(IFileSaveDialog *iface, IShellItem *item, IPropertyStore *store, HWND hwnd,
                                           IFileOperationProgressSink *sink)
{
    IFileSaveDialog *s; HRESULT hr;
    if (FAILED(hr = save_inner(impl((IFileDialog *)iface), &s))) return hr;
    hr = IFileSaveDialog_ApplyProperties(s, item, store, hwnd, sink);
    IFileSaveDialog_Release(s);
    return hr;
}

#define FILEDIALOG_METHODS(T) \
    (void *)dlg_QueryInterface, (void *)dlg_AddRef, (void *)dlg_Release, (void *)dlg_Show, \
    (void *)dlg_SetFileTypes, (void *)dlg_SetFileTypeIndex, (void *)dlg_GetFileTypeIndex, (void *)dlg_Advise, \
    (void *)dlg_Unadvise, (void *)dlg_SetOptions, (void *)dlg_GetOptions, (void *)dlg_SetDefaultFolder, \
    (void *)dlg_SetFolder, (void *)dlg_GetFolder, (void *)dlg_GetCurrentSelection, (void *)dlg_SetFileName, \
    (void *)dlg_GetFileName, (void *)dlg_SetTitle, (void *)dlg_SetOkButtonLabel, (void *)dlg_SetFileNameLabel, \
    (void *)dlg_GetResult, (void *)dlg_AddPlace, (void *)dlg_SetDefaultExtension, (void *)dlg_Close, \
    (void *)dlg_SetClientGuid, (void *)dlg_ClearClientData, (void *)dlg_SetFilter

static const IFileOpenDialogVtbl open_vtbl = { FILEDIALOG_METHODS(open), open_GetResults, open_GetSelectedItems };
static const IFileSaveDialogVtbl save_vtbl = { FILEDIALOG_METHODS(save), save_SetSaveAsItem, save_SetProperties,
                                               save_SetCollectedProperties, save_GetProperties, save_ApplyProperties };

/* ---- class factory ---- */

struct factory
{
    IClassFactory IClassFactory_iface;
    LONG ref;
    BOOL save;
};

static struct factory *factory_impl(IClassFactory *iface)
{
    return CONTAINING_RECORD(iface, struct factory, IClassFactory_iface);
}

static HRESULT WINAPI factory_QueryInterface(IClassFactory *iface, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IClassFactory))
    {
        *ppv = iface;
        IClassFactory_AddRef(iface);
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}

static ULONG WINAPI factory_AddRef(IClassFactory *iface)
{
    return InterlockedIncrement(&factory_impl(iface)->ref);
}

static ULONG WINAPI factory_Release(IClassFactory *iface)
{
    struct factory *f = factory_impl(iface);
    ULONG ref = InterlockedDecrement(&f->ref);
    if (!ref) release(f);
    return ref;
}

static HRESULT inner_create(BOOL save, IFileDialog **inner)
{
    HRESULT (WINAPI *get_class)(REFCLSID, REFIID, void **);
    IClassFactory *cf;
    HMODULE comdlg;
    HRESULT hr;

    if (!(comdlg = LoadLibraryW(L"comdlg32.dll"))) return CLASS_E_CLASSNOTAVAILABLE;
    if (!(get_class = (void *)GetProcAddress(comdlg, "DllGetClassObject"))) return CLASS_E_CLASSNOTAVAILABLE;
    if (FAILED(hr = get_class(save ? &clsid_save : &clsid_open, &IID_IClassFactory, (void **)&cf))) return hr;
    hr = IClassFactory_CreateInstance(cf, NULL, &IID_IFileDialog, (void **)inner);
    IClassFactory_Release(cf);
    return hr;
}

static HRESULT WINAPI factory_CreateInstance(IClassFactory *iface, IUnknown *outer, REFIID riid, void **ppv)
{
    struct factory *f = factory_impl(iface);
    struct dialog *d;
    HRESULT hr;

    *ppv = NULL;
    if (outer) return CLASS_E_NOAGGREGATION;
    if (!(d = alloc(sizeof(*d)))) return E_OUTOFMEMORY;
    if (FAILED(hr = inner_create(f->save, &d->inner)))
    {
        release(d);
        return hr;
    }
    d->IFileDialog_iface.lpVtbl = f->save ? (void *)&save_vtbl : (void *)&open_vtbl;
    d->ref = 1;
    d->save = f->save;
    IFileDialog_GetOptions(d->inner, &d->options);
    hr = IFileDialog_QueryInterface(&d->IFileDialog_iface, riid, ppv);
    IFileDialog_Release(&d->IFileDialog_iface);
    return hr;
}

static HRESULT WINAPI factory_LockServer(IClassFactory *iface, BOOL lock)
{
    return S_OK;
}

static const IClassFactoryVtbl factory_vtbl =
{
    factory_QueryInterface, factory_AddRef, factory_Release, factory_CreateInstance, factory_LockServer
};

HRESULT WINAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void **ppv)
{
    struct factory *f;
    HRESULT hr;

    *ppv = NULL;
    if (!IsEqualCLSID(clsid, &clsid_open) && !IsEqualCLSID(clsid, &clsid_save)) return CLASS_E_CLASSNOTAVAILABLE;
    if (!(f = alloc(sizeof(*f)))) return E_OUTOFMEMORY;
    f->IClassFactory_iface.lpVtbl = (IClassFactoryVtbl *)&factory_vtbl;
    f->ref = 1;
    f->save = IsEqualCLSID(clsid, &clsid_save);
    hr = IClassFactory_QueryInterface(&f->IClassFactory_iface, riid, ppv);
    IClassFactory_Release(&f->IClassFactory_iface);
    return hr;
}

HRESULT WINAPI DllCanUnloadNow(void)
{
    return S_FALSE;
}
