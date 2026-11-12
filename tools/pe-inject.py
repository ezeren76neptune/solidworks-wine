#!/usr/bin/env python3
"""Inject a code blob into a PE32+ DLL and export functions from it.

usage: pe-inject.py IN.dll OUT.dll BLOB.bin BLOB.syms [--export Name[=symbol]]... [--ldrp-tls]

BLOB.bin is a flat, position-independent blob; BLOB.syms is `nm` output for it.
The blob goes into a new section (.swx) together with a rebuilt export
directory; nothing else in the image moves. Blob symbols named slot_<Export>
are 32-bit slots (holding 0x5a5a5a5a) that get the distance to that export of
the DLL; symslot_<name> slots get the distance to that COFF symbol of the DLL.

--ldrp-tls (ntdll only) also lays out, in the spare room at the end of .text
and .rdata, what Dassault's in-memory DLL loader scans ntdll for:
  * the string "LdrpHandleTlsData" in .rdata, a `lea rdx,[rip+string]` in .text
    right after an int3, a scope-table-like record in .rdata holding that lea's
    RVA with a function RVA 8 bytes before it, and int3 padding right before
    that function, which jumps to the blob's LdrpHandleTlsData_impl;
  * a function starting with the Windows 10 LdrpReleaseTlsEntry prologue that
    jumps to LdrpReleaseTlsEntry_impl.
Used to give private copies of Wine's DLLs things Wine lacks.
"""
import struct, sys

RELEASE_PROLOGUE = bytes.fromhex('48895c24085748 83ec20 488bfa 488bd9 4885d2 750c'.replace(' ', ''))


class PE:
    def __init__(self, path):
        self.d = d = bytearray(open(path, 'rb').read())
        self.pe = pe = struct.unpack_from('<I', d, 0x3c)[0]
        assert d[pe:pe + 4] == b'PE\0\0'
        self.opt = pe + 24
        assert struct.unpack_from('<H', d, self.opt)[0] == 0x20b, 'PE32+ only'
        self.salign, self.falign = struct.unpack_from('<II', d, self.opt + 32)
        self.ddir = self.opt + 112
        self.sectab = self.opt + struct.unpack_from('<H', d, pe + 20)[0]

    @property
    def nsec(self):
        return struct.unpack_from('<H', self.d, self.pe + 6)[0]

    def sections(self):
        out = []
        for i in range(self.nsec):
            o = self.sectab + 40 * i
            vsize, va, rsize, raw = struct.unpack_from('<IIII', self.d, o + 8)
            out.append(dict(hdr=o, name=bytes(self.d[o:o + 8]).rstrip(b'\0'), va=va, vsize=vsize, raw=raw, rsize=rsize))
        return out

    def section(self, name):
        return next(s for s in self.sections() if s['name'] == name)

    def off(self, rva):
        for s in self.sections():
            if s['va'] <= rva < s['va'] + max(s['vsize'], s['rsize']):
                return s['raw'] + rva - s['va']
        raise ValueError('rva %#x not mapped' % rva)

    def cstr(self, rva):
        o = self.off(rva)
        return bytes(self.d[o:self.d.index(b'\0', o)])

    def exports(self):
        rva, size = struct.unpack_from('<II', self.d, self.ddir)
        hdr = struct.unpack_from('<IIHHIIIIIII', self.d, self.off(rva))
        nfuncs, nnames, funcs_rva, names_rva, ords_rva = hdr[6:]
        funcs = list(struct.unpack_from('<%dI' % nfuncs, self.d, self.off(funcs_rva)))
        names = [self.cstr(r) for r in struct.unpack_from('<%dI' % nnames, self.d, self.off(names_rva))]
        ords = list(struct.unpack_from('<%dH' % nnames, self.d, self.off(ords_rva)))
        for f in funcs:
            assert not (rva <= f < rva + size), 'forwarder exports are not handled'
        return hdr, funcs, names, ords

    def coff_symbols(self):
        ptr, count = struct.unpack_from('<II', self.d, self.pe + 12)
        secs = self.sections()
        strtab = ptr + 18 * count
        out = {}
        i = 0
        while ptr and i < count:
            o = ptr + 18 * i
            raw = bytes(self.d[o:o + 8])
            if raw[:4] == b'\0\0\0\0':
                s = strtab + struct.unpack_from('<I', raw, 4)[0]
                name = bytes(self.d[s:self.d.index(b'\0', s)])
            else:
                name = raw.rstrip(b'\0')
            value, secnum = struct.unpack_from('<Ih', self.d, o + 8)
            if 0 < secnum <= len(secs):
                out.setdefault(name.decode('latin1'), set()).add(secs[secnum - 1]['va'] + value)
            i += 1 + self.d[o + 17]
        return out


