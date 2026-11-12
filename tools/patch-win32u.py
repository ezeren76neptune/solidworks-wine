#!/usr/bin/env python3
"""Stop Wine's win32u.so sending WM_CAPTURECHANGED to a window that keeps the capture.

usage: patch-win32u.py IN.so OUT.so

Binary form of Denis Bonnenfant's patch for Wine bug 27403 (0002-win32u-Don-t-
send-WM_CAPTURECHANGED-when-capture-is-set-to-the-same-window): in
set_capture_window(), `if (previous)` becomes `if (previous && previous != hwnd)`.
Without it SOLIDWORKS' PropertyManager buttons (green check, type selectors)
lose BN_CLICKED: the spurious message makes their subclass release capture
between button-down and button-up.

The call to send_message() there is redirected to a stub placed in the padding
after .plt, which returns without sending when previous (rdi) == hwnd (rcx).
Exits non-zero, writing nothing, if the build does not look as expected.
"""
import struct, sys

# mov rcx,r13; xor edx,edx; mov esi,WM_CAPTURECHANGED; mov rdi,r14; call send_message
SITE = bytes.fromhex('4c89e9' '31d2' 'be15020000' '4c89f7' 'e8')


def sections(d):
    shoff = struct.unpack_from('<Q', d, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', d, 0x3a)
    raw = [struct.unpack_from('<IIQQQQ', d, shoff + i * shentsize) for i in range(shnum)]
    stro = raw[shstrndx][4]
    out = {}
    for name, typ, flags, addr, off, size in raw:
        out[d[stro + name:d.index(b'\0', stro + name)].decode()] = (flags, addr, off, size)
    return out


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    if d[:4] != b'\x7fELF' or d[4] != 2:
        return 'not a 64-bit ELF file'
    if d.count(SITE) != 1:
        return 'set_capture_window call site not found'
    site = d.find(SITE) + len(SITE) - 1          # the call instruction
    secs = sections(d)
    plt, text = secs.get('.plt'), secs.get('.text')
    if not plt or not text:
        return 'missing .plt/.text'
    # offsets equal addresses in the first (executable) LOAD segment of this build
    if plt[1] != plt[2] or text[1] != text[2]:
        return 'unexpected section layout'
    cave = plt[1] + plt[3]
    if text[1] - cave < 16 or any(b not in (0, 0xcc, 0x90) for b in d[cave:text[1]]):
        return 'no padding after .plt'
    cave = (cave + 3) & ~3
    target = site + 5 + struct.unpack_from('<i', d, site + 1)[0]   # send_message
    stub = bytes.fromhex('4839cf' '7405') + b'\xe9' + struct.pack('<i', target - (cave + 10)) + b'\xc3'
    if cave + len(stub) > text[1]:
        return 'padding too small'
    d[cave:cave + len(stub)] = stub
    struct.pack_into('<i', d, site + 1, cave - (site + 5))
    open(dst, 'wb').write(d)
    print('%s: WM_CAPTURECHANGED same-window check added (site %#x, stub %#x)' % (dst, site, cave))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-win32u: ' + err)
