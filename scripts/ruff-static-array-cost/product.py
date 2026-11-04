"""Open a complete GNU rlib, including the special members hidden by ordinary ar t."""
import hashlib
import re


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def rlib(raw):
    assert raw[:8] == b"!<arch>\n"
    at = 8
    index = None
    long_names = None
    names_by_offset = {}
    payloads = {}
    starts = {}
    while at < len(raw):
        header = raw[at:at + 60]
        assert len(header) == 60 and header[58:] == b"`\n"
        size = int(header[48:58])
        name = header[:16].rstrip()
        start = at + 60
        stop = start + size
        assert size >= 0 and stop <= len(raw)
        data = raw[start:stop]
        if name == b"/":
            assert index is None
            index = data
        elif name == b"//":
            assert long_names is None
            long_names = data
            long_start = start
        else:
            if name.startswith(b"/"):
                assert name[1:].isdigit() and long_names is not None
                offset = int(name[1:])
                assert offset == 0 or long_names[offset - 2:offset] == b"/\n"
                name = long_names[offset:long_names.index(b"/\n", offset)]
            else:
                assert name.endswith(b"/")
                name = name[:-1]
            key = name.decode("ascii")
            assert key not in payloads and data.startswith(b"\x7fELF")
            payloads[key] = data
            names_by_offset[at] = key
            starts[key] = start
        if size % 2:
            assert raw[stop:stop + 1] == b"\n"
        at = stop + size % 2
    assert at == len(raw) and index is not None and long_names is not None
    assert len(payloads) == 15 and {k for k in payloads if not k.endswith(".o")} == {"lib.rmeta", "lib.rmeta-link"}

    link = payloads["lib.rmeta-link"]
    complete = bytearray(raw)
    physical = {name:sha(data) for name,data in payloads.items()}
    canonical = {"lib.rmeta":physical["lib.rmeta"]}
    stable_names = {"lib.rmeta":"lib.rmeta", "lib.rmeta-link":"lib.rmeta-link"}
    for name in payloads:
        if not name.endswith(".o"):
            continue
        match = re.fullmatch(r"(.+)\.([a-z0-9]{7})\.rcgu\.o", name)
        assert match and link.count(name.encode()) == 1
        stable = match[1] + "._______.rcgu.o"
        assert stable not in canonical
        encoded = name.encode()
        target = stable.encode()
        assert len(encoded) == len(target) and long_names.count(encoded) == 1 and raw.count(encoded) == 2
        for pos in (long_start + long_names.index(encoded), starts["lib.rmeta-link"] + link.index(encoded)):
            assert complete[pos:pos + len(encoded)] == encoded
            complete[pos:pos + len(encoded)] = target
        link = link.replace(encoded, target)
        canonical[stable] = physical[name]
        stable_names[name] = stable
    canonical["lib.rmeta-link"] = sha(link)

    count = int.from_bytes(index[:4], "big")
    assert 0 < count <= (len(index) - 4) // 4
    names = index[4 + 4 * count:].split(b"\x00")
    assert len(names) >= count and not any(names[count:]) and all(names[:count])
    symbols = []
    for number,symbol in enumerate(names[:count]):
        i = 4 + 4 * number
        offset = int.from_bytes(index[i:i + 4], "big")
        owner = stable_names[names_by_offset[offset]]
        symbols.append((symbol.decode("ascii"), owner))
    return {"physical":physical, "verified_renames":canonical}, symbols, sha(complete)
