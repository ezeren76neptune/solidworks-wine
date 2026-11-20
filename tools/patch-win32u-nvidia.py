#!/usr/bin/env python3
"""Correct front-buffer handling for SOLIDWORKS on an NVIDIA GPU (PRIME render offload).

usage: patch-win32u-nvidia.py IN.so OUT.so      (IN: win32u.so, normally already patch-win32u.py'd)

SOLIDWORKS draws its viewports into the front buffer and presents with glFlush;
with PRIME offload, NVIDIA only shows a frame on a buffer swap. It also uses the
back buffer as scratch: it clears it, draws overlays there (the view triad,
labels) and copies the changed strips to the front buffer with glCopyPixels. So
front and back must stay separate buffers: mapping front onto back (Wine's
EGL-style emulation) showed that cleared scratch buffer, and the part vanished
when the mouse moved over the triad or a dialog opened over the view.

Wine's framebuffer surfaces (its EmulateModeset path) do this properly: the
application draws into an FBO with separate front and back attachments, and
each present blits the front one to the real window and swaps. On NVIDIA that
path fails with BadMatch in glXMakeContextCurrent, because Wine's internal
blitting context always uses pixel format 1 while the window's real drawable
uses the application's format (25: depth 24, stencil 8). This patch changes
get_window_unused_drawable() so that, for every non-raw window drawable:
  A. the client surface is offscreen and created with pixel format 1;
  B. the real (target) drawable is created with pixel format 1, matching the
     internal context, while the FBO keeps the application's format;
  C. it is always wrapped in a framebuffer surface, as with EmulateModeset;
and in get_target() (inlined twice, for the draw and read drawables):
  D. an application context is always bound to a null surface of its own
     format instead of the window drawable (it draws into the FBO anyway), so
     only the internal context, with format 1, ever touches the window.
Stubs go in the unused tail of the executable segment's last page, which is
extended to cover them. Exits non-zero, writing nothing, if the build does not
look as expected.
"""
import re, struct, sys

