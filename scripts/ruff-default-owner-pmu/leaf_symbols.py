"""Bind a kernel instruction IP to the sized symbols in the authenticated x86_64 ELF."""

import bisect
import mmap
import struct
import subprocess


class Symbols:
    def __init__(self, p):
        self.fd = p.open("rb")
        self.obj = mmap.mmap(self.fd.fileno(), 0, access=mmap.ACCESS_READ)
        b = self.obj
        assert b[:7] == b"\x7fELF\x02\x01\x01" and struct.unpack_from("<H", b, 18)[0] == 62
        phoff, shoff = struct.unpack_from("<QQ", b, 32)
        phsize, phnum, shsize, shnum = struct.unpack_from("<HHHH", b, 54)
        assert (phsize, shsize) == (56, 64)
        self.ex = []
        for num in range(phnum):
            ty, fl, off, va, _, fs, ms, align = struct.unpack_from("<II6Q", b, phoff + num * phsize)
            if ty == 1 and fl & 1:
                self.ex.append((off, off + fs, va))
        sections = [struct.unpack_from("<II4QII2Q", b, shoff + i * shsize) for i in range(shnum)]
        syms = [a for a in sections if a[1] == 2]
        assert len(syms) == 1
        _, _, _, _, so, sz, idx, _, _, ent = syms[0]
        assert ent == 24
        st = sections[idx]
        assert st[1] == 3
        self.nameoff = st[4]
        self.namelim = st[4] + st[5]
        self.func = []
        for off in range(so, so + sz, 24):
            nm, inf, other, sh, val, size = struct.unpack_from("<IBBHQQ", b, off)
            if inf & 15 in (2, 10) and sh and nm and size and sh < shnum and sections[sh][2] & 4:
                self.func.append((val, val + size, nm))
        self.func.sort()
        self.starts = [f[0] for f in self.func]
        self.maxend = []
        v = 0
        for _, end, _ in self.func:
            v = max(v, end)
            self.maxend.append(v)
        assert self.func

    def offset(self, va):
        hits = [off + va - addr for off, end, addr in self.ex if addr <= va < addr + end - off]
        assert len(hits) == 1, "instruction outside unique file-backed executable segment"
        return hits[0]

    def close(self):
        self.obj.close()
        self.fd.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def resolve(self, fo):
        vas = [a + fo - off for off, stop, a in self.ex if off <= fo < stop]
        if not vas:
            return set()
        assert len(vas) == 1, ("executable bytes do not belong to unique file-backed PT_LOAD", fo, vas)
        va = vas[0]
        k = bisect.bisect_right(self.starts, va) - 1
        matches = []
        while k >= 0 and self.maxend[k] > va:
            start, end, name = self.func[k]
            if start <= va < end:
                i = self.nameoff + name
                j = self.obj.find(b"\0", i, self.namelim)
                assert j > i
                matches.append(self.obj[i:j].decode())
            k -= 1
        return set(matches)


def demangle(names):
    q = list(names)
    output = subprocess.run(
        ["/usr/bin/c++filt", "-n"], input="\n".join(q) + "\n", text=True, stdout=subprocess.PIPE, check=True
    ).stdout.splitlines()
    assert len(output) == len(q)
    return dict(zip(q, output))
