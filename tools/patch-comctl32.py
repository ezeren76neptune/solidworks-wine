#!/usr/bin/env python3
"""Make Wine's comctl32 v6 header control tolerate HDM_LAYOUT with a NULL HDLAYOUT.

usage: patch-comctl32.py IN.dll OUT.dll

Windows' Header_OnLayout returns FALSE when lParam is NULL; Wine's inlined
HEADER_Layout dereferences it, and a SOLIDWORKS task pane sends exactly that
at startup. This redirects the start of that code to a small stub, placed in
the spare room at the end of .text, that returns 0 from HEADER_WindowProc when
lParam (kept in rbp) is NULL. Exits non-zero, writing nothing, if the build
does not look as expected.
"""
import struct, sys

SITE = bytes.fromhex('488b4508' '48c7400800000000' '488b5500' '488b4508' '8b12' '895010')
PROLOGUE = bytes.fromhex('4157' '4156' '4155' '4154' '55' '57' '56' '53' '4881ec')
EPILOGUE_POPS = bytes.fromhex('5b' '5e' '5f' '5d' '415c' '415d' '415e' '415f')


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
    struct.pack_into('<I', d, text + 8, cave + len(stub))
    open(dst, 'wb').write(d)
    print('%s: HDM_LAYOUT NULL check added (site %#x, stub %#x)' % (dst, va + site - raw, va + cave))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-comctl32: ' + err)
