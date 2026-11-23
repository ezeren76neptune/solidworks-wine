#!/usr/bin/env python3
"""Two mouse fixes and a window-position fix in Wine's win32u.so for SOLIDWORKS.

usage: patch-win32u.py IN.so OUT.so

1. Stop sending WM_CAPTURECHANGED to a window that keeps the capture. Required.

Binary form of Denis Bonnenfant's patch for Wine bug 27403 (0002-win32u-Don-t-
send-WM_CAPTURECHANGED-when-capture-is-set-to-the-same-window): in
set_capture_window(), `if (previous)` becomes `if (previous && previous != hwnd)`.
Without it SOLIDWORKS' PropertyManager buttons (green check, type selectors)
lose BN_CLICKED: the spurious message makes their subclass release capture
between button-down and button-up.

The call to send_message() there is redirected to a stub placed in the padding
after .plt, which returns without sending when previous (rdi) == hwnd (rcx).

2. Hit-test when checking whether the mouse left a tracked window. Wine's
TrackMouseEvent timer finds the window under the cursor with
window_from_point(hwnd, pt, &hittest, FALSE), i.e. without WM_NCHITTEST, so a
window that covers more than it shows and answers HTTRANSPARENT outside its
visible part still counts as under the cursor. SOLIDWORKS' heads-up view
toolbar is such a window: after its View Orientation flyout was opened, the
toolbar never got WM_MOUSELEAVE and its balloon tooltip stayed on screen.
get_mouse_window() now passes TRUE, as Windows hit-tests. It also treats a
mouse capture held by another window as the window under the cursor, as
Windows does (tracking follows the window that receives mouse input): when a
flyout or menu captures the mouse, the tracked window gets WM_MOUSELEAVE and
its pending WM_MOUSEHOVER is dropped. Without that, SOLIDWORKS' graphics area
got a hover while its View Orientation flyout was open, showed a balloon
tooltip, and never hid it. The capture check is a stub in the unused tail of
the executable segment's last page, which is extended to cover it. Skipped
with a warning if the code is not found.

3. Ignore the position and size when a child window is moved with HWND_TOPMOST
or HWND_NOTOPMOST, as Windows does (Wine's own user32 test, win.c
test_SetWindowPos: SetWindowPos(child, HWND_TOPMOST, 1, 2, 3, 4, 0) returns TRUE
and leaves the rect alone; todo_wine there). SOLIDWORKS' PropertyManager group
painting (slduiu.dll) reads each group header button's rect, adds a 4 px margin
and calls SetWindowPos(header, &wndTopMost, ...) on every WM_PAINT and
WM_PRINTCLIENT. On Windows that never moves anything; Wine moved the header,
which uncovered part of the page, which painted again, so the headers slid right
4 px per paint until they were 0 px wide, and the sub-sections of the Extrude
and Dimension PropertyManagers showed for a frame and vanished. In
set_window_pos(), the HWND_TOPMOST/NOTOPMOST branch now adds SWP_NOMOVE |
SWP_NOSIZE when GetAncestor(hwnd, GA_ROOT) != hwnd; the z-order part is
unchanged. Stub in the same segment tail as 2. Skipped with a warning if the
code is not found.

Exits non-zero, writing nothing, if the build does not look as expected for 1.
"""
import re
import struct, sys

# mov rcx,r13; xor edx,edx; mov esi,WM_CAPTURECHANGED; mov rdi,r14; call send_message
SITE = bytes.fromhex('4c89e9' '31d2' 'be15020000' '4c89f7' 'e8')
# get_mouse_window: call NtUserGetCursorPos; mov pos,%rsi; mov %rbx,%rdi; [xor %ecx,%ecx]; mov %r13,%rdx;
#                   call window_from_point; mov %rax,%rbx; test %rax,%rax; je ..; cmp %rax,last_mouse_message_hwnd(%r12)
MOUSE = re.compile(rb'\xe8....\x48\x8b\x75.\x48\x89\xdf(\x31\xc9)\x4c\x89\xea\xe8(....)\x48\x89\xc3\x48\x85\xc0\x74.\x49\x39\x44\x24.', re.S)
SCOPE = b'scope %p (%d,%d) returning %p'
# make_client_context_current: call NtCurrentTeb; mov 0x1220(%rax),%r13
TEB = re.compile(rb'\xe8(....)\x4c\x8b\xa8\x20\x12\x00\x00', re.S)
# set_window_pos, HWND_TOPMOST/NOTOPMOST: mov $GA_ROOT,%esi; call NtUserGetAncestor; mov $GA_PARENT,%esi;
#   mov %rax,%rdi; call NtUserGetAncestor; ... (message-parent check) ...; mov 0x20(%rbx),%eax  winpos->flags;
#   mov (%rbx),%rdi  winpos->hwnd; jmp <continue>
TOPMOST = re.compile(rb'\xbe\x02\x00\x00\x00\xe8(....)\xbe\x01\x00\x00\x00\x48\x89\xc7\xe8(....)'
                     rb'[^\xe9]{0,48}?\x8b\x43\x20\x48\x8b\x3b\xe9(....)', re.S)


