"""Read on-disk crate dependencies and local definition keys from the exact RC22 metadata format."""

import re


class Reader:
    def __init__(self, b, pre):
        self.b = b
        self.pos = 0
        self.pre = pre

    def byte(self):
        self.pos += 1
        return self.b[self.pos - 1]

    def var(self):
        x = 0
        for sh in range(0, 64, 7):
            v = self.byte()
            x |= (v & 127) << sh
            if v < 128:
                return x
        raise ValueError("invalid rustc unsigned LEB")

    def take(self, n):
        assert 0 <= n <= len(self.b) - self.pos
        v = self.b[self.pos : self.pos + n]
        self.pos += n
        return v

    def string(self):
        s = self.take(self.var()).decode()
        assert self.byte() == 0xC1
        return s

    def sym(self):
        t = self.byte()
        if t == 2:
            i = self.var()
            return self.pre.get(i, "PREDEFINED#" + str(i))
        if t == 0:
            return self.string()
        assert t == 1
        ofs = self.var()
        old = self.pos
        assert 0 < ofs < old
        self.pos = ofs
        s = self.string()
        self.pos = old
        return s


def symbols(text):
    keys, sy = text.split("Keywords {", 1)[1].split("Symbols {", 1)
    names = [m[1] for m in re.findall(r'^\s*(\w+):\s*"([^"\n]+)"', keys, re.M)]
    assert names[56] == "'_"
    sy = sy.replace("little, big,", "little,\n        big,")
    sy = re.sub(r"\\\n\s*", "", sy)  # Rust continuation in a multi-line literal.
    for line in sy.splitlines():
        if line.strip() == "}":
            break
        m = re.match(r'^\s*(\w+)(?::\s*"([^"]*)")?,\s*(?://.*)?$', line)
        if m:
            names.append(m[2] if m[2] is not None else m[1])
    return dict(enumerate(names))
