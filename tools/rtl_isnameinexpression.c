/* RtlIsNameInExpression for Wine's ntdll (missing in Wine <= 11.20 and Proton).
 * Dassault's V6 runtime (3DEXPERIENCE SOLIDWORKS) resolves it with GetProcAddress
 * and gives up on directory listing when it is absent.
 * Built as a self-contained, position-independent blob (no imports, no data)
 * and injected into a private copy of ntdll.dll by pe-inject.py.
 * Semantics follow FsRtlIsNameInExpression: '*', '?', and the DOS wildcards
 * '<' (DOS_STAR), '>' (DOS_QM), '"' (DOS_DOT). Case folding covers ASCII and Latin-1. */
typedef unsigned short WCHAR;
typedef struct { unsigned short Length, MaximumLength; WCHAR *Buffer; } USTR;

static inline WCHAR up(WCHAR c)
{
    if (c >= 'a' && c <= 'z') return c - 32;
    if (c >= 0xe0 && c <= 0xfe && c != 0xf7) return c - 32;
    return c;
}

__attribute__((ms_abi)) unsigned char RtlIsNameInExpression(const USTR *expr, const USTR *name,
                                                            unsigned char ignore_case, const WCHAR *table)
{
    const WCHAR *e, *n;
    unsigned int el, nl, ei = 0, ni = 0, star_e = ~0u, star_n = 0, last_dot = ~0u, i;
    int star_dos = 0;

    (void)table;
    if (!expr || !name) return 0;
    e = expr->Buffer; n = name->Buffer;
    el = expr->Length / 2; nl = name->Length / 2;
    if (!el) return nl == 0;
    for (i = 0; i < nl; i++) if (n[i] == '.') last_dot = i;

    while (ni < nl)
    {
        if (ei < el)
        {
            WCHAR ec = e[ei], nc = n[ni];
            if (ec == '*') { star_e = ei++; star_n = ni; star_dos = 0; continue; }
            if (ec == '<') { star_e = ei++; star_n = ni; star_dos = 1; continue; }
            if (ec == '?') { ei++; ni++; continue; }
            if (ec == '>')
            {
                if (nc == '.') { while (ei < el && e[ei] == '>') ei++; continue; }
                ei++; ni++; continue;
            }
            if (ec == '"')
            {
                if (nc == '.') { ei++; ni++; continue; }
            }
            else
            {
                if (ignore_case) { ec = up(ec); nc = up(nc); }
                if (ec == nc) { ei++; ni++; continue; }
            }
        }
        /* mismatch: let the last star swallow one more character */
        if (star_e == ~0u) return 0;
        if (star_dos && last_dot != ~0u && star_n >= last_dot) return 0;
        ei = star_e + 1;
        ni = ++star_n;
    }
    while (ei < el && (e[ei] == '*' || e[ei] == '<' || e[ei] == '>' || e[ei] == '"')) ei++;
    return ei == el;
}
