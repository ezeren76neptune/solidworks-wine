/* pmdrift: reproduces SOLIDWORKS' PropertyManager group headers sliding away under Wine.
   A dialog-like parent (WS_CLIPCHILDREN) holds a themed checkbox and WS_EX_TRANSPARENT owner-draw
   "header" buttons. Like slduiu.dll's group painting, every WM_PAINT/WM_PRINTCLIENT of the parent
   reads each header's current rect, adds a 4 px margin on the left and calls
   SetWindowPos(header, HWND_TOPMOST, ...). Windows ignores the position and size when a child
   window is given HWND_TOPMOST, so nothing moves; Wine moved the headers, which exposed the parent,
   which painted again, until the headers were 0 px wide.
   Like SOLIDWORKS, the parent's WM_PRINTCLIENT handler (which themed check boxes reach through
   DrawThemeParentBackground) ends with ReleaseDC(parent, hdc) on the DC it was given; the check box
   must still draw itself (on Windows the button paints through a buffered-paint memory DC).
   Also checks Wine's user32 test case: SetWindowPos(child, HWND_TOPMOST/NOTOPMOST, 1,2,3,4, 0)
   must leave the child's rect alone, while HWND_TOP moves it and a top-level window still moves.
   Prints PASS/FAIL lines; exit code = number of failures. Wine 11.21: 5 failures unpatched, 0 with
   tools/patch-win32u.py and tools/uxtheme_parentbg.c. PMDRIFT_DUMP=1 prints the check box as text.
   Build (MinGW, comctl32 v6 manifest for the themed check box):
     echo '1 24 "pmdrift.manifest"' > pmdrift.rc
     x86_64-w64-mingw32-windres pmdrift.rc -O coff -o pmdrift.res
     x86_64-w64-mingw32-gcc -O2 -o pmdrift.exe pmdrift.c pmdrift.res -lcomctl32 -lgdi32 -luser32
   Run in a scratch prefix: WINEPREFIX=/tmp/pfx bin/sw-wine wine pmdrift.exe */
