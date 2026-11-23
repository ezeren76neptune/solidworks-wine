#!/usr/bin/env python3
"""Let the old Microsoft core fonts be smoothed at every size, as current Windows fonts are.

usage: fix-font-gasp.py FONT.ttf...     (rewrites the files in place; prints what changed)

winetricks corefonts installs the 1998-2000 versions of Arial, Verdana, Times New
Roman, Georgia and friends. Their 'gasp' tables say "grid-fit, no grayscale" for
roughly 9 to 17 pixels, the size of ordinary text. Chromium (WebView2: the
3DEXPERIENCE sign-in page) treats a font in such a range like a bitmap font and
draws it aliased with hinted spacing, so the page's text looked jagged and
unevenly spaced. The fonts that ship with Windows today allow grayscale at every
size. This adds the "grayscale" flag to every range that grid-fits without it
and fixes the table checksum and head.checkSumAdjustment. Files without such a
range are left alone, so running it again changes nothing.
"""
import struct, sys

GASP_GRIDFIT, GASP_DOGRAY = 1, 2


def checksum(b):
    b = b + b'\0' * (-len(b) % 4)
    return sum(struct.unpack('>%dI' % (len(b) // 4), b)) & 0xffffffff


def fix(path):
    d = bytearray(open(path, 'rb').read())
    if d[:4] not in (b'\0\1\0\0', b'true'):
        return 'not a TrueType font'
    n = struct.unpack_from('>H', d, 4)[0]
    dirs = {bytes(d[12 + i * 16:16 + i * 16]): 12 + i * 16 for i in range(n)}
    if b'gasp' not in dirs:
        return None
    rec = dirs[b'gasp']
    _, off, length = struct.unpack_from('>III', d, rec + 4)
    count = struct.unpack_from('>H', d, off + 2)[0]
    changed = []
    for i in range(count):
        ppem, flags = struct.unpack_from('>HH', d, off + 4 + 4 * i)
        if flags & GASP_GRIDFIT and not flags & GASP_DOGRAY:
            struct.pack_into('>H', d, off + 6 + 4 * i, flags | GASP_DOGRAY)
            changed.append(ppem)
    if not changed:
        return None
    struct.pack_into('>I', d, rec + 4, checksum(bytes(d[off:off + length])))
    if b'head' in dirs:
        hoff = struct.unpack_from('>I', d, dirs[b'head'] + 8)[0]
        struct.pack_into('>I', d, hoff + 8, 0)
        struct.pack_into('>I', d, hoff + 8, (0xB1B0AFBA - checksum(bytes(d))) & 0xffffffff)
    open(path, 'wb').write(d)
    return 'grayscale added up to %s ppem' % '/'.join(map(str, changed))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for p in sys.argv[1:]:
        r = fix(p)
        if r:
            print('%s: %s' % (p, r))
