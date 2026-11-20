#!/usr/bin/env python3
"""Front-buffer rendering emulation for Wine's GLX drawables (for NVIDIA PRIME offload).

usage: patch-winex11.py IN.so OUT.so

SOLIDWORKS draws its viewports straight into the front buffer and presents with
glFlush/glFinish; it never calls SwapBuffers. With NVIDIA PRIME render offload
(the NVIDIA GPU renders, the integrated GPU drives the display) a frame only
reaches the X window on a buffer swap, so the viewport stops updating.

Wine's EGL drawables already handle such applications: they map GL_FRONT_LEFT,
GL_FRONT and GL_FRONT_AND_BACK to the back buffer, and Wine then turns each
front-buffer flush into a swap and copies the front buffer back ("front buffer
rendering emulation"). This gives GLX drawables the same mapping: right after
x11drv_surface_create()'s opengl_drawable_create() succeeds, it stores the same
three buffer_map entries the EGL path stores. Offsets and values are read from
that EGL code in the same binary. The stub goes in the unused tail of the
executable segment's last page, and the segment is extended to cover it.
Exits non-zero, writing nothing, if the build does not look as expected.
"""
import re, struct, sys

# EGL surface create: movl $GL_BACK_LEFT,o1(%rax); [mov %rax,%rbx]; movl $GL_BACK,o2(%rax); movl $GL_BACK,o3(%rax)
# (each store with an 8- or 32-bit displacement, depending on where buffer_map sits in this build)
STORE = rb'\xc7(?:\x40(.)|\x80(....))'
MOV = rb'(?:\x48\x89\xc3)?'
EGL = re.compile(STORE + rb'\x02\x04\x00\x00' + MOV + STORE + rb'\x05\x04\x00\x00' + MOV + STORE + rb'\x05\x04\x00\x00', re.S)
# GLX surface create: call opengl_drawable_create; mov %rax,%r15; test %rax,%rax; je fail;
#                     shl $5,%rbx; mov 0x90(%r12),%rdx     <- these 12 bytes move to the stub
GLX = re.compile(rb'\xe8(....)\x49\x89\xc7\x48\x85\xc0\x0f\x84(....)(\x48\xc1\xe3\x05\x49\x8b\x94\x24\x90\x00\x00\x00)', re.S)
EGL_CALL = re.compile(rb'\xe8(....)\x48\x85\xc0\x0f\x84(....)\xc7(?:\x40.|\x80....)\x02\x04\x00\x00', re.S)


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    if d[:4] != b'\x7fELF' or d[4] != 2:
        return 'not a 64-bit ELF file'
    egl, glx = list(EGL.finditer(d)), list(GLX.finditer(d))
    if len(egl) != 1 or len(glx) != 1:
        return 'expected one EGL and one GLX surface-create site, found %d/%d' % (len(egl), len(glx))
    g = egl[0].groups()
    def disp(d8, d32):
        return struct.unpack('<b', d8)[0] if d8 is not None else struct.unpack('<i', d32)[0]
    o1, o2, o3 = disp(g[0], g[1]), disp(g[2], g[3]), disp(g[4], g[5])
    # both sites must call the same function (opengl_drawable_create@plt)
    ec = list(EGL_CALL.finditer(d))
    if len(ec) != 1:
        return 'EGL opengl_drawable_create call not found'
    target = lambda m: m.start() + 5 + struct.unpack('<i', m.group(1))[0]
    if target(ec[0]) != target(glx[0]):
        return 'GLX and EGL sites call different functions'
    site = glx[0].start(3)
    moved = bytes(glx[0].group(3))

    # executable LOAD segment; stub in the tail of its last page
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
    def store(off, value):                                                 # movl $value,off(%r15)
        if -128 <= off < 128:
            return bytes([0x41, 0xc7, 0x47]) + struct.pack('<bI', off, value)
        return bytes([0x41, 0xc7, 0x87]) + struct.pack('<iI', off, value)
    stub = store(o1, 0x402) + store(o2, 0x405) + store(o3, 0x405)        # GL_BACK_LEFT, GL_BACK, GL_BACK
    stub += moved
    stub += b'\xe9' + struct.pack('<i', (site + len(moved)) - (cave + len(stub) + 5))
    end = cave + len(stub)
    nxt = min([l[2] for l in loads if l[2] > off] or [len(d)])
    if end > ((off + fsz + 0xfff) & ~0xfff) or end > nxt or any(d[off + fsz:end]):
        return 'no room after the executable segment'
    d[cave:end] = stub
    d[site:site + len(moved)] = b'\xe9' + struct.pack('<i', cave - (site + 5)) + b'\x90' * (len(moved) - 5)
    struct.pack_into('<QQ', d, ph + 32, end - off, end - off)               # p_filesz, p_memsz
    open(dst, 'wb').write(d)
    print('%s: GLX front-buffer emulation added (site %#x, stub %#x, buffer_map at %#x)' % (dst, site, cave, o1))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-winex11: ' + err)
