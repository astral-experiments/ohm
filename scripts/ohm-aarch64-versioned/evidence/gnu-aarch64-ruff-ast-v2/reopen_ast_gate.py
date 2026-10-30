"""Verify the AST crate's own marker and its two imported compact_str assembly sites."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import zipfile


HARD = b"/dev/null/ohm-untracked-relink-inputs"
V2 = b"/dev/null/ohm-recheck-dependent-links-v2"
SYMBOL = b"_RNvMCs2O6kHReENuX_11compact_strNtB2_13CompactString8push_str"
PHASES = ("old-empty", "edit", "unchanged-1", "unchanged-2", "empty-edited")
HERE = Path(__file__).resolve().parent


def sha(body):
    return hashlib.sha256(body).hexdigest()


def file_sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_json(z, path):
    return json.loads(z.read(path))


def edit_member(z, folder, nm):
    archived = read_json(z, folder + "/verified.json")["archive"]
    library = z.read("objects/" + archived["raw"] + ".rlib")
    assert sha(library) == archived["raw"] and len(archived["objects"]) == 95
    fd = os.memfd_create("ruff_ast_reviewer")
    with os.fdopen(fd, "wb") as f:
        f.write(library)
        f.flush()
        result = subprocess.run(
            [nm, "--defined-only", "--no-demangle", "--print-file-name", f"/proc/self/fd/{fd}"],
            pass_fds=(fd,), capture_output=True, check=True,
        )
    match, = [line for line in result.stdout.splitlines() if line.endswith(b" t " + SYMBOL)]
    path, member, _ = match.decode().split(":", 2)
    assert path == f"/proc/self/fd/{fd}"
    payload, = [row for row in archived["objects"] if row[1] == member]
    return {"archive_sha256": archived["raw"], "ordered_objects": len(archived["objects"]),
            "member": member, "native_object_sha256": payload[-1], "symbol": SYMBOL.decode()}


def local_markers(archive, nm):
    assert file_sha(archive) == "3f9227bf53f1a00ed408ce650a62ff0e15f15baa5213a90728ee0539139bc3df"
    evidence = {}
    with zipfile.ZipFile(archive) as z:
        for role in "ANM":
            marker = V2 if role == "M" else HARD
            rows = {}
            for phase in PHASES:
                root = f"ruff-native-{role}/{phase}"
                unit = read_json(z, root + "/unit-evidence.json")["units"]["ruff_python_ast"]
                native = read_json(z, root + "/native.json")
                argv = unit["argv"]
                assert argv[argv.index("--crate-name") + 1] == "ruff_python_ast"
                assert "-Zohm-check-relink-inputs" in argv and "lto=off" in argv
                assert any(v.startswith("incremental=/") for v in argv)
                current = [r for r in native["rustcs"] if r["crate"] == "ruff_python_ast"]
                if role == "M" and phase.startswith("unchanged"):
                    assert not current
                else:
                    assert len(current) == 1 and current[0]["argv"] == argv and current[0]["terminal"] == [0]
                full = Path(unit["path"])
                assert full.parent == Path(argv[argv.index("--out-dir") + 1])
                suffix, = [v.removeprefix("extra-filename=") for v in argv if v.startswith("extra-filename=")]
                expected = "ruff_python_ast" + suffix
                assert full.name == expected + ".d"
                wire = z.read(root + "/ruff_python_ast.d")
                assert sha(wire) == unit["dep"]
                rules = {}
                for line in wire.splitlines():
                    if b": " in line:
                        path, inputs = line.split(b": ", 1)
                        name = Path(os.fsdecode(path)).name
                        if name in unit["outputs"]:
                            assert name not in rules
                            rules[name] = inputs.split()
                assert set(rules) == {expected + ".d", "lib" + expected + ".rlib", "lib" + expected + ".rmeta"}
                base = rules[expected + ".d"]
                assert not any(v.startswith(b"/dev/null/ohm-") for v in base)
                assert all(inputs == base + [marker] for name, inputs in rules.items() if name.endswith((".rlib", ".rmeta")))
                assert [line for line in wire.splitlines() if line.startswith(b"/dev/null/ohm-")] == [marker + b":"]
                rows[phase] = {"marker": marker.decode(), "depfile_sha256": sha(wire),
                               "arg_sha256": sha(b"\0".join(map(os.fsencode, argv))),
                               "actual_AST_rustcs": len(current), "ordinary_source_inputs": len(base)}
            evidence[role] = {"phases": rows, "real_edit_object": edit_member(z, f"ruff-native-{role}/edit", nm)}
    return evidence


def diagnostic_sites(archive, crate):
    assert file_sha(archive) == "c5d9db1bb28b5c82d447448a105cc2a82fed79c63a2fe5475103b33e54a11e0e"
    with tarfile.open(crate) as source:
        body = source.extractfile("compact_str-0.10.0/src/repr/mod.rs").read()
    lines = body.decode().splitlines()
    assert 'fn ensure_read' in lines[923] and 'core::arch::asm!(' in lines[938]
    assert [v.strip() for v in lines[939:942]] == ['"/* {value} */",', 'value = in(reg) value,', 'options(nomem, nostack),']
    outputs = {}
    with zipfile.ZipFile(archive) as z:
        for name, count in (("compact_str", 13), ("ruff_python_ast", 2)):
            member, = [n for n in z.namelist() if n.startswith("lowering/" + name + "/") and n.endswith(".ll.gz")]
            data = gzip.decompress(z.read(member))
            current = None
            calls = []
            debug = {}
            for line in data.splitlines():
                if line.startswith(b"define "):
                    current = re.search(rb"@([^ (]+)\(", line)[1]
                elif line.startswith(b"}"):
                    current = None
                elif re.match(rb"^!\d+ = ", line):
                    key, value = line.split(b" = ", 1)
                    debug[key[1:]] = value
                if b' asm ' in line:
                    assert current and b'asm sideeffect "/* ${0} */", "r,~{cc}"' in line
                    calls.append((current, re.search(rb"!dbg !(\d+)", line)[1]))
            assert len(calls) == count
            for owner, key in calls:
                assert b"line: 939," in debug[key]
                for _ in range(5):
                    if b'!DISubprogram(name: "ensure_read"' in debug[key]:
                        break
                    key = re.search(rb"scope: !(\d+)", debug[key])[1]
                else:
                    raise AssertionError("could not resolve assembly back to compact_str::repr::ensure_read")
                if name == "ruff_python_ast":
                    assert owner == SYMBOL
            outputs[name] = {"llvm_ir_sha256": sha(data), "asm_calls": len(calls),
                             "physical_owner_count": len({owner for owner, _ in calls})}
    return {"package_sha256":file_sha(crate), "package_source_sha256": sha(body),
            "line": 939, "function": "compact_str::repr::ensure_read", "IR": outputs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native_zip", type=Path)
    parser.add_argument("lowering_zip", type=Path)
    parser.add_argument("locked_compact_str", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    nm = shutil.which("llvm-nm-18") or shutil.which("llvm-nm")
    assert nm
    ordinary = local_markers(args.native_zip, nm)
    upstream = diagnostic_sites(args.lowering_zip, args.locked_compact_str)
    codegen = json.loads((HERE / "pilot/codegen.json").read_bytes())
    cgus = {slot: {role: item["compile_codegen_unit_calls"] for role,item in row["roles"].items()}
            for slot,row in codegen["cells"].items()}
    assert cgus == {slot: {"A": 95, "N": 95, "M": 1} for slot in ("01", "02")}
    data = {"measured_roles": "M in this cohort names the versioned V compiler",
            "one_per_crate_flag": "-Zohm-check-relink-inputs", "local_ordinary": ordinary,
            "supplementary_lowering_using_N": upstream, "pilot_actual_LLVM_calls": cgus,
            "reopened_native_zip_sha256": file_sha(args.native_zip), "separate_diagnostic_zip_sha256": file_sha(args.lowering_zip)}
    wire = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()
    if args.output:
        args.output.open("xb").write(wire)
    print(sha(wire))


if __name__ == "__main__":
    main()
