/* seektest: the SOLIDWORKS Installation Manager's Connect call: HTTP/1.0 GET, flags a0600001,
   InternetSetFilePointer(0, FILE_BEGIN) before the first read. Prints what InternetReadFile returns. */
#include <windows.h>
#include <wininet.h>
#include <stdio.h>
int main(void)
{
    HINTERNET s = InternetOpenW(L"sldIM", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
    HINTERNET c = InternetConnectW(s, L"im.solidworks.com", 80, NULL, NULL, INTERNET_SERVICE_HTTP, 0, 1);
    HINTERNET r = HttpOpenRequestW(c, L"GET", L"/2026/Connect.aspx?Release=20260-40502-1100-100&Debug=0&ini=1&osa=131072:0:2&lid=1033&app=I&cx=1:-1&cm=-1&lfr=&lfp=&lfv=",
                                   L"HTTP/1.0", NULL, NULL, 0xa0600001, 1);
    if (!s || !c || !r || !HttpSendRequestW(r, NULL, 0, NULL, 0)) { printf("request failed %lu\n", GetLastError()); return 1; }
    DWORD pos = InternetSetFilePointer(r, 0, NULL, FILE_BEGIN, 0);
    printf("InternetSetFilePointer -> %lu (err %lu)\n", pos, GetLastError());
    char buf[4096]; DWORD n, total = 0;
    while (InternetReadFile(r, buf + total, sizeof buf - 1 - total, &n) && n) total += n;
    buf[total] = 0;
    printf("read %lu bytes:\n%s\n", total, buf);
    return total ? 0 : 2;
}
