/* DrawThemeParentBackground that lets the parent paint into a private memory DC.
 * Themed buttons (check boxes, radio buttons, group boxes, push buttons) call
 * DrawThemeParentBackground from their WM_PAINT, and Wine passes the button's own
 * BeginPaint DC to the parent's WM_ERASEBKGND and WM_PRINTCLIENT. SOLIDWORKS'
 * PropertyManager pages (slduiu.dll, uiPropertyPage_c) end their WM_PRINTCLIENT
 * handler with ReleaseDC(page, hdc) on the DC they were handed. Wine releases a
 * cache DC whatever window is named (as Windows does) and disables it, so every
 * drawing call the button made afterwards failed: the Extrude PropertyManager's
 * "Draft outward" and the Direction 2 check box stayed blank. On Windows the
 * button's themed painting goes through a buffered-paint memory DC, so the parent
 * never gets the window DC and that ReleaseDC does nothing.
 * This wrapper copies what is under the control into a memory DC, runs Wine's
 * DrawThemeParentBackground on it (same messages, same offsets), and copies the
 * result back to the caller's DC. If the memory DC can't be made or read from the
 * caller's DC (printer or metafile DCs), Wine's function runs on the caller's DC.
 * Injected into a private copy of uxtheme.dll by pe-inject.py, which points the
 * export here and fills the slots below. */
typedef void *HANDLE;
typedef unsigned int DWORD;
typedef int BOOL, HRESULT;
typedef struct { int left, top, right, bottom; } RECT;

typedef __attribute__((ms_abi)) HRESULT (*parent_bg_t)(HANDLE, HANDLE, RECT *);
typedef __attribute__((ms_abi)) BOOL (*client_rect_t)(HANDLE, RECT *);
typedef __attribute__((ms_abi)) HANDLE (*compat_dc_t)(HANDLE);
typedef __attribute__((ms_abi)) HANDLE (*compat_bitmap_t)(HANDLE, int, int);
typedef __attribute__((ms_abi)) HANDLE (*select_t)(HANDLE, HANDLE);
typedef __attribute__((ms_abi)) BOOL (*bitblt_t)(HANDLE, int, int, int, int, HANDLE, int, int, DWORD);
typedef __attribute__((ms_abi)) BOOL (*delete_t)(HANDLE);

__attribute__((used)) const volatile int slot_DrawThemeParentBackground = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_GetClientRect = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_CreateCompatibleDC = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_CreateCompatibleBitmap = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_SelectObject = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_BitBlt = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_DeleteObject = 0x5a5a5a5a;
__attribute__((used)) const volatile int symslot_DeleteDC = 0x5a5a5a5a;

#define SLOT(type, name) ((type)((const char *)&slot_##name + slot_##name))
#define SYMSLOT(type, name) ((type)((const char *)&symslot_##name + symslot_##name))
#define SRCCOPY 0x00cc0020

__attribute__((ms_abi)) HRESULT DrawThemeParentBackground_wrap(HANDLE hwnd, HANDLE hdc, RECT *prc)
{
    parent_bg_t orig = SLOT(parent_bg_t, DrawThemeParentBackground);
    select_t select = SYMSLOT(select_t, SelectObject);
    bitblt_t bitblt = SYMSLOT(bitblt_t, BitBlt);
    delete_t delete_object = SYMSLOT(delete_t, DeleteObject), delete_dc = SYMSLOT(delete_t, DeleteDC);
    RECT client, r;
    HANDLE mem, bmp, old;
    HRESULT hr;

    if (!hwnd || !hdc || !SYMSLOT(client_rect_t, GetClientRect)(hwnd, &client) ||
        client.right <= 0 || client.bottom <= 0)
        return orig(hwnd, hdc, prc);
    if (!(mem = SYMSLOT(compat_dc_t, CreateCompatibleDC)(hdc))) return orig(hwnd, hdc, prc);
    if (!(bmp = SYMSLOT(compat_bitmap_t, CreateCompatibleBitmap)(hdc, client.right, client.bottom)))
    {
        delete_dc(mem);
        return orig(hwnd, hdc, prc);
    }
    old = select(mem, bmp);
    if (!bitblt(mem, 0, 0, client.right, client.bottom, hdc, 0, 0, SRCCOPY))
    {
        select(mem, old);
        delete_object(bmp);
        delete_dc(mem);
        return orig(hwnd, hdc, prc);
    }
    hr = orig(hwnd, mem, prc);
    r = prc ? *prc : client;
    bitblt(hdc, r.left, r.top, r.right - r.left, r.bottom - r.top, mem, r.left, r.top, SRCCOPY);
    select(mem, old);
    delete_object(bmp);
    delete_dc(mem);
    return hr;
}
