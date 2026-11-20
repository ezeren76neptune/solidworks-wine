#!/usr/bin/env python3
"""OpenGL rendering into bitmaps (memory DCs) on NVIDIA's GLX driver.

usage: patch-win32u-memdc.py IN.so OUT.so      (IN: win32u.so, normally already patch-win32u.py'd)

When it saves a document, SOLIDWORKS renders the file's preview image into a
memory DC (a bitmap) with a bitmap pixel format: single-buffered RGB8 with a
24-bit depth buffer. Wine backs the bitmap with a pbuffer of that format and,
in flush_memory_dc(), copies between the two with its own internal context.
That context always has pixel format 1 (double-buffered RGBA8, no depth).
Mesa accepts the pairing; NVIDIA's GLX refuses it (BadMatch in
X_GLXMakeContextCurrent), and Xlib's default error handler then ends the
process: SOLIDWORKS vanished in the middle of a save and left a 0-byte file.

This patch replaces flush_memory_dc()'s switch to the internal context:
  * copying the rendered image back into the bitmap (when the application
    flushes) uses the application's own context, which has the pbuffer's
    format, if it is the active context and reads from that pbuffer;
    otherwise that copy is skipped rather than risk the BadMatch;
  * copying the bitmap's old contents into a new pbuffer is skipped
    (applications clear before they draw).
The stub goes in the unused tail of the executable segment's last page, which
is extended to cover it. Exits non-zero, writing nothing, if the build does not
look as expected.
"""
import re, struct, sys

# flush_memory_dc: drawable = dc->opengl_drawable; ...; make_thread_context_current(context->root_context, drawable);
#   if (drawable->funcs->flush) opengl_drawable_flush(drawable, 0, GL_FLUSH_ACTIVATE); if (write) ...
SITE = re.compile(rb'\x4c\x8b\x63.\x49\x8b\x7e.\xc1\xe8\x02\x41\xf7\xf5\x4c\x89\xe6\x41\x89\xc7(\xe8....)'
                  rb'\x49\x8b\x04\x24\x48\x83\x78\x10\x00\x74.\xba\x20\x00\x00\x00\x31\xf6\x4c\x89\xe7\xe8....'
                  rb'\x8b\xb5(....)\x85\xf6\x0f\x84', re.S)
# the "no image" exit just before it: test %eax,%eax; je <site block>; mov hBitmap(%rbx),%rdi; call GDI_ReleaseObj
RELEASE = re.compile(rb'\x85\xc0\x74(.)\x48\x8b\xbb....\xe8', re.S)
# make_client_context_current: call NtCurrentTeb; mov 0x1220(%rax),%r13   (glReserved2: the active context)
TEB = re.compile(rb'\xe8(....)\x4c\x8b\xa8\x20\x12\x00\x00', re.S)
# ... get_target(context->read) in %rdx, get_target(context->draw) in %rsi
CTX = re.compile(rb'\x49\x8b\x54\x24(.)\x48\x8d\x0d....\x4c\x8b\x40.\x48\x39\x0a\x0f\x84....\x49\x8b\x74\x24(.)\x48\x39\x0e', re.S)


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    if d[:4] != b'\x7fELF' or d[4] != 2:
        return 'not a 64-bit ELF file'
    sites, ctx = list(SITE.finditer(d)), list(CTX.finditer(d))
    if len(sites) != 1 or len(ctx) != 1:
        return 'expected one flush_memory_dc site and one make_client_context_current, found %d/%d' % (len(sites), len(ctx))
    m = sites[0]
    call = m.start(1)
    write_flag = struct.unpack('<i', m.group(2))[0]
    read_off = ctx[0].group(1)[0]
    # the exit that releases the bitmap and returns TRUE, right before the site
    rel = [r for r in RELEASE.finditer(d, max(0, m.start() - 0x80), m.start())
           if m.start() - 0x20 <= r.start() + 4 + struct.unpack('<b', r.group(1))[0] <= m.start()]
    if len(rel) != 1:
        return 'bitmap release exit not found before the flush_memory_dc site'
    release = rel[0].start() + 4
    tebs = {t.start() + 5 + struct.unpack('<i', t.group(1))[0] for t in TEB.finditer(d)}
    if len(tebs) != 1:
        return 'NtCurrentTeb call not found'
    teb = tebs.pop()

    phoff = struct.unpack_from('<Q', d, 0x20)[0]
    phsize, phnum = struct.unpack_from('<HH', d, 0x36)
    loads = []
    for i in range(phnum):
        p = phoff + i * phsize
        typ, flags, off, va, pa, fsz, msz, align = struct.unpack_from('<IIQQQQQQ', d, p)
        if typ == 1:
            loads.append((p, flags, off, va, fsz, msz))
    ex = [l for l in loads if l[1] & 1]
    if len(ex) != 1 or ex[0][2] != ex[0][3] or ex[0][4] != ex[0][5]:
        return 'unexpected executable segment layout'
    ph, _, off, va, fsz, _ = ex[0]
    cave = (off + fsz + 15) & ~15

    def rel32(frm, to):
        return struct.pack('<i', to - frm)
    s = bytearray()
    s += b'\x8b\x85' + struct.pack('<i', write_flag)          # mov write(%rbp),%eax
    s += b'\x85\xc0'                                          # test %eax,%eax
    j1 = len(s); s += b'\x75\x00'                             # jne skip       (no upload into a new pbuffer)
    s += b'\xe8' + rel32(cave + len(s) + 5, teb)              # call NtCurrentTeb
    s += b'\x4c\x39\xb0\x20\x12\x00\x00'                      # cmp %r14,0x1220(%rax)   active context == context?
    j2 = len(s); s += b'\x75\x00'                             # jne skip
    s += b'\x4d\x39\x66' + bytes([read_off])                  # cmp %r12,read(%r14)     reading from this pbuffer?
    j3 = len(s); s += b'\x75\x00'                             # jne skip
    s += b'\xe9' + rel32(cave + len(s) + 5, call + 5)         # jmp back: read the image with the current context
    skip = len(s)
    s += b'\xe9' + rel32(cave + len(s) + 5, release)          # skip: release the bitmap, return TRUE
    for j in (j1, j2, j3):
        s[j + 1] = skip - (j + 2)
    end = cave + len(s)
    nxt = min([l[2] for l in loads if l[2] > off] or [len(d)])
    if end > ((off + fsz + 0xfff) & ~0xfff) or end > nxt or any(d[off + fsz:end]):
        return 'no room after the executable segment'

    d[cave:end] = s
    d[call:call + 5] = b'\xe9' + rel32(call + 5, cave)
    struct.pack_into('<QQ', d, ph + 32, end - off, end - off)               # p_filesz, p_memsz
    open(dst, 'wb').write(d)
    print('%s: memory-DC copies without the internal context (site %#x, stub %#x)' % (dst, call, cave))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-win32u-memdc: ' + err)
