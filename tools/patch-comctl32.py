#!/usr/bin/env python3
"""Three fixes in Wine's comctl32 v6 for SOLIDWORKS.

usage: patch-comctl32.py IN.dll OUT.dll

1. Header control: tolerate HDM_LAYOUT with a NULL HDLAYOUT. Windows'
   Header_OnLayout returns FALSE when lParam is NULL; Wine's inlined
   HEADER_Layout dereferences it, and a SOLIDWORKS task pane sends exactly that
   at startup. The start of that code jumps to a stub that returns 0 from
   HEADER_WindowProc when lParam (kept in rbp) is NULL. Required.

2. Toolbar background. With a theme active, Wine's toolbar hands WM_ERASEBKGND
   to its parent and paints nothing itself when the parent says it erased. The
   parent of SOLIDWORKS' shortcut bar (the S key) is its main frame, which
   claims the erase without painting, so the grid slot without a button stayed
   black. TOOLBAR_DoEraseBackground now fills the client area with the toolbar
   class colour (COLOR_BTNFACE) before asking the parent, which still paints
   over it when it does paint. Skipped with a warning if the code is not found.

3. Toolbar drawn into a DC the caller supplies. SOLIDWORKS paints its shortcut
   bar off-screen: the toolbar gets WM_PRINTCLIENT (or WM_PAINT with a DC) for a
   memory bitmap, which starts out black, and the result is copied to the
   screen. Wine's toolbar erases its background only through BeginPaint or, in
   v6, when it has TBSTYLE_TRANSPARENT, so on that path nothing was erased:
   SOLIDWORKS draws behind each button itself, and the toolbar area without a
   button (beside the last column, sized for the search box) stayed black.
   The supplied-DC call to TOOLBAR_Refresh now goes through a stub that first
   runs the toolbar's own erase (TOOLBAR_DoEraseBackground: parent's background,
   or fix 2's fill) unless redraw is off or the toolbar is transparent (Refresh
   erases those itself). Found through the DLL's COFF symbols; skipped with a
   warning if they or the code are not as expected.

Stubs go in the spare room at the end of .text. Exits non-zero, writing
nothing, if the build does not look as expected for fix 1.
"""
import re, struct, sys

SITE = bytes.fromhex('488b4508' '48c7400800000000' '488b5500' '488b4508' '8b12' '895010')
PROLOGUE = bytes.fromhex('4157' '4156' '4155' '4154' '55' '57' '56' '53' '4881ec')
EPILOGUE_POPS = bytes.fromhex('5b' '5e' '5f' '5d' '415c' '415d' '415e' '415f')
# TOOLBAR_DoEraseBackground, themed branch: movq $0,0x30(%rsp) (pt); mov hwndSelf(%rbx),%rcx; call *GetParent;
# ... call *MapWindowPoints ... call *OffsetWindowOrgEx ... mov $WM_ERASEBKGND,%edx; call *SendMessageW
ERASE = re.compile(rb'(\x48\xc7\x44\x24(.)\x00\x00\x00\x00)\x48\x8b\x8b(....)\xff\x15....'
                   rb'.{0,40}?\xff\x15(....).{0,40}?\xff\x15(....).{0,30}?\xba\x14\x00\x00\x00\xff\x15', re.S)


def imports(d, pe):
    """{name: IAT slot RVA} for user32/gdi32 imports"""
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    opt = pe + 24
    sectab = opt + struct.unpack_from('<H', d, pe + 20)[0]
    secs = [struct.unpack_from('<IIII', d, sectab + 40 * i + 8) for i in range(nsec)]
    def off(rva):
        for vsize, va, rsize, raw in secs:
            if va <= rva < va + max(vsize, rsize):
                return raw + rva - va
        return None
    imp_rva = struct.unpack_from('<I', d, opt + 112 + 8)[0]                 # data directory 1 (PE32+)
    out = {}
    o = off(imp_rva)
    while o is not None:
        ilt, _, _, name_rva, iat = struct.unpack_from('<IIIII', d, o)
        if not name_rva:
            break
        i = 0
        while True:
            entry = struct.unpack_from('<Q', d, off(ilt or iat) + 8 * i)[0]
            if not entry:
                break
            if not entry >> 63:
                n = off(entry & 0x7fffffff) + 2
                out[d[n:d.index(b'\0', n)].decode()] = iat + 8 * i
            i += 1
        o += 20
    return out


# ToolbarWindowProc, WM_PAINT/WM_PRINTCLIENT with wParam = hdc: test %reg,%reg; je BeginPaint path;
# testb $8,__wine_dbch_toolbar; jne trace; lea ps,%r8; mov hdc,%rdx; mov infoPtr,%rcx; [xor %ebx,%ebx]; call TOOLBAR_Refresh
PAINTDC = re.compile(rb'\x48\x85[\xc0-\xff]\x0f\x84....\xf6\x05....\x08\x0f\x85....'
                     rb'\x4c\x8d\x44\x24.\x48\x89[\xc0-\xff]\x48\x89[\xc0-\xff](?:\x31\xdb)?(\xe8)(....)', re.S)
