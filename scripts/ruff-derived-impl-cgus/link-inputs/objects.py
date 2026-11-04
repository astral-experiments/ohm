"""Decode the signed Wild 0.11 postcard layout and the original regular Unix archives."""

import hashlib
import mmap
import os


def require(value, label):
    if not value:
        raise ValueError(label)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def archives(path):
    with path.open("rb") as f:
        magic = f.read(8)
        if magic != b"!<arch>\n":
            require(magic != b"!<thin>\n", "thin archive needs external member custody")
            return None
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            at, names, rows = 8, None, []
            while at < len(data):
                h = data[at : at + 60]
                require(len(h) == 60 and h[58:] == b"`\n", "bad archive header")
                n = int(h[48:58].strip())
                raw = h[:16].rstrip(b" ")
                start = at + 60
                end = start + n
                require(
                    start <= end <= len(data) and len(rows) < 100_000, "bad member span"
                )
                if raw == b"//":
                    require(names is None and n <= 8 << 20, "bad GNU names")
                    names = data[start:end]
                if raw.startswith(b"/") and raw[1:].isdigit():
                    skip = int(raw[1:])
                    require(
                        names is not None and 0 <= skip < len(names),
                        "bad GNU name offset",
                    )
                    stop = names.index(b"/\n", skip)
                    name = names[skip:stop]
                elif raw.startswith(b"#1/"):
                    length = int(raw[3:])
                    require(0 < length <= n, "bad BSD filename")
                    name = data[start : start + length].rstrip(b"\0")
                    start += length
                elif raw in (b"//", b"/", b"/SYM64/"):
                    name = raw
                else:
                    require(raw.endswith(b"/"), "unknown member name encoding")
                    name = raw[:-1]
                with memoryview(data)[start:end] as body:
                    rows.append([os.fsdecode(name), start, end, sha(body)])
                at = end + n % 2
                if n % 2:
                    require(data[end:at] == b"\n", "bad archive alignment")
            require(at == len(data), "truncated archive")
            return rows


class Wire:
    def __init__(self, data):
        self.data, self.i = data, 0

    def byte(self):
        result = self.data[self.i]
        self.i += 1
        return result

    def integer(self):
        out = 0
        for shift in range(0, 64, 7):
            value = self.byte()
            out |= (value & 127) << shift
            if value < 128:
                require(
                    (not shift or value != 0) and out < 2**64, "invalid encoded integer"
                )
                return out
        raise ValueError("oversized integer")

    def string(self):
        n = self.integer()
        require(n <= 65536 and self.i + n <= len(self.data), "bad layout string")
        out = os.fsdecode(self.data[self.i : self.i + n])
        self.i += n
        return out


def layout(path):
    raw = path.read_bytes()
    require(0 < len(raw) < 256 << 20, "invalid Wild layout size")
    r = Wire(raw)
    rows = []
    count = r.integer()
    require(0 < count < 200_000, "unexpected object count")
    for _ in range(count):
        disk = r.string()
        tag = r.byte()
        require(tag in (0, 1), "bad archive option")
        member = None if not tag else [r.integer(), r.integer(), r.string()]
        n = r.integer()
        require(n < 2_000_000, "oversized section table")
        at = r.i
        retained = byte_count = 0
        for _ in range(n):
            present = r.byte()
            require(present in (0, 1), "bad section option")
            if present:
                start, end = r.integer(), r.integer()
                require(start <= end, "reversed native section")
                retained += 1
                byte_count += end - start
        data = sha(raw[at : r.i])
        temp = r.byte()
        require(temp in (0, 1), "bad input tag")
        rows.append([disk, member, n, retained, byte_count, data, temp])
    thunks = r.integer()
    require(r.i == len(raw), "unknown layout suffix")
    return rows, thunks
