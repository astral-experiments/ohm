"""Reopen the rejected pre-timing enrollment and exercise the prospective whole-file comparator."""

import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from macho_paths import canonical, compare
from study import need, save

ORIGINAL = "777a63bd3105370057ec66646b785b4b0e43926e2f17a4ade6d12f39ce5d44bf"


def rehash_one_page(data, index):
    copy = bytearray(data)
    cursor = 32
    for _ in range(struct.unpack_from("<I", data, 16)[0]):
        cmd, n = struct.unpack_from("<II", data, cursor)
        if cmd == 0x1D:
            start, _ = struct.unpack_from("<II", data, cursor + 8)
        cursor += n
    base = start + struct.unpack_from(">I", data, start + 16)[0]
    hashes = struct.unpack_from(">I", data, base + 16)[0]
    page_size = 1 << data[base + 39]
    i = index // page_size
    offset = base + hashes + 32 * i
    copy[offset : offset + 32] = hashlib.sha256(
        copy[i * page_size : min(start, (i + 1) * page_size)]
    ).digest()
    return bytes(copy)


def reject(f):
    try:
        f()
    except RuntimeError:
        return True
    raise RuntimeError("invalid native evidence was accepted")


def reopen(path):
    assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == ORIGINAL
    results = {}
    with zipfile.ZipFile(path) as z:
        assert not any(
            "/pair-" in n or n.endswith("/time.txt") and n.startswith("test-screen/")
            for n in z.namelist()
        )
        for state, rows, expected_bytes in (("old", 29, 533), ("new", 30, 548)):
            arms = {}
            for role in "PC":
                stem = f"test-screen/native-before/{role}/empty-{state}/clean/"
                rec = json.loads(z.read(stem + "verified.json"))
                events = map(
                    json.loads, gzip.decompress(z.read(stem + "stdout.gz")).splitlines()
                )
                (p,) = [
                    r["executable"]
                    for r in events
                    if r.get("executable")
                    and r["target"]["name"] == "ruff_python_ast"
                    and r["profile"]["test"]
                ]
                (link,) = [
                    r["argv"]
                    for r in rec["native"]["linkers"]
                    if [v for k, v in zip(r["argv"], r["argv"][1:]) if k == "-o"] == [p]
                ]
                h = rec["product"]["raw"]
                data = gzip.decompress(z.read("test-executables/" + h + ".macho.gz"))
                assert hashlib.sha256(data).hexdigest() == h
                arms[role] = (data, p, link)
            result = compare(arms)
            assert (
                len(result["P"]["paths"]) == len(result["C"]["paths"]) == rows
                and result["raw_difference_bytes"] == expected_bytes
            )
            original, p, args = arms["C"]
            # Corrupt a covered real program byte. First reject the damaged signature,
            # then recompute its genuine page slot and require full-program equality to catch it.
            index = 16384
            mutated = bytearray(original)
            mutated[index] ^= 1
            reject(lambda: canonical(bytes(mutated), p, args))
            valid_signature = rehash_one_page(mutated, index)
            canonical(valid_signature, p, args)
            reject(lambda: compare(arms | {"C": (valid_signature, p, args)}))
            # An actual changed debug object cannot be exempt without physical linker provenance.
            absolute = (
                result["C"]["base"] + result["C"]["key"] + "/" + result["C"]["paths"][0]
            ).split("(")[0]
            reject(lambda: canonical(original, p, [v for v in args if v != absolute]))
            # A changed namespace in a different workspace is also ineligible.
            wrong = p.replace("64e8753c5e9f70b3", "64e8753c5e9f70b4")
            reject(
                lambda: canonical(
                    original, wrong, [wrong if v == p else v for v in args]
                )
            )
            results[state] = result
    return {
        "raw_sha256": ORIGINAL,
        "negative_controls": 4,
        "timed_pairs": 0,
        "source_states": results,
    }


if __name__ == "__main__":
    original, dest = sys.argv[1:]
    data = reopen(original)
    save(Path(dest), data)
