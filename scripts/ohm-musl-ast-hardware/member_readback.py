"""Read the actual GNU ar members and locate any byte differences within a repeated Ruff source state."""
from collections import Counter
import gzip
import hashlib
import json
import re
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = ROOT / "ast"

def sha(x):
    return hashlib.sha256(x).hexdigest()

def archive(raw):
    assert raw.startswith(b"!<arch>\n")
    at = 8
    table = b""
    records = []
    while at < len(raw):
        header = raw[at:at + 60]
        assert len(header) == 60 and header[58:] == b"`\n"
        size = int(header[48:58].strip())
        data = raw[at + 60:at + 60 + size]
        assert len(data) == size
        short = header[:16].decode().rstrip(" ")
        if short == "//":
            table = data
            name = short
        elif short.startswith("/") and short[1:].isdigit():
            offset = int(short[1:])
            assert 0 <= offset < len(table)
            stop = table.index(b"/\n", offset)
            name = table[offset:stop].decode()
        elif short in ("/", "/SYM64/"):
            name = short
        else:
            name = short.removesuffix("/")
        records.append((name, header, data))
        at += 60 + size
        if at & 1:
            assert raw[at:at + 1] == b"\n"
            at += 1
    assert at == len(raw)
    return records

def sections(buf):
    ident = buf[:16]
    assert ident[:7] == b"\x7fELF\x02\x01\x01"
    e = struct.unpack_from("<HHIQQQIHHHHHH", buf, 16)
    off, entsize, n, names = e[5], e[10], e[11], e[12]
    hdr = struct.Struct("<IIQQQQIIQQ")
    assert entsize == hdr.size and n and 0 < names < n
    entries = [hdr.unpack_from(buf, off + i * entsize) for i in range(n)]
    table = entries[names]
    strings = buf[table[4]:table[4]+table[5]]
    out = []
    for section in entries:
        start = section[0]
        name = strings[start:strings.index(0, start)].decode()
        data = buf[section[4]:section[4] + section[5]] if section[1] != 8 else b""
        out.append((name, sha(data)))
    return out

def summary(raw):
    items = archive(raw)
    assert len({name for name,_,_ in items}) == len(items)
    return {"sha256":sha(raw),"bytes":len(raw),"members":len(items),
        "ordered_names_sha256":sha("\n".join(x[0] for x in items).encode()),
        "members_by_name":{n:{"sha256":sha(d),"bytes":len(d),"header":h.hex()} for n,h,d in items}}

def compare(left, right):
    a, b = archive(left), archive(right)
    by_name_a = {n:(h,d) for n,h,d in a}
    by_name_b = {n:(h,d) for n,h,d in b}
    common = sorted(by_name_a.keys() & by_name_b.keys())
    changed = {}
    for name in common:
        before, after = by_name_a[name][1], by_name_b[name][1]
        if before == after:
            continue
        distinct = {}
        if before[:4] == after[:4] == b"\x7fELF":
            ls, rs = sections(before), sections(after)
            distinct["ordered_elf_sections_equal"] = ls == rs
            distinct["different_sections"] = [n for n,h in (Counter(ls)-Counter(rs)).elements()]
        if len(before) == len(after):
            positions = [i for i, (x,y) in enumerate(zip(before,after)) if x != y]
            distinct["bytes_different"] = len(positions)
            distinct["first_offset"] = positions[0]
            distinct["last_offset"] = positions[-1]
        changed[name] = distinct
    return {"same_member_order": [x[0] for x in a] == [x[0] for x in b],
        "left_only":sorted(by_name_a.keys()-by_name_b.keys()), "right_only":sorted(by_name_b.keys()-by_name_a.keys()),
        "header_differences":{n:[by_name_a[n][0].decode().strip(),by_name_b[n][0].decode().strip()]
            for n in common if by_name_a[n][0] != by_name_b[n][0]},
        "changed_payloads":changed}

def payload_proof(left, right):
    def objects(raw):
        entries = archive(raw)
        tags = set()
        out = {}
        for n, _, data in entries:
            if not n.endswith(".rcgu.o"):
                continue
            match = re.fullmatch(r"(.*)\.([a-z0-9]{7})\.rcgu\.o", n)
            assert match and match[1] not in out
            tags.add(match[2])
            out[match[1]] = sha(data)
        assert len(tags) == 1 and len(out) == 100
        return ("." + tags.pop() + ".rcgu.o").encode(), out
    a, ao = objects(left)
    b, bo = objects(right)
    transformed = left.replace(a, b)
    return {"left_tag":a.decode(), "right_tag":b.decode(), "left_tag_occurrences":left.count(a),
            "right_tag_occurrences":right.count(b), "after_substitution_sha256":sha(transformed),
            "entire_file_equal_after_one_substitution":transformed == right,
            "ordered_object_identities_equal":list(ao) == list(bo),
            "left_objects":len(ao), "right_objects":len(bo),
            "objects_byte_equal":sum(value == bo.get(name) for name, value in ao.items()),
            "changed_or_missing_objects":[k for k,v in ao.items() if bo.get(k)!=v]}

def run():
    rows = json.loads((ORIGIN/"result.json").read_bytes())["rows"]
    data = {}
    inputs = {}
    for phase in ("old-cold","old-first","old-settled","edited","first","settled"):
        size, digest = rows[phase]["root_outputs"]["libruff_python_ast.rlib"]
        packet = ORIGIN/"data"/(digest+".gz")
        inputs[phase] = {"bytes":size,"sha256":digest,"retained":packet.exists()}
        if packet.exists():
            raw = gzip.decompress(packet.read_bytes())
            assert sha(raw) == digest and len(raw) == size
            data[phase] = raw
    assert set(data) == {"old-cold","edited","settled"}
    out = {"inputs":inputs,"retained":{p:summary(d) for p,d in data.items()},
           "same_source_edited_to_settled":compare(data["edited"],data["settled"]),
           "salt_proof":payload_proof(data["edited"],data["settled"]),
           "historical_edit_objects":payload_proof(data["old-cold"],data["edited"])}
    assert out["salt_proof"]["entire_file_equal_after_one_substitution"]
    assert out["salt_proof"]["objects_byte_equal"] == 100
    assert out["historical_edit_objects"]["objects_byte_equal"] < 100
    print(json.dumps(out,indent=2,sort_keys=True))

if __name__ == "__main__":
    run()
