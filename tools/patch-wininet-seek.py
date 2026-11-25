#!/usr/bin/env python3
"""Keep already-received data when an app rewinds an HTTP response (InternetSetFilePointer).

usage: patch-wininet-seek.py IN.dll OUT.dll

The SOLIDWORKS Installation Manager sends its request, then calls
InternetSetFilePointer(hRequest, 0, NULL, FILE_BEGIN) before its first InternetReadFile.
Wine's HTTPREQ_SetFilePointer always empties the read buffer (read_pos = read_size = 0)
and relies on re-reading from the WinINet cache file. Dassault's server answers
"Cache-Control: no-cache, no-store", so Wine keeps no cache file, the body that arrived
with the headers is thrown away and the read returns 0 bytes: "Could not connect to the
SOLIDWORKS server". Windows keeps the data. Here, when the new position lies inside the
buffered data, the buffer is advanced instead of emptied; anything else behaves as before.

The site is the end of HTTPREQ_SetFilePointer, found by its exact instruction bytes:
    mov qword [rbx+read_pos], 0   ; read_pos = read_size = 0 (adjacent DWORDs)
    mov ecx, eax
    mov [rbx+content_pos], rcx
    jmp <leave the critical section and return>
It is replaced by a jump to a stub in the spare room at the end of .text. Nothing is
changed when the bytes are not found exactly once.
"""
import re
import struct
import sys

SITE = re.compile(rb'\x48\xc7\x83(....)\x00\x00\x00\x00\x89\xc1\x48\x89\x8b(....)\xeb(.)', re.S)
# 32-bit (i386-windows, the Installation Manager itself is 32-bit): esi = new position, ebx = req
#   mov [ebx+cp], esi ; mov dword [ebx+cp+4], 0 ; mov dword [ebx+rp], 0 ; mov dword [ebx+rp+4], 0 ; jmp
SITE32 = re.compile(rb'\x89\xb3(....)\xc7\x83(....)\x00\x00\x00\x00\xc7\x83(....)\x00\x00\x00\x00'
                    rb'\xc7\x83(....)\x00\x00\x00\x00\xeb(.)', re.S)


