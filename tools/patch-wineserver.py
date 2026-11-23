#!/usr/bin/env python3
"""Keep the parent's repaints off child windows drawn by another process (wineserver).

usage: patch-wineserver.py IN OUT      (IN: the wineserver executable)

The 3DEXPERIENCE sign-in page is a WebView2 window: msedgewebview2.exe draws it
into a child window of the launcher's window. A process cannot use the window
surface of a top-level window it does not own, so Wine draws such a child
straight onto the X11 window, past the launcher's copy of the window contents.
The next time the launcher's surface is flushed (it repaints, the window is
exposed or moved), its copy, white where the page is, is put back over the
page. The page showed for a moment, then went white except where the mouse had
just made it redraw, and the text cursor was never visible.

wineserver already keeps a top-level window's surface off child windows that
draw directly (OpenGL/Vulkan children: PAINT_HAS_PIXEL_FORMAT, see
get_surface_region()). This patch gives that flag to every child window whose
owning process differs from its parent's, in the set_window_pos request
handler where the client's paint flags are stored, so the existing code clips
it out of the parent's surface and marks the parents (PAINT_PIXEL_FORMAT_CHILD)
as it does for OpenGL children. Top-level windows (whose parent is the desktop)
are not affected.

The store of the new flags is redirected to a stub in the unused tail of the
executable segment's last page, which is extended to cover it. Exits non-zero,
writing nothing, if the build does not look as expected.
"""
import re, struct, sys

# set_window_pos handler: mov PF(%r12),%edi; movzwl 0xe(%r15),%r15d; mov PARENT(%r12),%rax;
# and $~7,%edi; and $7,%r15d; or %r15d,%edi; mov %rax,%r13; [mov %edi,SLOT(%rbp)]; test %rax,%rax
SITE = re.compile(rb'\x41\x8b\xbc\x24(....)\x45\x0f\xb7\x7f\x0e\x49\x8b\x44\x24(.)\x83\xe7\xf8\x41\x83\xe7\x07'
                  rb'\x44\x09\xff\x49\x89\xc5(\x89\xbd....)\x48\x85\xc0', re.S)
# get_top_window_owner(): mov TOP(%rdi),%rax; test; je; mov THREAD(%rax),%rax; test; je; mov PROCESS(%rax),%rax; ret
OWNER = re.compile(rb'\x48\x8b\x47.\x48\x85\xc0\x74\x13\x48\x8b\x80(....)\x48\x85\xc0\x74\x07\x48\x8b\x80(....)\xc3', re.S)


def exec_segment(d):
    phoff = struct.unpack_from('<Q', d, 0x20)[0]
    phsize, phnum = struct.unpack_from('<HH', d, 0x36)
    loads = []
    for i in range(phnum):
        ph = phoff + i * phsize
        typ, flags, off, va, pa, fsz, msz, align = struct.unpack_from('<IIQQQQQQ', d, ph)
        if typ == 1:
            loads.append((ph, flags, off, va, fsz, msz))
    ex = [l for l in loads if l[1] & 1]
    if len(ex) != 1 or ex[0][4] != ex[0][5]:
        return None
    ph, _, off, va, fsz, _ = ex[0]
    limit = min([(off + fsz + 0xfff) & ~0xfff] + [l[2] for l in loads if l[2] > off])
    return ph, off, va, fsz, limit


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    if d[:4] != b'\x7fELF' or d[4] != 2:
        return 'not a 64-bit ELF file'
    sites, owners = list(SITE.finditer(d)), list(OWNER.finditer(d))
    if len(sites) != 1:
        return 'set_window_pos paint-flags site not found (%d matches)' % len(sites)
    if len({(o.group(1), o.group(2)) for o in owners}) != 1:
        return 'get_top_window_owner not found (%d matches)' % len(owners)
    m = sites[0]
    parent_off = m.group(2)[0]
    thread_off = struct.unpack('<I', owners[0].group(1))[0]
    process_off = struct.unpack('<I', owners[0].group(2))[0]
    store = m.group(3)                                   # mov %edi,SLOT(%rbp)
    seg = exec_segment(d)
    if not seg:
        return 'unexpected program headers'
    ph, off, va, fsz, limit = seg
    cave = (off + fsz + 15) & ~15
    if any(d[off + fsz:limit]):
        return 'no free space after the executable segment'

    st = bytearray()
    def je(label_pos_holder):
        st.extend(b'\x74\x00')
        label_pos_holder.append(len(st) - 1)
    to_store, to_done = [], []
    st += b'\x48\x85\xc0'                                      # test %rax,%rax        parent?
    je(to_store)
    st += b'\x48\x83\x78' + bytes([parent_off]) + b'\x00'      # cmpq $0,PARENT(%rax)  parent is the desktop?
    je(to_store)
    st += b'\x51\x52'                                          # push %rcx; push %rdx
    st += b'\x49\x8b\x8c\x24' + struct.pack('<I', thread_off)  # mov THREAD(%r12),%rcx
    st += b'\x48\x85\xc9'                                      # test %rcx,%rcx
    je(to_done)
    st += b'\x48\x8b\x90' + struct.pack('<I', thread_off)      # mov THREAD(%rax),%rdx
    st += b'\x48\x85\xd2'                                      # test %rdx,%rdx
    je(to_done)
    st += b'\x48\x8b\x89' + struct.pack('<I', process_off)     # mov PROCESS(%rcx),%rcx
    st += b'\x48\x3b\x8a' + struct.pack('<I', process_off)     # cmp PROCESS(%rdx),%rcx
    je(to_done)
    st += b'\x83\xcf\x02'                                      # or $PAINT_HAS_PIXEL_FORMAT,%edi
    done = len(st)
    st += b'\x5a\x59'                                          # pop %rdx; pop %rcx
    stored = len(st)
    st += store + b'\xc3'                                      # mov %edi,SLOT(%rbp); ret
    for pos in to_done:
        st[pos] = done - (pos + 1)
    for pos in to_store:
        st[pos] = stored - (pos + 1)

    end = cave + len(st)
    if end > limit:
        return 'no room for the stub'
    call = m.start(3)                                          # file offset of the store
    d[cave:end] = st
    d[call:call + 6] = b'\xe8' + struct.pack('<i', (cave - off + va) - (call - off + va + 5)) + b'\x90'
    struct.pack_into('<QQ', d, ph + 32, end - off, end - off)  # p_filesz, p_memsz
    open(dst, 'wb').write(d)
    print('%s: cross-process child windows clipped out of parent surfaces (site %#x, stub %#x)'
          % (dst, call - off + va, cave - off + va))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-wineserver: ' + err)
