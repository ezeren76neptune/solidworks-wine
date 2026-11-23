/* SHOpenFolderAndSelectItems that shows the item in the Linux file manager.
 * SOLIDWORKS' "Show in Folder" (Welcome dialog > Recent > Documents) calls
 * SHOpenFolderAndSelectItems. Wine's version only works with Wine's own explorer: it
 * runs the Folder class's "explore" verb through ShellExecuteEx with an ID list, and for
 * an ID list Wine substitutes the folder into the whole command line and then looks that
 * line up as one file name, which fails for any command that takes arguments (such as
 * sw-wine's swopenfolder.exe), so nothing opened at all.
 * This wrapper turns the item into a path and runs
 *   C:\windows\system32\swopenfolder.exe /select,"<path>"
 * which shows the file selected in Dolphin (see tools/swopenfolder.c). When the path
 * cannot be had or swopenfolder.exe cannot be started, Wine's function runs as before.
 * Injected into a private copy of shell32.dll by pe-inject.py, which points the export
 * here and fills the slots below. */
typedef unsigned short WCHAR;
typedef unsigned int DWORD, UINT;
typedef int BOOL, HRESULT;

typedef struct
{
    DWORD cbSize;
    DWORD fMask;
    void *hwnd;
    const WCHAR *lpVerb;
    const WCHAR *lpFile;
    const WCHAR *lpParameters;
    const WCHAR *lpDirectory;
    int nShow;
    void *hInstApp;
    void *lpIDList;
    const WCHAR *lpClass;
    void *hkeyClass;
    DWORD dwHotKey;
    void *hIcon;
    void *hProcess;
} SHELLEXECUTEINFOW;

typedef __attribute__((ms_abi)) HRESULT (*open_folder_t)(const void *, UINT, const void **, DWORD);
typedef __attribute__((ms_abi)) BOOL (*get_path_t)(const void *, WCHAR *);
typedef __attribute__((ms_abi)) void *(*il_combine_t)(const void *, const void *);
typedef __attribute__((ms_abi)) void (*il_free_t)(void *);
typedef __attribute__((ms_abi)) BOOL (*shell_execute_t)(SHELLEXECUTEINFOW *);

__attribute__((used)) const volatile int slot_SHOpenFolderAndSelectItems = 0x5a5a5a5a;
__attribute__((used)) const volatile int slot_SHGetPathFromIDListW = 0x5a5a5a5a;
__attribute__((used)) const volatile int slot_ILCombine = 0x5a5a5a5a;
__attribute__((used)) const volatile int slot_ILFree = 0x5a5a5a5a;
__attribute__((used)) const volatile int slot_ShellExecuteExW = 0x5a5a5a5a;

#define SLOT(type, name) ((type)((const char *)&slot_##name + slot_##name))
#define MAX_PATH 260
#define S_OK 0
#define SEE_MASK_FLAG_NO_UI 0x400
#define SW_SHOWNORMAL 1

__attribute__((ms_abi)) HRESULT SHOpenFolderAndSelectItems_wrap(const void *folder, UINT cidl, const void **items, DWORD flags)
{
    static const WCHAR helper[] = u"C:\\windows\\system32\\swopenfolder.exe";
    static const WCHAR verb[] = u"open";
    WCHAR path[MAX_PATH], params[MAX_PATH + 16];
    SHELLEXECUTEINFOW sei;
    void *full = 0;
    const void *item = folder;
    BOOL ok = 0;
    int i, n;

    if (folder)
    {
        if (cidl && items && items[0] && (full = SLOT(il_combine_t, ILCombine)(folder, items[0]))) item = full;
        if (SLOT(get_path_t, SHGetPathFromIDListW)(item, path))
        {
            static const char select[] = "/select,\"";
            for (n = 0; select[n]; n++) params[n] = select[n];
            for (i = 0; path[i] && n < MAX_PATH + 13; i++) params[n++] = path[i];
            params[n++] = '"';
            params[n] = 0;

            sei.cbSize = sizeof(sei);
            sei.fMask = SEE_MASK_FLAG_NO_UI;
            sei.hwnd = 0;
            sei.lpVerb = verb;
            sei.lpFile = helper;
            sei.lpParameters = params;
            sei.lpDirectory = 0;
            sei.nShow = SW_SHOWNORMAL;
            sei.hInstApp = 0;
            sei.lpIDList = 0;
            sei.lpClass = 0;
            sei.hkeyClass = 0;
            sei.dwHotKey = 0;
            sei.hIcon = 0;
            sei.hProcess = 0;
            ok = SLOT(shell_execute_t, ShellExecuteExW)(&sei);
        }
        if (full) SLOT(il_free_t, ILFree)(full);
        if (ok) return S_OK;
    }
    return SLOT(open_folder_t, SHOpenFolderAndSelectItems)(folder, cidl, items, flags);
}