#include <windows.h>
#include <commctrl.h>
#include <stdio.h>
static HWND parent, hdr[3], chk;
static int paints, prints, fails;
static void relayout(void)
{
    RECT rp; GetWindowRect(parent, &rp);
    for (int i = 0; i < 3; i++) {
        RECT r; GetWindowRect(hdr[i], &r); OffsetRect(&r, -rp.left, -rp.top);
        r.left += 4; if (r.right > rp.right - rp.left - 8) r.right = rp.right - rp.left - 8;
        if (r.right < r.left) r.right = r.left;
        SetWindowPos(hdr[i], HWND_TOPMOST, r.left, r.top, r.right - r.left, r.bottom - r.top, 0);
    }
}
static LRESULT CALLBACK proc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_PAINT: { PAINTSTRUCT ps; BeginPaint(h, &ps); paints++; relayout();
        RECT rc; GetClientRect(h, &rc); FillRect(ps.hdc, &rc, GetSysColorBrush(COLOR_WINDOW)); EndPaint(h, &ps); return 0; }
    case WM_PRINTCLIENT: { RECT rc; prints++; relayout(); GetClientRect(h, &rc);
        FillRect((HDC)w, &rc, GetSysColorBrush(COLOR_WINDOW));
        ReleaseDC(h, (HDC)w);           /* as SOLIDWORKS' uiPropertyPage_c does with the DC it was handed */
        return 0; }
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLORSTATIC: return (LRESULT)GetSysColorBrush(COLOR_WINDOW);
    case WM_DRAWITEM: { DRAWITEMSTRUCT *d = (DRAWITEMSTRUCT *)l; char t[64]; GetWindowTextA(d->hwndItem, t, sizeof t);
        SetBkMode(d->hDC, TRANSPARENT); DrawTextA(d->hDC, t, -1, &d->rcItem, DT_LEFT|DT_VCENTER|DT_SINGLELINE); return TRUE; }
    }
    return DefWindowProcA(h, m, w, l);
}
static void check(int ok, const char *what) { printf("%s %s\n", ok ? "PASS" : "FAIL", what); if (!ok) fails++; }
static void pump(DWORD ms)
{
    DWORD end = GetTickCount() + ms; MSG msg;
    while ((LONG)(end - GetTickCount()) > 0) { while (PeekMessageA(&msg, 0, 0, 0, PM_REMOVE)) DispatchMessageA(&msg); Sleep(10); }
}
int main(void)
{
    INITCOMMONCONTROLSEX icc = { sizeof icc, ICC_STANDARD_CLASSES }; InitCommonControlsEx(&icc);
    WNDCLASSA wc = { 0 }; wc.lpfnWndProc = proc; wc.hInstance = GetModuleHandleA(0); wc.lpszClassName = "pmdrift";
    wc.hCursor = LoadCursorA(0, (LPCSTR)IDC_ARROW); RegisterClassA(&wc);
    HWND top = CreateWindowA("pmdrift", "pmdrift", WS_OVERLAPPEDWINDOW|WS_VISIBLE, 100, 100, 300, 300, 0, 0, 0, 0);
    parent = CreateWindowA("pmdrift", "", WS_CHILD|WS_VISIBLE|WS_CLIPCHILDREN, 5, 5, 217, 240, top, 0, 0, 0);
    const char *names[3] = { "From", "Direction 1", "Direction 2" };
    for (int i = 0; i < 3; i++)
        hdr[i] = CreateWindowExA(WS_EX_TRANSPARENT, "Button", names[i], WS_CHILD|WS_VISIBLE|WS_TABSTOP|BS_OWNERDRAW,
                                 4, 8 + 70 * i, 209, 17, parent, (HMENU)(INT_PTR)(100 + i), 0, 0);
    chk = CreateWindowA("Button", "Draft outward", WS_CHILD|WS_VISIBLE|BS_AUTOCHECKBOX, 36, 40, 178, 19, parent, (HMENU)200, 0, 0);
    pump(1500);
    RECT r0, r; GetWindowRect(parent, &r0);
    int bad = 0;
    for (int i = 0; i < 3; i++) { GetWindowRect(hdr[i], &r); OffsetRect(&r, -r0.left, -r0.top);
        printf("header %d at %ld,%ld %ldx%ld\n", i, r.left, r.top, r.right - r.left, r.bottom - r.top);
        if (r.left != 4 || r.right - r.left != 209) bad++; }
    printf("parent WM_PAINT %d, WM_PRINTCLIENT %d\n", paints, prints);
    {   /* the check box's glyph and label must be on screen: count pixels that are not the background */
        RECT cr; GetClientRect(chk, &cr); HDC cdc = GetDC(chk); COLORREF bg = GetSysColor(COLOR_WINDOW); int ink = 0, same = 0, black = 0;
        for (int y = 0; y < cr.bottom; y++) for (int x = 0; x < cr.right; x++) {
            COLORREF c = GetPixel(cdc, x, y);
            if (c == bg) same++; else if (c == 0) black++; else ink++; }
        if (GetEnvironmentVariableA("PMDRIFT_DUMP", 0, 0))
            for (int y = 0; y < cr.bottom; y++) { for (int x = 0; x < 90 && x < cr.right; x++) { COLORREF c = GetPixel(cdc, x, y);
                putchar(c == bg ? '.' : c == 0 ? '#' : '+'); } putchar('\n'); }
        ReleaseDC(chk, cdc);
        printf("check box: %d background, %d black, %d other pixels\n", same, black, ink);
        check(same > 200 && ink + black > 40 && black < same, "check box draws after the parent released the DC it was given");
    }
    check(!bad, "headers keep their position when the parent repaints");
    check(paints < 10, "parent does not repaint in a loop");

    /* Wine user32 test (win.c test_SetWindowPos): child + HWND_TOPMOST/NOTOPMOST ignores move/size */
    HWND c = CreateWindowA("Static", "c", WS_CHILD|WS_VISIBLE, 10, 20, 30, 40, top, 0, 0, 0);
    RECT a, b;
    GetWindowRect(c, &a); BOOL ret = SetWindowPos(c, HWND_TOPMOST, 1, 2, 3, 4, 0); GetWindowRect(c, &b);
    check(ret && EqualRect(&a, &b), "child + HWND_TOPMOST: returns TRUE, rect unchanged");
    GetWindowRect(c, &a); ret = SetWindowPos(c, HWND_NOTOPMOST, 11, 12, 13, 14, 0); GetWindowRect(c, &b);
    check(ret && EqualRect(&a, &b), "child + HWND_NOTOPMOST: returns TRUE, rect unchanged");
    ret = SetWindowPos(c, HWND_TOPMOST, 1, 2, 3, 4, SWP_NOZORDER); GetWindowRect(c, &b);
    POINT p = { b.left, b.top }; ScreenToClient(top, &p);
    check(ret && p.x == 1 && p.y == 2 && b.right - b.left == 3, "child + HWND_TOPMOST + SWP_NOZORDER still moves");
    ret = SetWindowPos(c, HWND_TOP, 5, 6, 7, 8, 0); GetWindowRect(c, &b);
    p.x = b.left; p.y = b.top; ScreenToClient(top, &p);
    check(ret && p.x == 5 && p.y == 6 && b.right - b.left == 7, "child + HWND_TOP moves");
    ret = SetWindowPos(top, HWND_TOPMOST, 120, 130, 310, 320, 0); GetWindowRect(top, &b);
    check(ret && b.left == 120 && b.top == 130 && b.right - b.left == 310, "top-level + HWND_TOPMOST moves");
    SetWindowPos(top, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE|SWP_NOSIZE);
    if (GetEnvironmentVariableA("PMDRIFT_STAY", 0, 0)) pump(600000);
    DestroyWindow(top);
    printf("%d failure(s)\n", fails);
    return fails;
}