# TOOLBAR_Refresh start: mov bDoRedraw(%rcx),%ebp ... testb $0x80,dwStyle+1(%rcx) (TBSTYLE_TRANSPARENT)
REFRESH = re.compile(rb'\x8b\xa9(....).{0,40}?\xf6\x81(....)\x80', re.S)


def coff_symbols(d, pe):
    """{name: RVA} from the COFF symbol table Wine's PE DLLs keep"""
    symptr, nsym = struct.unpack_from('<II', d, pe + 12)
    if not symptr or not nsym:
        return {}
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    sectab = pe + 24 + struct.unpack_from('<H', d, pe + 20)[0]
    secva = [struct.unpack_from('<I', d, sectab + 40 * i + 12)[0] for i in range(nsec)]
    strtab = symptr + 18 * nsym
    out, i = {}, 0
    while i < nsym:
        o = symptr + 18 * i
        raw_name, value, secno, _, _, naux = struct.unpack_from('<8sIhHBB', d, o)
        if raw_name[:4] == b'\0\0\0\0':
            n = strtab + struct.unpack_from('<I', raw_name, 4)[0]
            name = d[n:d.index(b'\0', n)]
        else:
            name = raw_name.rstrip(b'\0')
        if 0 < secno <= nsec:
            out.setdefault(name.decode('latin-1'), secva[secno - 1] + value)
        i += 1 + naux
    return out


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    sectab = pe + 24 + struct.unpack_from('<H', d, pe + 20)[0]
    text = None
    for i in range(struct.unpack_from('<H', d, pe + 6)[0]):
        o = sectab + 40 * i
        if bytes(d[o:o + 8]).rstrip(b'\0') == b'.text':
            vsize, va, rsize, raw = struct.unpack_from('<IIII', d, o + 8)
            text = o
    if text is None or d.count(SITE) != 1:
        return 'HDM_LAYOUT code not found'
    site = d.find(SITE)
    start = d.rfind(PROLOGUE, max(site - 0x800, 0), site)
    if start < 0 or bytes.fromhex('4c89cd') not in d[start:start + 0x40]:   # mov rbp,r9
        return 'unexpected HEADER_WindowProc prologue'
    frame = bytes(d[start + len(PROLOGUE):start + len(PROLOGUE) + 4])
    cave = (vsize + 15) // 16 * 16
    ret0 = bytes.fromhex('31c0' '4881c4') + frame + EPILOGUE_POPS + b'\xc3'
    stub = bytes.fromhex('4885ed') + b'\x75' + bytes([len(ret0)]) + ret0   # test rbp,rbp; jnz original
    stub += SITE[:12]
    stub += b'\xe9' + struct.pack('<i', (site + 12) - (raw + cave + len(stub) + 5))
    if cave + len(stub) > rsize:
        return 'no spare room in .text'
    d[raw + vsize:raw + cave] = b'\xcc' * (cave - vsize)
    d[raw + cave:raw + cave + len(stub)] = stub
    d[site:site + 12] = b'\xe9' + struct.pack('<i', (raw + cave) - (site + 5)) + b'\x90' * 7
    end = cave + len(stub)
    msg = '%s: HDM_LAYOUT NULL check added (site %#x, stub %#x)' % (dst, va + site - raw, va + cave)

    # 2. toolbar background: fill with COLOR_BTNFACE before the parent's WM_ERASEBKGND
    imp = imports(d, pe)
    found = list(ERASE.finditer(d))
    cave2 = (end + 15) // 16 * 16
    if len(found) == 1 and all(k in imp for k in ('GetClientRect', 'GetSysColorBrush', 'FillRect', 'MapWindowPoints', 'OffsetWindowOrgEx')):
        m = found[0]
        site2 = m.start(1)
        rva2 = va + site2 - raw
        def target(g):
            return va + m.start(g) - raw + 4 + struct.unpack('<i', m.group(g))[0]
        if target(4) != imp['MapWindowPoints'] or target(5) != imp['OffsetWindowOrgEx']:
            found = []
    if len(found) == 1:
        hwnd_off = struct.unpack('<i', m.group(3))[0]
        pt_off = m.group(2)[0]
        st = bytearray()
        srva = va + cave2
        def call_imp(name):
            return b'\xff\x15' + struct.pack('<i', imp[name] - (srva + len(st) + 6))
        st += b'\x48\x83\xec\x38'                                         # sub $0x38,%rsp
        st += b'\x48\x8b\x8b' + struct.pack('<i', hwnd_off)                # mov hwndSelf(%rbx),%rcx
        st += b'\x48\x8d\x54\x24\x20'                                     # lea 0x20(%rsp),%rdx
        st += call_imp('GetClientRect')
        st += b'\xb9\x0f\x00\x00\x00'                                     # mov $COLOR_BTNFACE,%ecx
        st += call_imp('GetSysColorBrush')
        st += b'\x49\x89\xc0\x48\x89\xf1\x48\x8d\x54\x24\x20'               # mov %rax,%r8; mov %rsi,%rcx (hdc); lea rect,%rdx
        st += call_imp('FillRect')
        st += b'\x48\x83\xc4\x38'                                         # add $0x38,%rsp
        st += b'\x48\xc7\x44\x24' + bytes([pt_off + 8]) + b'\x00\x00\x00\x00'  # the replaced movq $0,pt(%rsp)
        st += b'\xc3'
        if cave2 + len(st) <= rsize and d[site2 - 7:site2] != b'' and m.group(0)[9:12] == b'\x48\x8b\x8b':
            d[raw + end:raw + cave2] = b'\xcc' * (cave2 - end)
            d[raw + cave2:raw + cave2 + len(st)] = st
            d[site2:site2 + 9] = b'\xe8' + struct.pack('<i', srva - (rva2 + 5)) + b'\x90' * 4
            end = cave2 + len(st)
            msg += '; toolbar background fill (site %#x, stub %#x)' % (rva2, srva)
        else:
            print('patch-comctl32: no room for the toolbar background stub', file=sys.stderr)
    else:
        print('patch-comctl32: toolbar erase code not found, the shortcut bar may show a black area', file=sys.stderr)

    # 3. toolbar painted into a caller's DC: erase first
    syms = coff_symbols(d, pe)
    refresh, erase = syms.get('TOOLBAR_Refresh'), syms.get('TOOLBAR_DoEraseBackground.part.0')
    def rva_of(off):
        return va + off - raw
    sites = [m for m in PAINTDC.finditer(d, raw, raw + vsize)
             if refresh and rva_of(m.start(2)) + 4 + struct.unpack('<i', m.group(2))[0] == refresh]
    rm = REFRESH.search(d, raw + refresh - va, raw + refresh - va + 0x80) if refresh else None
    if len(sites) == 1 and erase and rm:
        redraw_off = struct.unpack('<I', rm.group(1))[0]
        style_hi = struct.unpack('<I', rm.group(2))[0]
        cave3 = (end + 15) // 16 * 16
        srva = va + cave3
        st = bytearray()
        def rel(to):                                               # rel32 of a call/jmp whose opcode byte was just added
            return struct.pack('<i', to - (srva + len(st) + 4))
        st += b'\x56\x57\x53'                                      # push %rsi; push %rdi; push %rbx
        st += b'\x48\x83\xec\x20'                                  # sub $0x20,%rsp
        st += b'\x48\x89\xce\x48\x89\xd7\x4c\x89\xc3'               # mov %rcx,%rsi; mov %rdx,%rdi; mov %r8,%rbx
        st += b'\x83\xb9' + struct.pack('<I', redraw_off) + b'\x00'  # cmpl $0,bDoRedraw(%rcx)
        st += b'\x74\x00'; j1 = len(st) - 1                          # je 1f
        st += b'\xf6\x81' + struct.pack('<I', style_hi) + b'\x80'    # testb $0x80,dwStyle+1(%rcx)
        st += b'\x75\x00'; j2 = len(st) - 1                          # jne 1f
        st += b'\x45\x31\xc0'                                       # xor %r8d,%r8d
        st += b'\xe8'; st += rel(erase)                               # call TOOLBAR_DoEraseBackground.part.0
        target = len(st)
        st[j1] = target - (j1 + 1)
        st[j2] = target - (j2 + 1)
        st += b'\x48\x89\xf1\x48\x89\xfa\x49\x89\xd8'               # 1: mov %rsi,%rcx; mov %rdi,%rdx; mov %rbx,%r8
        st += b'\x48\x83\xc4\x20\x5b\x5f\x5e'                       # add $0x20,%rsp; pop %rbx; pop %rdi; pop %rsi
        st += b'\xe9'; st += rel(refresh)                             # jmp TOOLBAR_Refresh
        if cave3 + len(st) <= rsize:
            site3 = sites[0].start(1)
            d[raw + end:raw + cave3] = b'\xcc' * (cave3 - end)
            d[raw + cave3:raw + cave3 + len(st)] = st
            d[site3 + 1:site3 + 5] = struct.pack('<i', srva - (rva_of(site3) + 5))
            end = cave3 + len(st)
            msg += '; toolbar erase before painting into a supplied DC (site %#x, stub %#x)' % (rva_of(site3), srva)
        else:
            print('patch-comctl32: no room for the toolbar paint stub', file=sys.stderr)
    else:
        print('patch-comctl32: toolbar paint code not found, the shortcut bar may show a black area', file=sys.stderr)
    struct.pack_into('<I', d, text + 8, end)
    open(dst, 'wb').write(d)
    print(msg)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-comctl32: ' + err)
