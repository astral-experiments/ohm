"""Recount the original successful kernel execs and compare the native lookup with clean output."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import tarfile

path = Path(__file__).with_name("originals.tar.gz")
assert hashlib.sha256(path.read_bytes()).hexdigest() == "bc9977a6c5fa4176cff214c2906c8c3dabacae7f80890eb13a10aab633d9e532"
with tarfile.open(path) as f:
    files = {entry.name: f.extractfile(entry).read() for entry in f}
doc = lambda name: json.loads(files[name])
raw = lambda name: gzip.decompress(files[name + ".gz"])
product = doc("product.json")
assert product["parents"] == ["2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c", "c18e91b514b2c4e4966c9ab03232c804af3e1b57"]
assert product["git"] == "fd55a13d0220748794ba3c7c9556ef8ceed8591f" and product["typed_units"] == 389
assert product["sha256"] == "a5345089c120942d881ebf4f67f86e6f01a6d4e19d30df047ef6ac9baa6cf429"
assert b"7e71d3150938ff8ed82aca03416439d7e5b87ef3" in raw("compiler/stdout")
assert product["parents"][0].encode() in raw("builder/stdout") and product["git"].encode() in raw("result-version/stdout")
assert b"recheck_links_only_for_the_compiler_generated_marker ... ok" in raw("marker-tests/stdout")
assert b"; 0 failed;" in raw("marker-tests/stdout")
summary = doc("unicode-terminal.json")
assert len(summary) == 28
for reader in ("signed", "integrated"):
    for target in ("plain", "explicit-host"):
        arm = reader + "-" + target
        sources = {}
        for phase in ("cold", "first", "repeat", "edit", "edit-repeat", "clean-edit", "bad", "repair"):
            prefix = arm + "/" + phase
            command = doc(prefix + "/command.json")
            argv = command["argv"]
            assert argv[argv.index("cargo") + 1:argv.index("cargo") + 5] == ["+ohm", "build", "-p", "ruff_unicode_names2"]
            assert ("--target" in argv) == (target == "explicit-host")
            assert command["returncode"] == (101 if phase == "bad" else 0)
            events = [json.loads(line) for line in raw(prefix + "/stdout").splitlines()]
            assert events[-1] == {"reason": "build-finished", "success": phase != "bad"}
            if phase == "bad":
                assert any((r.get("message", {}).get("code") or {}).get("code") == "E0425" and
                           "OHM_UNKNOWN_294_QA" in r["message"]["rendered"] for r in events)
                continue
            r, = [v for v in summary if v["arm"] == arm and v["phase"] == phase]
            units = [m for m in events if m["reason"] == "compiler-artifact"]
            dirty = [m["target"]["name"] for m in units if not m["fresh"]]
            assert len(units) == 17 and r["dirty"] == dirty
            actual = collections.Counter()
            for line in raw(prefix + "/execve").splitlines():
                path = re.match(rb'execve\("([^"]+)",', line)
                assert path and line.endswith(b" = 0")
                actual[Path(path[1].decode()).name] += 1
            assert actual == r["kernel"]
            if phase in ("first", "repeat", "edit-repeat"):
                assert not dirty and actual["rustc"] == actual["ld.bfd"] == 0
            if phase in ("edit", "repair"):
                assert set(dirty) == {"build-script-build", "unicode_names2"} and actual["rustc"] == 2 and actual["ld.bfd"] == 1
            expected = b"None\nSome(0)\nSome(0)\n" if phase in ("edit", "edit-repeat", "clean-edit") else b"Some(0)\nNone\nSome(0)\n"
            assert raw(prefix + "/probe/stdout") == expected
            sources[phase] = r["generated"]
        assert len(sources["cold"]) == 3 and sources["cold"] == sources["first"] == sources["repeat"] == sources["repair"]
        assert sources["edit"] == sources["edit-repeat"] == sources["clean-edit"]
        assert {name for name in sources["cold"] if sources["cold"][name] != sources["edit"][name]} == {"generated_alias.rs"}
        print(arm, "verified 8 Cargo commands and 7 native program returns")
