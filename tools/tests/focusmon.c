/* focusmon: every 200 ms for N seconds, print foreground window/thread and the active/focus/capture
   windows of the foreground thread and of extra thread ids given on the command line, when they change.
   focusmon.exe <seconds> [tid ...] */
#include <windows.h>
#include <stdio.h>
#include <string.h>
static void desc(HWND h, char *out, size_t n)
{
    char cls[64] = ""; DWORD pid = 0, tid = 0;
    if (!h) { snprintf(out, n, "0"); return; }
    tid = GetWindowThreadProcessId(h, &pid); GetClassNameA(h, cls, sizeof cls);
    snprintf(out, n, "%p[%s pid=%lu tid=%lu]", h, cls, pid, tid);
}
static void info(DWORD tid, char *out, size_t n)
{
    GUITHREADINFO gi = { sizeof gi }; char a[128], f[128], c[128];
    if (!GetGUIThreadInfo(tid, &gi)) { snprintf(out, n, "tid %lu: GetGUIThreadInfo failed %lu", tid, GetLastError()); return; }
    desc(gi.hwndActive, a, sizeof a); desc(gi.hwndFocus, f, sizeof f); desc(gi.hwndCapture, c, sizeof c);
    snprintf(out, n, "tid %lu: active=%s focus=%s capture=%s caret=%p flags=%lx", tid, a, f, c, gi.hwndCaret, gi.flags);
}
int main(int argc, char **argv)
{
    int secs = argc > 1 ? atoi(argv[1]) : 30; char prev[4096] = "", cur[4096];
    for (int i = 0; i < secs * 5; i++) {
        char fg[160], line[600]; HWND h = GetForegroundWindow(); DWORD ftid = GetWindowThreadProcessId(h, NULL);
        desc(h, fg, sizeof fg); snprintf(cur, sizeof cur, "fg=%s\n", fg);
        info(ftid, line, sizeof line); strcat(cur, "  "); strcat(cur, line); strcat(cur, "\n");
        for (int a = 2; a < argc; a++) { info(strtoul(argv[a], 0, 0), line, sizeof line); strcat(cur, "  "); strcat(cur, line); strcat(cur, "\n"); }
        if (strcmp(cur, prev)) { printf("[%5.1fs]\n%s", i / 5.0, cur); fflush(stdout); strcpy(prev, cur); }
        Sleep(200);
    }
    return 0;
}
