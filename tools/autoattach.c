/* autoattach: Windows attaches the input queues of two threads when one owns a child window
   of the other's window (cross-thread parent/child). Wine does not, so keyboard focus never
   reaches e.g. an embedded WebView2 (its HWND lives in msedgewebview2.exe). This polls the
   window tree and does that AttachThreadInput itself.   autoattach.exe [seconds, 0 = forever] */
#include <windows.h>
#include <stdio.h>
#define MAXP 256
static DWORD done_a[MAXP], done_b[MAXP]; static int ndone;
static BOOL seen(DWORD a, DWORD b)
{
    for (int i = 0; i < ndone; i++) if (done_a[i] == a && done_b[i] == b) return TRUE;
    return FALSE;
}
static BOOL CALLBACK child(HWND c, LPARAM l)
{
    HWND p = GetAncestor(c, GA_PARENT); DWORD tc, tp;
    if (!p) return TRUE;
    tc = GetWindowThreadProcessId(c, NULL); tp = GetWindowThreadProcessId(p, NULL);
    if (tc && tp && tc != tp && !seen(tc, tp)) {
        char cls[64]; GetClassNameA(c, cls, sizeof cls);
        BOOL r = AttachThreadInput(tc, tp, TRUE);
        printf("attach %lu -> %lu for %p [%s]: %s (%lu)\n", tc, tp, c, cls, r ? "ok" : "failed", r ? 0 : GetLastError());
        fflush(stdout);
        if (ndone < MAXP) { done_a[ndone] = tc; done_b[ndone] = tp; ndone++; }
    }
    return TRUE;
}
static BOOL CALLBACK top(HWND h, LPARAM l) { EnumChildWindows(h, child, 0); return TRUE; }
int main(int argc, char **argv)
{
    int secs = argc > 1 ? atoi(argv[1]) : 0;
    for (DWORD start = GetTickCount(); !secs || GetTickCount() - start < (DWORD)secs * 1000; Sleep(500)) {
        EnumWindows(top, 0);
        /* forget pairs whose threads are gone so a restarted program is attached again */
        for (int i = 0; i < ndone; i++) {
            HANDLE ha = OpenThread(SYNCHRONIZE, FALSE, done_a[i]), hb = OpenThread(SYNCHRONIZE, FALSE, done_b[i]);
            BOOL gone = !ha || !hb || WaitForSingleObject(ha, 0) == WAIT_OBJECT_0 || WaitForSingleObject(hb, 0) == WAIT_OBJECT_0;
            if (ha) CloseHandle(ha);
            if (hb) CloseHandle(hb);
            if (gone) { done_a[i] = done_a[ndone - 1]; done_b[i] = done_b[ndone - 1]; ndone--; i--; }
        }
    }
    return 0;
}
