#!/usr/bin/env python3
"""Skip the DS installer stub's "Internet Explorer 10 or later" probe.

The stub does GetProcAddress(wininet.dll, "HttpWebSocketReceive") and refuses to
run when the export is missing; Wine's wininet has no such export. This flips the
one conditional jump after that probe (jne -> jmp) in a COPY of the stub.
Usage: patch-ie10-check.py <stub.exe> [...]
"""
import struct, sys

def patch(path):
    d = bytearray(open(path, 'rb').read())
    pe = struct.unpack_from('<I', d, 0x3c)[0]
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    optsz = struct.unpack_from('<H', d, pe + 20)[0]
    secs = []
    o = pe + 24 + optsz
    for _ in range(nsec):
        vs, va, rs, ro = struct.unpack_from('<IIII', d, o + 8)
        secs.append((va, ro, rs)); o += 40
    def rva(off):
        for va, ro, rs in secs:
            if ro <= off < ro + rs:
                return va + off - ro
    s = d.find(b'HttpWebSocketReceive\0')
    if s < 0:
        return 'no probe string'
    target = rva(s)
    hits = []
    i = 0
    while True:
        i = d.find(b'\x48\x8d\x15', i)          # lea rdx,[rip+rel32]
        if i < 0:
            break
        rel = struct.unpack_from('<i', d, i + 3)[0]
        r = rva(i)
        if r is not None and r + 7 + rel == target:
            hits.append(i)
        i += 1
    if len(hits) != 1:
        return 'expected 1 xref, found %d' % len(hits)
    # lea rdx,str ; mov rcx,rax ; call [GetProcAddress] ; test rax,rax ; jne ok
    j = hits[0] + 7 + 3 + 6 + 3
    if d[j] == 0xEB:
        return 'already patched'
    if d[hits[0] + 7:hits[0] + 10] != b'\x48\x8b\xc8' or d[j - 3:j] != b'\x48\x85\xc0' or d[j] != 0x75:
        return 'unexpected code at probe, not patched'
    d[j] = 0xEB
    open(path, 'wb').write(d)
    return 'patched at file offset %#x' % j

for p in sys.argv[1:]:
    print(p.rsplit('/', 1)[-1], '->', patch(p))
