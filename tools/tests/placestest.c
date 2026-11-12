#define COBJMACROS
#include <windows.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <stdio.h>
static void name(IShellFolder *sf, LPCITEMIDLIST p, DWORD f, WCHAR *out) {
    STRRET s; out[0] = 0;
    if (SUCCEEDED(IShellFolder_GetDisplayNameOf(sf, p, f, &s))) StrRetToBufW(&s, p, out, MAX_PATH);
}
int wmain(void) {
    IShellFolder *desk, *sub; IEnumIDList *en; LPITEMIDLIST p; WCHAR a[MAX_PATH], b[MAX_PATH];
    CoInitialize(NULL);
    SHGetDesktopFolder(&desk);
    IShellFolder_EnumObjects(desk, NULL, SHCONTF_FOLDERS, &en);
    while (IEnumIDList_Next(en, 1, &p, NULL) == S_OK) {
        SFGAOF at = SFGAO_FOLDER|SFGAO_FILESYSTEM|SFGAO_HASSUBFOLDER;
        IShellFolder_GetAttributesOf(desk, 1, (LPCITEMIDLIST *)&p, &at);
        name(desk, p, SHGDN_NORMAL, a); name(desk, p, SHGDN_FORPARSING, b);
        wprintf(L"desktop item: %-12ls attrs=%08lx parse=%ls\n", a, at, b);
        CoTaskMemFree(p);
    }
    IEnumIDList_Release(en);
    /* bind into Downloads (place 3), list two children with full paths */
    if (SUCCEEDED(SHParseDisplayName(L"::{5E1F0003-0C1D-4A5B-8C7D-53574C494E58}", NULL, &p, 0, NULL))) {
        SHGetPathFromIDListW(p, a); wprintf(L"Downloads place path: %ls\n", a);
        if (SUCCEEDED(IShellFolder_BindToObject(desk, p, NULL, &IID_IShellFolder, (void **)&sub))) {
            LPITEMIDLIST c; int n = 0;
            IShellFolder_EnumObjects(sub, NULL, SHCONTF_FOLDERS|SHCONTF_NONFOLDERS, &en);
            while (n++ < 3 && IEnumIDList_Next(en, 1, &c, NULL) == S_OK) {
                LPITEMIDLIST full = ILCombine(p, c);
                SHGetPathFromIDListW(full, b); name(sub, c, SHGDN_NORMAL, a);
                wprintf(L"  child %ls -> %ls\n", a, b);
                ILFree(full); CoTaskMemFree(c);
            }
        } else wprintf(L"bind failed\n");
    } else wprintf(L"parse failed\n");
    return 0;
}