def stub32(m, here):
    """here: file offset of the stub; returns (stub bytes, site start, site end)"""
    cp, cph, rp, rs = (struct.unpack('<I', m.group(i))[0] for i in range(1, 5))
    if cph != cp + 4 or rs != rp + 4:
        return None
    back = m.end() + struct.unpack('<b', m.group(5))[0]
    s = bytearray()
    s += b'\x89\xf0'                                   # mov eax, esi           new position
    s += b'\x2b\x83' + struct.pack('<I', cp)           # sub eax, [ebx+cp]      distance into the buffer
    jb = len(s); s += b'\x72\x00'                      # jb discard
    s += b'\x83\xbb' + struct.pack('<I', cph) + b'\x00'   # cmp dword [ebx+cp+4], 0
    jne = len(s); s += b'\x75\x00'                     # jne discard
    s += b'\x3b\x83' + struct.pack('<I', rs)           # cmp eax, [ebx+read_size]
    ja = len(s); s += b'\x77\x00'                      # ja discard
    s += b'\x01\x83' + struct.pack('<I', rp)           # add [ebx+read_pos], eax
    s += b'\x29\x83' + struct.pack('<I', rs)           # sub [ebx+read_size], eax
    jmp = len(s); s += b'\xeb\x00'                     # jmp store
    discard = len(s)
    s += b'\xc7\x83' + struct.pack('<I', rp) + b'\x00' * 4
    s += b'\xc7\x83' + struct.pack('<I', rs) + b'\x00' * 4
    store = len(s)
    s += b'\x89\xb3' + struct.pack('<I', cp)           # mov [ebx+cp], esi
    s += b'\xc7\x83' + struct.pack('<I', cph) + b'\x00' * 4
    s += b'\xe9' + struct.pack('<i', back - (here + len(s) + 5))
    for at in (jb, jne, ja):
        s[at + 1] = discard - (at + 2)
    s[jmp + 1] = store - (jmp + 2)
    return bytes(s), rp, cp


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
    if text is None:
        return 'no .text section'
    if struct.unpack_from('<H', d, pe + 4)[0] == 0x14c:          # i386
        hits = list(SITE32.finditer(d, raw, raw + vsize))
        if len(hits) != 1:
            return 'HTTPREQ_SetFilePointer code not found (%d matches)' % len(hits)
        m = hits[0]
        cave = (vsize + 15) // 16 * 16
        r = stub32(m, raw + cave)
        if not r:
            return 'unexpected field layout'
        s, rp, cp = r
        if cave + len(s) > rsize:
            return 'no spare room in .text'
        d[raw + vsize:raw + cave] = b'\xcc' * (cave - vsize)
        d[raw + cave:raw + cave + len(s)] = s
        patch = b'\xe9' + struct.pack('<i', (raw + cave) - (m.start() + 5))
        d[m.start():m.end()] = patch + b'\x90' * (m.end() - m.start() - len(patch))
        struct.pack_into('<I', d, text + 8, cave + len(s))
        open(dst, 'wb').write(d)
        print('%s: InternetSetFilePointer keeps buffered data (32-bit; site %#x, stub %#x, read_pos %#x, content_pos %#x)'
              % (dst, va + m.start() - raw, va + cave, rp, cp))
        return None
    hits = list(SITE.finditer(d, raw, raw + vsize))
    if len(hits) != 1:
        return 'HTTPREQ_SetFilePointer code not found (%d matches)' % len(hits)
    m = hits[0]
    rp = struct.unpack('<I', m.group(1))[0]          # read_pos; read_size follows it
    cp = struct.unpack('<I', m.group(2))[0]          # content_pos (ULONGLONG)
    rs = rp + 4
    site = m.start()
    site_end = m.end()
    back = site_end + struct.unpack('<b', m.group(3))[0]   # where the original jmp went

    def rva(off):
        return va + off - raw

    cave = (vsize + 15) // 16 * 16
    s = bytearray()
    s += b'\x89\xc1'                                  # mov ecx, eax          new position
    s += b'\x48\x8b\x93' + struct.pack('<I', cp)      # mov rdx, [rbx+cp]     content_pos
    s += b'\x49\x89\xc8'                              # mov r8, rcx
    s += b'\x49\x29\xd0'                              # sub r8, rdx           distance into the buffer
    jb = len(s); s += b'\x72\x00'                     # jb discard
    s += b'\x44\x8b\x93' + struct.pack('<I', rs)      # mov r10d, [rbx+read_size]
    s += b'\x4d\x39\xd0'                              # cmp r8, r10
    ja = len(s); s += b'\x77\x00'                     # ja discard
    s += b'\x44\x01\x83' + struct.pack('<I', rp)      # add [rbx+read_pos], r8d
    s += b'\x44\x29\x83' + struct.pack('<I', rs)      # sub [rbx+read_size], r8d
    jmp = len(s); s += b'\xeb\x00'                    # jmp store
    discard = len(s)
    s += b'\x48\xc7\x83' + struct.pack('<I', rp) + b'\x00' * 4   # mov qword [rbx+read_pos], 0
    store = len(s)
    s += b'\x48\x89\x8b' + struct.pack('<I', cp)      # mov [rbx+cp], rcx
    s += b'\xe9' + struct.pack('<i', back - (raw + cave + len(s) + 5))   # jmp back
    s[jb + 1] = discard - (jb + 2)
    s[ja + 1] = discard - (ja + 2)
    s[jmp + 1] = store - (jmp + 2)
    if cave + len(s) > rsize:
        return 'no spare room in .text'
    d[raw + vsize:raw + cave] = b'\xcc' * (cave - vsize)
    d[raw + cave:raw + cave + len(s)] = s
    patch = b'\xe9' + struct.pack('<i', (raw + cave) - (site + 5))
    d[site:site_end] = patch + b'\x90' * (site_end - site - len(patch))
    struct.pack_into('<I', d, text + 8, cave + len(s))
    open(dst, 'wb').write(d)
    print('%s: InternetSetFilePointer keeps buffered data (site %#x, stub %#x, read_pos %#x, content_pos %#x)'
          % (dst, rva(site), va + cave, rp, cp))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-wininet-seek: ' + err)