def ldrp_tls_layout(pe, new_va, syms):
    """Write the stubs and records Dassault's loader looks for; returns a note."""
    d = pe.d
    text, rdata = pe.section(b'.text'), pe.section(b'.rdata')
    old_text = bytes(d[text['raw']:text['raw'] + text['vsize']])
    old_rdata = bytes(d[rdata['raw']:rdata['raw'] + rdata['vsize']])
    assert RELEASE_PROLOGUE not in old_text and b'LdrpHandleTlsData\0' not in old_rdata

    a = (text['vsize'] + 8 + 15) // 16 * 16              # LdrpHandleTlsData stub, int3s before it
    while True:
        func = text['va'] + a
        funclet = func + 8
        if struct.pack('<I', funclet) not in old_rdata:  # the record must be the only match
            break
        a += 16
    rel = lambda frm, to: struct.pack('<i', to - frm)
    r = (rdata['vsize'] + 7) // 8 * 8
    string_rva = rdata['va'] + r
    stub = b'\xe9' + rel(func + 5, new_va + syms['LdrpHandleTlsData_impl']) + b'\xcc' * 3
    stub += b'\x48\x8d\x15' + rel(funclet + 7, string_rva) + b'\xc3'
    stub += b'\xcc' * 16
    rel_func = func + len(stub)                           # LdrpReleaseTlsEntry stub
    tail = bytes.fromhex('488bcb 488bd7 4883c420 5f 488b5c2408'.replace(' ', ''))
    body = RELEASE_PROLOGUE + b'\x90' * 12 + tail
    stub += body + b'\xe9' + rel(rel_func + len(body) + 5, new_va + syms['LdrpReleaseTlsEntry_impl']) + b'\xcc' * 8
    new_text = a + len(stub)
    record = b'LdrpHandleTlsData\0'.ljust(24, b'\0') + struct.pack('<IIII', func, func + 5, funclet, 0)
    new_rdata = r + len(record)
    assert new_text <= text['rsize'] and new_rdata <= rdata['rsize'], 'not enough spare room in .text/.rdata'

    d[text['raw'] + text['vsize']:text['raw'] + a] = b'\xcc' * (a - text['vsize'])
    d[text['raw'] + a:text['raw'] + new_text] = stub
    d[rdata['raw'] + rdata['vsize']:rdata['raw'] + r] = b'\0' * (r - rdata['vsize'])
    d[rdata['raw'] + r:rdata['raw'] + new_rdata] = record
    struct.pack_into('<I', d, text['hdr'] + 8, new_text)
    struct.pack_into('<I', d, rdata['hdr'] + 8, new_rdata)
    return 'LdrpHandleTlsData stub at rva %#x, LdrpReleaseTlsEntry stub at %#x' % (func, rel_func)


