#!/usr/bin/env python3
"""Keep the keyboard focus where SOLIDWORKS puts it (two fixes in winex11.so).

usage: patch-winex11-focus.py IN.so OUT.so

1. Don't let the window manager hand the focus to caption-less popups.

When SOLIDWORKS shows a small popup while you type (a tooltip, the "Filter
Quick Hits" box) Wine maps it as a managed X window, and the window manager
(KWin here) offers it the focus with WM_TAKE_FOCUS a moment later. Wine accepts
that offer even when SOLIDWORKS has already moved activation back to its main
window, so the PropertyManager number box you were typing into loses the focus
after one character: the value gets committed and reformatted, and the next
keys go to the graphics area. On Windows such popups never take the focus
unless the application activates them itself.

In handle_wm_protocols(), WM_TAKE_FOCUS for a window that is not the
foreground window is only honoured if window_should_take_focus() agrees. This
routes that call through a stub that first refuses the offer when there is a
foreground window and the offered window has no caption (WS_CAPTION), then
falls back to the original check. Windows the application activates itself
are the foreground window and are not affected; clicks still activate popups
through Win32's own mouse activation.

2. Tell the window manager when activation moves back. Typing in a
PropertyManager number box makes SOLIDWORKS show a suggestion popup ("Filter
Quick Hits") with activation and then immediately re-activate its main window
and refocus the box. Wine asked the window manager to activate the popup when
mapping it, but set_net_active_window() skips the request for the main window
because Wine's pending _NET_ACTIVE_WINDOW still names it. The window manager
then activates the popup and Wine follows, so the box loses the focus. Here the
request is skipped only when the window is not actually changing (hwnd ==
previous); otherwise it is sent, and Wine ignores the stale popup activation
until the window manager confirms the new one.

The stub goes in the unused tail of the executable segment's last page, which
is extended to cover it. Exits non-zero, writing nothing, if the build does
not look as expected.
"""
import re, struct, sys

# WM_TAKE_FOCUS: mov %r12,%rdi; cmp %rbx,%r12 (hwnd == foreground?); je take; mov %r15,%rsi;
#                mov %r10,disp(%rbp); call window_should_take_focus; mov disp(%rbp),%r10; test %eax,%eax; jne take
SITE = re.compile(rb'\x4c\x89\xe7\x49\x39\xdc\x74.\x4c\x89\xfe\x4c\x89\x95....(\xe8....)\x4c\x8b\x95....\x85\xc0\x75.', re.S)
WARN = b'Ignoring window %p/%lx WM_TAKE_FOCUS'
# NtUserGetWindowLongW( hwnd, GWL_STYLE ) == NtUserCallHwndParam( hwnd, -16, NtUserCallHwndParam_GetWindowLongW )
STYLE_CALL = re.compile(rb'\xba(.)\x00\x00\x00.{0,24}?\x48\xc7\xc6\xf0\xff\xff\xff.{0,12}?\xe8(....)', re.S)
GET_WINDOW_LONG_W = 10     # NtUserCallHwndParam_GetWindowLongW in Wine 11's ntuser.h
# set_net_active_window(hwnd=rbx, previous=r15): cmp %rax(window),pending_net_active_window(%r12); je return;
#                                                test %rbx,%rbx; je ...   (window_set_pending_activate)
ACTIVE = re.compile(rb'\x49\x39\x84\x24....(\x0f\x84(....))\x48\x85\xdb\x74', re.S)
EPILOGUE = bytes.fromhex('488d65d8' '5b' '415c' '415d' '415e' '415f' '5d' 'c3')
REQ = b'requesting _NET_ACTIVE_WINDOW %p/%lx serial'


