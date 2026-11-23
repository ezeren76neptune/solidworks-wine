/* InternetErrorDlg for a 401/407 that asks for no credentials.
 * When the 3DEXPERIENCE sign-in has expired, the server answers the launcher's
 * /api/user/authn/status with a 401 that has no WWW-Authenticate header (its
 * sign-in is a web page, not HTTP authentication). Dassault's HTTP client
 * (JS0LCC) then calls InternetErrorDlg(ERROR_INTERNET_INCORRECT_PASSWORD) and
 * resends only on ERROR_INTERNET_FORCE_RETRY. Wine shows its username/password
 * box for any 401; with no scheme to answer, nothing typed there is ever sent,
 * so OK resends the same request forever. After the web sign-in, other
 * requests get 401s whose only challenge is `CAS realm='CAS Server'`, a scheme
 * no HTTP stack implements. Windows' dialog is driven by the authentication
 * scheme and shows nothing in either case. This wrapper returns
 * ERROR_CANCELLED (ERROR_SUCCESS when only filtering for errors) without UI
 * when the response offers no scheme WinINet can answer (Basic, Digest, NTLM,
 * Negotiate, Kerberos), which sends the launcher on to its WebView2 sign-in
 * page; every other case goes to Wine's InternetErrorDlg.
 * Injected into a private copy of wininet.dll by pe-inject.py, which points
 * the InternetErrorDlg export here and fills the slots below. */
typedef unsigned short WCHAR;
typedef unsigned int DWORD;
typedef int BOOL;

typedef __attribute__((ms_abi)) DWORD (*error_dlg_t)(void *, void *, DWORD, DWORD, void **);
typedef __attribute__((ms_abi)) BOOL (*query_info_t)(void *, DWORD, void *, DWORD *, DWORD *);

__attribute__((used)) const volatile int slot_InternetErrorDlg = 0x5a5a5a5a;
__attribute__((used)) const volatile int slot_HttpQueryInfoW = 0x5a5a5a5a;

#define ERROR_INSUFFICIENT_BUFFER 122
#define ERROR_CANCELLED 1223
#define ERROR_INTERNET_INCORRECT_PASSWORD 12014
#define ERROR_HTTP_HEADER_NOT_FOUND 12150
#define FLAGS_ERROR_UI_FILTER_FOR_ERRORS 0x1
#define HTTP_QUERY_STATUS_CODE 19
#define HTTP_QUERY_WWW_AUTHENTICATE 40
#define HTTP_QUERY_PROXY_AUTHENTICATE 41
#define HTTP_QUERY_FLAG_NUMBER 0x20000000

/* does the challenge start with an authentication scheme WinINet implements? */
static int known_scheme(const WCHAR *v)
{
    /* one string, not a pointer table: the blob is never relocated */
    static const char schemes[] = "basic\0digest\0ntlm\0negotiate\0kerberos\0";
    const char *s;
    unsigned k;
    while (*v == ' ' || *v == '\t') v++;
    for (s = schemes; *s; s += k + 1)
    {
        for (k = 0; s[k] && (v[k] | 0x20) == s[k]; k++);
        if (!s[k] && (!v[k] || v[k] == ' ' || v[k] == '\t' || v[k] == ',')) return 1;
        while (s[k]) k++;
    }
    return 0;
}

static DWORD last_error(void)
{
    DWORD e;
    __asm__ volatile ("movl %%gs:0x68, %0" : "=r"(e));     /* TEB LastErrorValue */
    return e;
}

static void set_last_error(DWORD e)
{
    __asm__ volatile ("movl %0, %%gs:0x68" :: "r"(e));
}

__attribute__((ms_abi)) DWORD InternetErrorDlg_wrap(void *hwnd, void *request, DWORD error, DWORD flags, void **data)
{
    error_dlg_t dlg = (error_dlg_t)((const char *)&slot_InternetErrorDlg + slot_InternetErrorDlg);
    query_info_t query = (query_info_t)((const char *)&slot_HttpQueryInfoW + slot_HttpQueryInfoW);

    if (request && (error == ERROR_INTERNET_INCORRECT_PASSWORD || (!error && (flags & FLAGS_ERROR_UI_FILTER_FOR_ERRORS))))
    {
        DWORD saved = last_error(), status = 0, len = sizeof(status), index = 0;
        if (query(request, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &len, &index)
            && (status == 401 || status == 407))
        {
            DWORD what = status == 401 ? HTTP_QUERY_WWW_AUTHENTICATE : HTTP_QUERY_PROXY_AUTHENTICATE;
            WCHAR buf[512];
            int answerable = 0, n;
            index = 0;
            for (n = 0; n < 32 && !answerable; n++)          /* one header per challenge */
            {
                len = sizeof(buf) - sizeof(WCHAR);
                if (query(request, what, buf, &len, &index))
                {
                    buf[len / sizeof(WCHAR)] = 0;
                    answerable = known_scheme(buf);
                }
                else if (last_error() == ERROR_HTTP_HEADER_NOT_FOUND) break;
                else answerable = 1;                          /* unreadable: let Wine decide */
            }
            if (n == 32) answerable = 1;
            if (!answerable)
            {
                set_last_error(saved);
                return error ? ERROR_CANCELLED : 0;
            }
        }
        set_last_error(saved);
    }
    return dlg(hwnd, request, error, flags, data);
}
