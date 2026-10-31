"""Reopen raw Cargo events, query failures, emitted ELF bytes, exported names and native verdicts."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native import CASES, phases, CARGO_SHA, WILD, PARENT, parameters, hidden, need, save


def read(p):
    return json.loads(p.read_bytes())


def verify_case(cell, role, revision):
    s = read(cell / "subject.json")
    case = cell.name
    fixture, binary, abi, args = parameters(case)
    need(s["case"] == case and s["argv"] == args and s["role"] == (revision if role == "candidate" else PARENT),
         "mismatched producer")
    need(s["versions"]["cargo"]["sha256"] == CARGO_SHA and s["versions"]["wild"] == WILD, "changed controls")
    if role == "migration":
        need(("commit-hash: " + revision + "\n") in read(cell / "migrated.json")["rustc"]["version"], "wrong upgrade")
    need({x.name for x in cell.iterdir() if x.is_dir()} == set(phases(role == "migration")) | {"bodies"}, "wrong phase inventory")
    subjects = {}
    with tempfile.TemporaryDirectory() as temporary:
        for path in (cell / "bodies").iterdir():
            data = gzip.decompress(path.read_bytes())
            digest = hashlib.sha256(data).hexdigest()
            need(path.name == digest + ".gz" and data[:4] == b"\x7fELF", "wrong ELF")
            local = Path(temporary) / digest
            local.write_bytes(data)
            symbols = subprocess.check_output(["nm", "-a", local], text=True)
            subjects[digest] = [line.split()[-1] for line in symbols.splitlines()
                                if re.search(r"\s(?:ohm_retained_hook_|ohm_private_abi_hook)", line)]
    hashes = {}
    rows = {}
    all_diagnostics = {}
    for phase in phases(role == "migration"):
        d = cell / phase
        state = phase[-1]
        v = read(d / "visit.json")
        raw = [json.loads(l) for l in gzip.decompress((d / "stdout.gz").read_bytes()).splitlines()]
        stderr = gzip.decompress((d / "stderr.gz").read_bytes()).decode()
        ice = role == "parent" and case != "body" and phase in ("edit-B", "unchanged-B", "return-B")
        invalid = "invalid" in phase
        code = 101 if ice or invalid else 0
        source = hidden(fixture, case, state) + (b'const _: u8 = "wrong";\n' if invalid else b"")
        need(v["source"] == hashlib.sha256(source).hexdigest(), ("unexpected source", phase))
        need(v["code"] == code and raw[-1] == {"reason":"build-finished", "success":code == 0}
             and sum(e["reason"] == "build-finished" for e in raw) == 1, (case, phase, "Cargo status", v["code"], code))
        arts = [[e["target"]["name"], e["fresh"]] for e in raw if e["reason"] == "compiler-artifact"]
        need(arts == v["artifacts"], "wrong typed artifacts")
        diag = [e["message"] for e in raw if e["reason"] == "compiler-message" and e["message"]["level"] == "error"]
        if ice:
            query, leaf = {"abi": ("fn_sig", "abi_probe_dep::hidden::hook"),
                           "nested": ("type_of", "abi_probe_dep::hidden::Wire::value")}.get(
                           case, ("codegen_fn_attrs", "fixture_dep::hidden::REGISTER"))
            need("Found unstable fingerprints for " + query + "(" in stderr and "#" in stderr
                 and "[" + query + "]" in stderr and leaf in stderr and "elf" not in v, (case, phase, "wrong ICE"))
        elif invalid:
            need("unstable fingerprints" not in stderr and not list(d.glob("rustc-ice*")), "invalid phase ICE")
            coded = [(m["code"]["code"], m["message"], [(sp["file_name"], sp["line_start"], sp["column_start"])
                      for sp in m["spans"] if sp["is_primary"]]) for m in diag if m["code"]]
            need(len(coded) == 1 and coded[0][0] == "E0308" and len(coded[0][2]) == 1
                 and coded[0][2][0][0] == "dep/src/hidden.rs" and "elf" not in v, (case, phase, coded))
            all_diagnostics[phase] = coded
        else:
            need(not diag and "internal compiler error" not in stderr and "unstable fingerprints" not in stderr,
                 "unexpected compiler error")
            consumer = "test_owner" if binary else ("native" if abi else "control")
            need([n for n, _ in arts] == ["abi_probe_dep" if abi else "fixture_dep", consumer], (phase, arts))
            if phase in ("cold-A", "empty-A", "empty-B"):
                need(all(not fresh for _, fresh in arts), ("not an empty control", phase, arts))
            if phase in ("unchanged-A", "unchanged-B"):
                need(all(fresh for _, fresh in arts), ("unexpected compiler on unchanged successful source", phase, arts))
            expected = 17 if state == "A" or case == "name" else (0x100000011 if abi else 83)
            sym = "ohm_private_abi_hook" if abi else "ohm_retained_hook_" + (
                      "aaaa" if state == "A" or case == "body" else "bbbb")
            digest = v["elf"]
            need(subjects.get(digest) == [sym], ("wrong actual export", phase, sym))
            if not binary:
                lines = (d / "inventory.txt").read_text().splitlines()
                test = "library_answer" if abi else "root_value"
                need(lines == [test + ": test", "", "1 test, 0 benchmarks"], ("wrong test inventory", lines))
            for want in (17, 0x100000011 if abi else 83):
                result = (d / f"native-{want}.txt").read_text()
                phrase = r"actual ABI value=(\d+)" if abi else r"actual native = (\d+)"
                need(re.findall(phrase, result) == [str(expected)] and
                     v["executions"][str(want)] == (0 if expected == want else 101), (phase, want, result))
            hashes[phase] = digest
        rows[phase] = {"cargo": code, "query_or_error": query if ice else "E0308" if invalid else None,
                       "elf": v.get("elf")}
    need(all_diagnostics["invalid-A"] == all_diagnostics["empty-invalid-A"], "wrong repaired diagnostics")
    need(set(subjects) == set(hashes.values()), "unused or absent retained ELF")
    for phase, digest in hashes.items():
        if role == "migration" and phase in ("cold-A", "unchanged-A"):
            continue
        need(digest == hashes["empty-" + phase[-1]], (case, phase, "different own-mode clean ELF"))
    need(hashes["empty-A"] != hashes["empty-B"], "edit did not change the executable")
    return rows


def verify(root, role, revision, cases):
    return {c: verify_case(root / c, role, revision) for c in cases}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    p.add_argument("role", choices=("parent", "candidate", "migration"))
    p.add_argument("revision")
    p.add_argument("--case", action="append", choices=CASES)
    opts = p.parse_args()
    result = verify(opts.root, opts.role, opts.revision, opts.case or CASES)
    save(opts.root / "verified.json", result)
    print("verified", opts.role, len(result), sum(map(len, result.values())), flush=True)
