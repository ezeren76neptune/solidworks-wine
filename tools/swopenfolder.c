/* Open a folder (or show a file) in the Linux file manager instead of Wine's.
 *
 *   swopenfolder.exe "C:\path\to\folder"      (also "/select,C:\path\to\file")
 *
 * sw-wine registers this as the "open" and "explore" verbs of the Folder class, so a folder
 * SOLIDWORKS hands to the Windows shell shows up in Dolphin (or $SW_FILE_MANAGER) rather than
 * in Wine's own file browser. A file is shown selected in its folder. Without that file
 * manager it falls back to xdg-open on the folder. ShellExecute refuses to start a Linux
 * program itself ("bad format"), so this small Windows program does it with CreateProcess,
 * which Wine allows, and never shows a console window.
 * Built by tools/build-pe.sh. */
#include <windows.h>
#include <shellapi.h>
#include <string.h>

struct buf { char *p; SIZE_T len, size; };

static void buf_add(struct buf *b, const char *s, SIZE_T n)
{
    if (b->len + n + 1 > b->size)
    {
        SIZE_T size = b->size * 2 > b->len + n + 256 ? b->size * 2 : b->len + n + 256;
        char *p = HeapAlloc(GetProcessHeap(), 0, size);
        if (!p) return;
        if (b->p) { memcpy(p, b->p, b->len); HeapFree(GetProcessHeap(), 0, b->p); }
        b->p = p;
        b->size = size;
    }
    memcpy(b->p + b->len, s, n);
    b->len += n;
    b->p[b->len] = 0;
}

static void buf_str(struct buf *b, const char *s) { buf_add(b, s, strlen(s)); }

/* append one argument quoted for Windows command-line parsing (which Wine applies to argv) */
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

/* $1 is the Linux path: show a folder, or a file selected in its folder */
static const char script[] =
    "exec </dev/null >/dev/null 2>&1; fm=${SW_FILE_MANAGER:-dolphin}; "
    "if command -v \"$fm\" >/dev/null 2>&1; then "
    "if [ -d \"$1\" ]; then exec \"$fm\" --new-window \"$1\"; fi; "
    "exec \"$fm\" --new-window --select \"$1\"; fi; "
    "[ -d \"$1\" ] || set -- \"$(dirname \"$1\")\"; exec xdg-open \"$1\"";

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, WCHAR *cmdline, int show)
{
    char *(CDECL *get_unix)(const WCHAR *) =
        (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "wine_get_unix_file_name");
    STARTUPINFOW si = {sizeof(si)};
    PROCESS_INFORMATION pi;
    struct buf line = {0};
    WCHAR **argv, *path, *lineW;
    char *unix;
    int argc, n;

    if (!get_unix || !(argv = CommandLineToArgvW(GetCommandLineW(), &argc)) || argc < 2) return 1;
    path = argv[1];
    if (!_wcsnicmp(path, L"/select,", 8)) path += 8;
    while (*path == ' ') path++;
    if (!(unix = get_unix(path))) return 1;

    buf_str(&line, "Z:\\bin\\sh -c ");
    buf_argv(&line, script);
    buf_str(&line, " swopenfolder ");
    buf_argv(&line, unix);
    if (!line.p) return 1;
    n = MultiByteToWideChar(CP_UTF8, 0, line.p, -1, NULL, 0);
    if (!(lineW = HeapAlloc(GetProcessHeap(), 0, n * sizeof(WCHAR)))) return 1;
    MultiByteToWideChar(CP_UTF8, 0, line.p, -1, lineW, n);
    if (!CreateProcessW(NULL, lineW, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) return 1;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
