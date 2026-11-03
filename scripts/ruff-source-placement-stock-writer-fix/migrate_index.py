"""Exchange one independently valid historical entry while preserving the real native object and base index."""

from hashlib import sha256
import ast
import re
import struct
import subprocess

from stock_footer import END, MAGIC, parse


QUOTED = re.compile(r'"(?:\\.|[^"\\])*"')
B3SUM = "/usr/bin/b3sum"


def kernel_read(traces, original):
    links, opened = [], []
    for name, stream in traces:
        for data in stream:
            if b"work-products.bin" not in data or b" = -1 " in data:
                continue
            line = data.decode().rstrip("\n")
            if not re.search(r"\s= [0-9]+(?:<.*>)?\s*$", line):
                continue
            names = [ast.literal_eval(s) for s in QUOTED.findall(line)]
            record = {"trace": name, "line_sha256": sha256(data).hexdigest()}
            if line.startswith(("link(", "linkat(")) and len(names) >= 2:
                links.append((names[0], names[1], record))
            elif line.startswith(("openat(", "openat2(", "open(")) and names and "O_RDONLY" in line:
                opened.append((names[0], record))
    reached = {original: []}
    while True:
        size = len(reached)
        for before, after, rec in links:
            if before in reached and after not in reached:
                reached[after] = reached[before] + [rec]
        if len(reached) == size:
            break
    matches = [reached[name] + [rec] for name, rec in opened if name in reached]
    need(matches, "no successful kernel read of the challenged index or its actual hardlink")
    return min(matches, key=lambda rows: (len(rows), [x["line_sha256"] for x in rows]))


def need(condition, message):
    if not condition:
        raise ValueError(message)


def framed_seal(obj, wire):
    result = subprocess.run(
        [B3SUM, "--no-names"],
        input=obj + wire + struct.pack("<Q", len(wire)),
        stdout=subprocess.PIPE,
        check=True,
    )
    return bytes.fromhex(result.stdout.decode().strip())


def open_entry(index, version, obj, *, slot=None):
    table = parse(index, version)
    need(table is not None and obj.startswith(b"\x7fELF\x02\x01"), "no physical placed ELF record")
    cursor = table["offset"] + len(MAGIC)
    matching = []
    for position, size, key, seal in table["entries"]:
        at = cursor + 8
        raw = index[at : at + size]
        need(struct.unpack_from("<II", index, cursor) == (position, size), "entry changed")
        if slot is None or position == slot:
            wire = raw[:-32]
            if framed_seal(obj, wire) == raw[-32:]:
                matching.append((position, at, raw))
        cursor = at + size
    need(
        cursor == len(index) - len(END) and len(matching) == 1,
        "old object must authenticate exactly one original placement",
    )
    return matching[0]


def swap(index, dest_version, obj, foreign_index, foreign_version, foreign_slot):
    need({dest_version, foreign_version} == {3, 4}, "not an OSP3/4 upgrade or downgrade")
    pos, at, incumbent = open_entry(index, dest_version, obj)
    donor_slot, _, donor = open_entry(foreign_index, foreign_version, obj, slot=foreign_slot)
    need(
        incumbent[:4] != donor[:4]
        and incumbent[4:36] != donor[4:36]
        and incumbent[36:-32] == donor[36:-32]
        and incumbent[-32:] != donor[-32:],
        "changed placement coordinates, missing version distinction, or same key or seal",
    )
    changed = index[:at] + donor + index[at + len(incumbent) :]
    need(
        len(changed) == len(index)
        and changed[:at] == index[:at]
        and changed[at + len(donor) :] == index[at + len(incumbent) :],
        "a second row or legacy index changed",
    )
    return changed, {
        "destination_slot": pos,
        "donor_slot": donor_slot,
        "offset": at,
        "bytes": len(donor),
        "object_sha256": sha256(obj).hexdigest(),
        "destination_index_sha256": sha256(index).hexdigest(),
        "donor_index_sha256": sha256(foreign_index).hexdigest(),
        "changed_index_sha256": sha256(changed).hexdigest(),
        "legacy_prefix_sha256": parse(index, dest_version)["prefix_sha256"],
        "destination_wire_key": incumbent[4:36].hex(),
        "donor_wire_key": donor[4:36].hex(),
        "destination_b3": incumbent[-32:].hex(),
        "donor_b3": donor[-32:].hex(),
        "equal_placement_sha256": sha256(donor[36:-32]).hexdigest(),
        "unchanged_records": len(parse(index, dest_version)["entries"]) - 1,
    }