def dynsym(d, secs, name):
    sym, strs = secs.get('.dynsym'), secs.get('.dynstr')
    if not sym or not strs:
        return None
    for i in range(sym[3] // 24):
        st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from('<IBBHQQ', d, sym[2] + i * 24)
        if st_value and d[strs[2] + st_name:d.index(b'\0', strs[2] + st_name)] == name:
            return st_value
    return None


def exec_cave(d):
    phoff = struct.unpack_from('<Q', d, 0x20)[0]
    phsize, phnum = struct.unpack_from('<HH', d, 0x36)
    loads = []
    for i in range(phnum):
        ph = phoff + i * phsize
        typ, flags, off, va, pa, fsz, msz, align = struct.unpack_from('<IIQQQQQQ', d, ph)
        if typ == 1:
            loads.append((ph, flags, off, va, fsz, msz))
    ex = [l for l in loads if l[1] & 1]
    if len(ex) != 1 or ex[0][2] != ex[0][3] or ex[0][4] != ex[0][5]:
        return None
    ph, _, off, va, fsz, _ = ex[0]
    limit = min([(off + fsz + 0xfff) & ~0xfff] + [l[2] for l in loads if l[2] > off])
    return ph, off, (off + fsz + 15) & ~15, limit


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
    msg = '%s: WM_CAPTURECHANGED same-window check added (site %#x, stub %#x)' % (dst, site, cave)

    # 2: get_mouse_window() calls window_from_point(..., TRUE); check the callee is window_from_point
    scope = d.find(SCOPE)
    found = []
    for m in MOUSE.finditer(d):
        callee = m.start(2) + 4 + struct.unpack('<i', m.group(2))[0]
        if scope >= 0 and any(d[k:k + 3] == b'\x48\x8d\x0d' and k + 7 + struct.unpack_from('<i', d, k + 3)[0] == scope
                              for k in range(callee, callee + 0x400)):
            found.append(m)
    tebs = {t.start() + 5 + struct.unpack('<i', t.group(1))[0] for t in TEB.finditer(d)}
    gui = dynsym(d, secs, b'NtUserGetGUIThreadInfo')
    seg = exec_cave(d)
    if len(found) == 1 and len(tebs) == 1 and gui and seg:
        m = found[0]
        call = m.start(2) - 1                                                # call window_from_point
        wfp = call + 5 + struct.unpack('<i', m.group(2))[0]
        teb = tebs.pop()
        ph, off, cave, limit = seg
        st = bytearray()
        def rel(to):                                                         # rel32 for an instruction ending here
            return struct.pack('<i', to - (cave + len(st) + 4))
        st += b'\x57'                                                         # push %rdi        tracked window
        st += b'\xe8'; st += rel(wfp)                                         # call window_from_point
        st += b'\x5f\x50\x57'                                                 # pop %rdi; push %rax; push %rdi
        st += b'\x48\x83\xec\x58'                                             # sub $0x58,%rsp   GUITHREADINFO
        st += b'\xc7\x04\x24\x48\x00\x00\x00'                                 # movl $72,(%rsp)  cbSize
        st += b'\xe8'; st += rel(teb)                                         # call NtCurrentTeb
        st += b'\x8b\x78\x48'                                                 # mov 0x48(%rax),%edi  thread id
        st += b'\x48\x89\xe6'                                                 # mov %rsp,%rsi
        st += b'\xe8'; st += rel(gui)                                         # call NtUserGetGUIThreadInfo
        st += b'\x31\xc9\x85\xc0\x74\x05'                                     # xor %ecx,%ecx; test %eax,%eax; je 1f
        st += b'\x48\x8b\x4c\x24\x18'                                         # mov 0x18(%rsp),%rcx  hwndCapture
        st += b'\x48\x83\xc4\x58\x5f\x58'                                     # 1: add $0x58,%rsp; pop %rdi; pop %rax
        st += b'\x48\x85\xc9\x74\x08'                                         # test %rcx,%rcx; je 2f
        st += b'\x48\x39\xf9\x74\x03'                                         # cmp %rdi,%rcx; je 2f
        st += b'\x48\x89\xc8'                                                 # mov %rcx,%rax    capture receives the mouse
        st += b'\xc3'                                                         # 2: ret
        end = cave + len(st)
        if end <= limit and not any(d[off + struct.unpack_from('<Q', d, ph + 32)[0]:end]):
            d[m.start(1):m.end(1)] = b'\xb1\x01'                              # mov $1,%cl (TRUE: hit-test)
            d[cave:end] = st
            struct.pack_into('<i', d, call + 1, cave - (call + 5))
            struct.pack_into('<QQ', d, ph + 32, end - off, end - off)
            msg += '; mouse-leave hit-test and capture check (site %#x, stub %#x)' % (call, cave)
        else:
            print('patch-win32u: no room for the mouse-leave stub, WM_MOUSELEAVE may be missed', file=sys.stderr)
    else:
        print('patch-win32u: get_mouse_window not found, WM_MOUSELEAVE may be missed', file=sys.stderr)

    # 3: child window + HWND_TOPMOST/NOTOPMOST keeps its position and size
    anc = dynsym(d, secs, b'NtUserGetAncestor')
    hits = []
    for m in TOPMOST.finditer(d):
        c1 = m.start(1) + 4 + struct.unpack('<i', m.group(1))[0]
        c2 = m.start(2) + 4 + struct.unpack('<i', m.group(2))[0]
        if anc and c1 == anc and c2 == anc:
            hits.append(m)
    seg = exec_cave(d)
    if len(hits) == 1 and seg:
        m = hits[0]
        jmp = m.start(3) - 1                                                 # jmp <continue>
        back = jmp + 5 + struct.unpack('<i', m.group(3))[0]
        ph, off, cave, limit = seg
        st = bytearray()
        def rel(to):
            return struct.pack('<i', to - (cave + len(st) + 4))
        st += b'\x57\x50'                                                     # push %rdi; push %rax
        st += b'\xbe\x02\x00\x00\x00'                                         # mov $GA_ROOT,%esi
        st += b'\xe8'; st += rel(anc)                                         # call NtUserGetAncestor
        st += b'\x48\x89\xc6\x58\x5f'                                         # mov %rax,%rsi; pop %rax; pop %rdi
        st += b'\x48\x39\xfe\x74\x06'                                         # cmp %rdi,%rsi; je 1f  (top-level)
        st += b'\x83\xc8\x03'                                                 # or $SWP_NOSIZE|SWP_NOMOVE,%eax
        st += b'\x89\x43\x20'                                                 # mov %eax,0x20(%rbx)  winpos->flags
        st += b'\xe9'; st += rel(back)                                        # 1: jmp <continue>
        end = cave + len(st)
        if end <= limit and not any(d[off + struct.unpack_from('<Q', d, ph + 32)[0]:end]):
            d[cave:end] = st
            struct.pack_into('<i', d, jmp + 1, cave - (jmp + 5))
            struct.pack_into('<QQ', d, ph + 32, end - off, end - off)
            msg += '; child HWND_TOPMOST keeps position (site %#x, stub %#x)' % (jmp, cave)
        else:
            print('patch-win32u: no room for the HWND_TOPMOST stub, PropertyManager headers may slide away', file=sys.stderr)
    else:
        print('patch-win32u: set_window_pos HWND_TOPMOST branch not found (%d), PropertyManager headers may slide away'
              % len(hits), file=sys.stderr)
    open(dst, 'wb').write(d)
    print(msg)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-win32u: ' + err)