def main(argv):
    src, dst, blob_path, syms_path = argv[:4]
    want, ldrp = [], False
    args = argv[4:]
    while args:
        a = args.pop(0)
        if a == '--export':
            name, _, sym = args.pop(0).partition('=')
            want.append((name, sym or name))
        elif a == '--ldrp-tls':
            ldrp = True
        else:
            sys.exit('unknown argument ' + a)

    pe = PE(src)
    d = pe.d
    blob = bytearray(open(blob_path, 'rb').read())
    syms = {}
    for line in open(syms_path):
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)

    hdr, funcs, names, ords = pe.exports()
    flags, stamp, vmaj, vmin, name_rva, base, nfuncs, nnames = hdr[:8]
    want = [(n, s) for n, s in want if n.encode() not in names]
    secs = pe.sections()
    first_raw = min(s['raw'] for s in secs if s['raw'])
    size_of_headers = struct.unpack_from('<I', d, pe.opt + 60)[0]
    assert pe.sectab + 40 * (pe.nsec + 1) <= min(first_raw, size_of_headers), 'no room for a section header'
    new_va = (max(s['va'] + max(s['vsize'], 1) for s in secs) + pe.salign - 1) // pe.salign * pe.salign
    new_raw = (len(d) + pe.falign - 1) // pe.falign * pe.falign

    by_name = {n: funcs[o] for n, o in zip(names, ords)}
    coff = None
    for sym, slot in syms.items():
        if sym.startswith('slot_'):
            target = by_name[sym[5:].encode()]
        elif sym.startswith('symslot_'):
            coff = coff or pe.coff_symbols()
            found = coff.get(sym[8:], set())
            assert len(found) == 1, '%s: %d COFF symbols found' % (sym[8:], len(found))
            target = next(iter(found))
        else:
            continue
        assert struct.unpack_from('<i', blob, slot)[0] == 0x5a5a5a5a, 'slot marker missing in ' + sym
        struct.pack_into('<i', blob, slot, target - (new_va + slot))

    code = bytes(blob) + b'\xcc' * (-len(blob) % 16)
    exp_off = len(code)                       # export data starts after the code
    entries = list(zip(names, ords))
    for name, sym in want:
        entries.append((name.encode(), len(funcs)))
        funcs.append(new_va + syms[sym])
    entries.sort()
    p_funcs = exp_off + 40
    p_names = p_funcs + 4 * len(funcs)
    p_ords = p_names + 4 * len(entries)
    p_str = p_ords + 2 * len(entries)
    strings = bytearray(pe.cstr(name_rva) + b'\0')
    str_rva = []
    for n_, _ in entries:
        str_rva.append(new_va + p_str + len(strings))
        strings += n_ + b'\0'
    exp = bytearray(struct.pack('<IIHHIIIIIII', flags, stamp, vmaj, vmin, new_va + p_str, base, len(funcs),
                                len(entries), new_va + p_funcs, new_va + p_names, new_va + p_ords))
    exp += struct.pack('<%dI' % len(funcs), *funcs)
    exp += struct.pack('<%dI' % len(entries), *str_rva)
    exp += struct.pack('<%dH' % len(entries), *[o for _, o in entries])
    exp += strings
    body = code + bytes(exp)
    vsize = len(body)
    rsize = (vsize + pe.falign - 1) // pe.falign * pe.falign

    note = ldrp_tls_layout(pe, new_va, syms) if ldrp else ''

    nsec = pe.nsec
    d += b'\0' * (new_raw - len(d))
    d += body + b'\0' * (rsize - vsize)
    d[pe.sectab + 40 * nsec:pe.sectab + 40 * nsec + 40] = struct.pack(
        '<8sIIIIIIHHI', b'.swx', vsize, new_va, rsize, new_raw, 0, 0, 0, 0, 0x60000020)  # code | execute | read
    struct.pack_into('<H', d, pe.pe + 6, nsec + 1)
    struct.pack_into('<I', d, pe.opt + 56, (new_va + vsize + pe.salign - 1) // pe.salign * pe.salign)
    struct.pack_into('<II', d, pe.ddir, new_va + exp_off, len(exp))
    struct.pack_into('<I', d, pe.opt + 64, 0)   # checksum
    open(dst, 'wb').write(d)
    print('%s: section .swx at rva %#x, exports added: %s%s' % (
        dst, new_va, ', '.join(n for n, _ in want) or 'none', '; ' + note if note else ''))


if __name__ == '__main__':
    if len(sys.argv) < 5:
        sys.exit(__doc__)
    main(sys.argv[1:])
