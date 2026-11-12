/* InternetSetCookieEx2 for Wine's wininet (missing in Wine <= 11.20 and Proton).
 * Dassault's JS0LCC.dll uses it to hand the WebView2 sign-in cookies to WinINet;
 * without it the launcher jumps through a null pointer right after sign-in.
 * Built as a position-independent blob with no imports and injected into a
 * private copy of wininet.dll by pe-inject.py, which fills the slot below
 * with the distance to the DLL's own InternetSetCookieExW. */
typedef unsigned short WCHAR;
typedef unsigned int DWORD;
typedef unsigned long long u64;

typedef struct {
    WCHAR *name, *value, *domain, *path;
    DWORD flags, expires_lo, expires_hi;
    int expires_set;
} COOKIE2;

typedef __attribute__((ms_abi)) DWORD (*set_cookie_t)(const WCHAR *, const WCHAR *, const WCHAR *, DWORD, u64);

#define COOKIE_SECURE 0x1
#define COOKIE_HTTPONLY 0x2000
#define CAP 4096

__attribute__((used)) const volatile int slot_InternetSetCookieExW = 0x5a5a5a5a;

struct out { WCHAR *b; unsigned n; int over; };

static void put_w(struct out *o, const WCHAR *s)
{
    while (*s) { if (o->n + 1 >= CAP) { o->over = 1; return; } o->b[o->n++] = *s++; }
}

static void put_a(struct out *o, const char *s)
{
    while (*s) { if (o->n + 1 >= CAP) { o->over = 1; return; } o->b[o->n++] = (unsigned char)*s++; }
}

static void put_n(struct out *o, unsigned v, int width)
{
    char t[12];
    int i = 11;
    t[i] = 0;
    do { t[--i] = '0' + v % 10; v /= 10; width--; } while (v || width > 0);
    put_a(o, t + i);
}

static void put_3(struct out *o, const char *table, unsigned index)
{
    char t[4];
    t[0] = table[index * 3]; t[1] = table[index * 3 + 1]; t[2] = table[index * 3 + 2]; t[3] = 0;
    put_a(o, t);
}

/* RFC 1123 date from a FILETIME */
static void put_date(struct out *o, DWORD lo, DWORD hi)
{
    long long secs = (long long)((((u64)hi << 32) | lo) / 10000000ULL) - 11644473600LL;
    long long days = secs / 86400, z, era;
    unsigned rem, doe, yoe, doy, mp, d, m;
    int y;

    rem = (unsigned)(secs % 86400);
    if (secs < 0) { days = 0; rem = 0; }
    z = days + 719468;
    era = z / 146097;
    doe = (unsigned)(z - era * 146097);
    yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    mp = (5 * doy + 2) / 153;
    d = doy - (153 * mp + 2) / 5 + 1;
    m = mp < 10 ? mp + 3 : mp - 9;
    y = (int)yoe + (int)era * 400 + (m <= 2);

    put_3(o, "ThuFriSatSunMonTueWed", (unsigned)(days % 7));
    put_a(o, ", ");
    put_n(o, d, 2);
    put_a(o, " ");
    put_3(o, "JanFebMarAprMayJunJulAugSepOctNovDec", m - 1);
    put_a(o, " ");
    put_n(o, (unsigned)y, 4);
    put_a(o, " ");
    put_n(o, rem / 3600, 2);
    put_a(o, ":");
    put_n(o, rem / 60 % 60, 2);
    put_a(o, ":");
    put_n(o, rem % 60, 2);
    put_a(o, " GMT");
}

__attribute__((ms_abi)) DWORD InternetSetCookieEx2(const WCHAR *url, const COOKIE2 *c, const WCHAR *p3p,
                                                   DWORD flags, DWORD *state)
{
    WCHAR buf[CAP];
    struct out o = { buf, 0, 0 };
    set_cookie_t set;
    DWORD r;

    (void)p3p;
    if (state) *state = 0;
    if (!url || !c || !c->name) return 87;   /* ERROR_INVALID_PARAMETER */

    if (c->value) put_w(&o, c->value);
    if (c->domain && *c->domain) { put_a(&o, "; domain="); put_w(&o, c->domain); }
    if (c->path && *c->path) { put_a(&o, "; path="); put_w(&o, c->path); }
    if (c->expires_set) { put_a(&o, "; expires="); put_date(&o, c->expires_lo, c->expires_hi); }
    if (c->flags & COOKIE_SECURE) put_a(&o, "; secure");
    if (c->flags & COOKIE_HTTPONLY) put_a(&o, "; httponly");
    if (o.over) return 122;                  /* ERROR_INSUFFICIENT_BUFFER */
    buf[o.n] = 0;

    set = (set_cookie_t)((const char *)&slot_InternetSetCookieExW + slot_InternetSetCookieExW);
    r = set(url, c->name, buf, flags | COOKIE_HTTPONLY, 0);
    if (state) *state = r;
    return r ? 0 : 4317;                     /* ERROR_INVALID_OPERATION */
}