def main(src, dst):
    d = bytearray(open(src, 'rb').read())
    if d[:4] != b'\x7fELF' or d[4] != 2:
        return 'not a 64-bit ELF file'
    sites = list(SITE.finditer(d))
    warn = d.find(WARN)
    # keep only sites followed by the "Ignoring window ... WM_TAKE_FOCUS" WARN (lea of that string)
    def refs_warn(m):
        for k in range(m.end(), m.end() + 0x60):
            if d[k:k + 3] in (b'\x48\x8d\x0d', b'\x48\x8d\x15', b'\x48\x8d\x35', b'\x48\x8d\x3d') and \
                    k + 7 + struct.unpack_from('<i', d, k + 3)[0] == warn:
                return True
        return False
    sites = [m for m in sites if warn >= 0 and refs_warn(m)]
    if len(sites) != 1:
        return 'expected one WM_TAKE_FOCUS window_should_take_focus call, found %d' % len(sites)
    call = sites[0].start(1)
    should_take = call + 5 + struct.unpack_from('<i', d, call + 1)[0]
    # NtUserCallHwndParam@plt, from an existing GetWindowLongW(hwnd, GWL_STYLE) call
    plts = {m.start(2) + 4 + struct.unpack('<i', m.group(2))[0]
            for m in STYLE_CALL.finditer(d) if m.group(1)[0] == GET_WINDOW_LONG_W}
    if len(plts) != 1:
        return 'NtUserCallHwndParam (GetWindowLongW) call not found (%d candidates)' % len(plts)
    plt = plts.pop()

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

    s = bytearray()
    s += b'\x48\x85\xff'                                    # test %rdi,%rdi        no foreground window?
    j0 = len(s); s += b'\x74\x00'                           # je orig
    s += b'\x57\x56\x48\x83\xec\x08'                        # push %rdi; push %rsi; sub $8,%rsp
    s += b'\x48\x89\xdf'                                    # mov %rbx,%rdi         (offered window)
    s += b'\x48\xc7\xc6\xf0\xff\xff\xff'                    # mov $GWL_STYLE,%rsi
    s += b'\xba' + struct.pack('<I', GET_WINDOW_LONG_W)     # mov $GetWindowLongW,%edx
    s += b'\xe8' + struct.pack('<i', plt - (cave + len(s) + 5))
    s += b'\x48\x83\xc4\x08\x5e\x5f'                        # add $8,%rsp; pop %rsi; pop %rdi
    s += b'\x25\x00\x00\xc0\x00'                            # and $WS_CAPTION,%eax
    s += b'\x3d\x00\x00\xc0\x00'                            # cmp $WS_CAPTION,%eax
    j1 = len(s); s += b'\x74\x00'                           # je orig               captioned: usual check
    s += b'\x31\xc0\xc3'                                    # xor %eax,%eax; ret    caption-less popup: refuse
    orig = len(s)
    s += b'\xe9' + struct.pack('<i', should_take - (cave + len(s) + 5))
    for j in (j0, j1):
        s[j + 1] = orig - (j + 2)
    # 2: set_net_active_window
    req = d.find(REQ)
    act = [m for m in ACTIVE.finditer(d) if req >= 0 and any(
        d[k:k + 3] in (b'\x48\x8d\x0d', b'\x48\x8d\x15', b'\x48\x8d\x35', b'\x48\x8d\x3d') and
        k + 7 + struct.unpack_from('<i', d, k + 3)[0] == req for k in range(m.end(), m.end() + 0x200))]
    if len(act) != 1:
        return 'expected one set_net_active_window pending check, found %d' % len(act)
    je = act[0].start(1)
    ret = je + 6 + struct.unpack('<i', act[0].group(2))[0]
    start = d.rfind(b'\x55\x48\x89\xe5', je - 0xc0, je)
    if d[ret:ret + len(EPILOGUE)] != EPILOGUE or start < 0 or \
            b'\x49\x89\xf7' not in d[start:start + 0x12] or b'\x48\x89\xfb' not in d[start:start + 0x18]:
        return 'set_net_active_window does not look as expected (hwnd in rbx, previous in r15)'
    cave2 = (cave + len(s) + 15) & ~15
    s2 = (b'\x4c\x39\xfb'                                          # cmp %r15,%rbx      same window?
          + b'\x0f\x84' + struct.pack('<i', ret - (cave2 + 9))        # je return
          + b'\xe9' + struct.pack('<i', (je + 6) - (cave2 + 14)))      # jmp on: send the request
    end = cave2 + len(s2)
    nxt = min([l[2] for l in loads if l[2] > off] or [len(d)])
    if end > ((off + fsz + 0xfff) & ~0xfff) or end > nxt or any(d[off + fsz:end]):
        return 'no room after the executable segment'

    d[cave:cave + len(s)] = s
    d[cave2:end] = s2
    d[call + 1:call + 5] = struct.pack('<i', cave - (call + 5))
    d[je + 2:je + 6] = struct.pack('<i', cave2 - (je + 6))
    struct.pack_into('<QQ', d, ph + 32, end - off, end - off)               # p_filesz, p_memsz
    open(dst, 'wb').write(d)
    print('%s: WM_TAKE_FOCUS refused for caption-less popups (site %#x, stub %#x); activation always sent (site %#x, stub %#x)' % (dst, call, cave, je, cave2))


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    err = main(*sys.argv[1:])
    if err:
        sys.exit('patch-winex11-focus: ' + err)