# A: lea emulate_modeset,%rax; mov %r14d,%ecx; xor %edx,%edx; [mov %ebx,%esi; mov %r12,%rdi; or (%rax),%ecx; setne %dl]; call get_unused_client_surface
SITE_A = re.compile(rb'\x48\x8d\x05(....)\x44\x89\xf1\x31\xd2(\x89\xde\x4c\x89\xe7\x0b\x08\x0f\x95\xc2)\xe8', re.S)
# B: mov driver_funcs,%rax; [lea -0x28(%rbp),%rdx; mov %ebx,%esi; mov %r15,%rdi; call *0x28(%rax)]   (p_surface_create)
SITE_B = re.compile(rb'\x48\x8b\x05....(\x48\x8d\x55\xd8\x89\xde\x4c\x89\xff\xff\x50\x28)', re.S)
# C: test %r14d,%r14d; jne ..; lea emulate_modeset,%rax; mov (%rax),%eax; test %eax,%eax; [je skip]; lea framebuffer_surface_funcs,%rax; cmp %rax,(%rcx)
# D: mov 0xb0(%reg),%reg2; test %reg2,%reg2; [jne use_target]; ... call get_null_surface
SITE_D = re.compile(rb'[\x48\x49]\x8b(?:\x92|\xb6|\x95|\xb4\x24)\xb0\x00\x00\x00\x48\x85(?:\xd2|\xf6)(\x0f\x85....)', re.S)
SITE_C = re.compile(rb'\x45\x85\xf6\x0f\x85....\x48\x8d\x05(....)\x8b\x00\x85\xc0(\x0f\x84....)\x48\x8d\x05....\x48\x39\x01', re.S)


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    if d[:4] != b'\x7fELF' or d[4] != 2:
        return 'not a 64-bit ELF file'
    a, b, c = list(SITE_A.finditer(d)), list(SITE_B.finditer(d)), list(SITE_C.finditer(d))
    if (len(a), len(b), len(c)) != (1, 1, 1):
        return 'expected one of each get_window_unused_drawable site, found %d/%d/%d' % (len(a), len(b), len(c))
    a, b, c = a[0], b[0], c[0]
    # both sites must read the same global (emulate_modeset), and A, B, C must be close together
    ga = a.start() + 7 + struct.unpack('<i', a.group(1))[0]
    gc = c.start() + 9 + 7 + struct.unpack('<i', c.group(1))[0]
    if ga != gc or not (a.start() < b.start() < c.start() < a.start() + 0x200):
        return 'sites do not belong to one get_window_unused_drawable'
    # D: exactly four target checks, each followed shortly by a call to the same function
    ds, calls = [], set()
    for m in SITE_D.finditer(d):
        k = d.find(b'\xe8', m.end(), m.end() + 40)
        if k < 0:
            continue
        calls.add(k + 5 + struct.unpack_from('<i', d, k + 1)[0])
        ds.append(m)
    if len(ds) != 4 or len(calls) != 1:
        return 'expected four get_target checks calling get_null_surface, found %d (%d targets)' % (len(ds), len(calls))

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

    def jmp(frm, to):
        return b'\xe9' + struct.pack('<i', to - (frm + 5))

    # stub A: offscreen client surface, format 1 unless raw
    sa = a.start(2)
    stub_a = (b'\x4c\x89\xe7'              # mov %r12,%rdi
              b'\xba\x01\x00\x00\x00'      # mov $1,%edx        (offscreen)
              b'\x89\xde'                  # mov %ebx,%esi      (format)
              b'\x45\x85\xf6'              # test %r14d,%r14d   (raw?)
              b'\x75\x05'                  # jne 1f
              b'\xbe\x01\x00\x00\x00')     # mov $1,%esi        (format 1)
    stub_a += jmp(cave + len(stub_a), sa + len(a.group(2)))
    # stub B: target drawable with format 1 unless raw
    sb = b.start(1)
    cave_b = (cave + len(stub_a) + 15) & ~15
    stub_b = (b'\x48\x8d\x55\xd8'          # lea -0x28(%rbp),%rdx
              b'\x89\xde'                  # mov %ebx,%esi
              b'\x45\x85\xf6'              # test %r14d,%r14d
              b'\x75\x05'                  # jne 1f
              b'\xbe\x01\x00\x00\x00'      # mov $1,%esi
              b'\x4c\x89\xff'              # 1: mov %r15,%rdi
              b'\xff\x50\x28')             # call *0x28(%rax)
    stub_b += jmp(cave_b + len(stub_b), sb + len(b.group(1)))
    end = cave_b + len(stub_b)
    nxt = min([l[2] for l in loads if l[2] > off] or [len(d)])
    if end > ((off + fsz + 0xfff) & ~0xfff) or end > nxt or any(d[off + fsz:end]):
        return 'no room after the executable segment'

    d[cave:cave + len(stub_a)] = stub_a
    d[cave_b:end] = stub_b
    d[sa:sa + len(a.group(2))] = jmp(sa, cave) + b'\x90' * (len(a.group(2)) - 5)
    d[sb:sb + len(b.group(1))] = jmp(sb, cave_b) + b'\x90' * (len(b.group(1)) - 5)
    sc = c.start(2)
    d[sc:sc + 6] = b'\x66\x0f\x1f\x44\x00\x00'                              # always wrap (C)
    for m in ds:                                                            # null surface (D)
        d[m.start(1):m.start(1) + 6] = b'\x66\x0f\x1f\x44\x00\x00'
    struct.pack_into('<QQ', d, ph + 32, end - off, end - off)
    open(dst, 'wb').write(d)
    print('%s: NVIDIA framebuffer surfaces (sites %#x %#x %#x, get_target %s, stubs %#x %#x)' % (dst, sa, sb, sc, ' '.join('%#x' % m.start(1) for m in ds), cave, cave_b))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-win32u-nvidia: ' + err)
