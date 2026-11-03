"""Retain ordinary complete native histories before deciding whether the P3/Q3 trial may be priced."""

import gzip
import hashlib
import mmap
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import case
import elf_gate
import native_owner
import prefix
import qualification as q

STATES = {
    "settled-fixed": "fixed",
    "edited": "fixed",
    "reverse": "buggy",
    "repaired": "fixed",
    "fully-empty-fixed": "fixed",
    "fully-empty-buggy": "buggy",
}
MEM = case.BASE / "members"


def products(rows, destination):
    table = []
    for row in rows:
        item = [row["package_id"], row["target"]["name"], row["target"]["kind"], row["fresh"], []]
        for raw in row["filenames"]:
            p = Path(raw)
            key = case.sha(p)
            size = p.stat().st_size
            item[-1].append([raw, key, size])
            select = row["target"]["name"] in (
                "get_size2",
                "get_size_derive2",
                "portable_atomic",
                "salsa",
                "ruff_linter",
            )
            if select and (p.suffix in (".rmeta", ".so") or (p.suffix == ".rlib" and size < 2_000_000)):
                kept = MEM / (key + ".dependency.zst")
                if not kept.exists():
                    with kept.open("xb") as out:
                        subprocess.run(["zstd", "-q", "-3", "-c", p], stdout=out, check=True)
        table.append(item)
    (destination / "artifacts.json.gz").write_bytes(
        gzip.compress(json.dumps(table, separators=(",", ":")).encode(), compresslevel=4, mtime=0)
    )


def capture(label, role, env, traced=False):
    state = STATES[label]
    case.source(state)
    out = case.w.OUT / label
    argv = case.BUILD
    if traced:
        logs = case.w.OUT / (label + "-kernel")
        logs.mkdir()
        argv = [
            "strace",
            "-ff",
            "-qq",
            "-yy",
            "-s",
            "260000",
            "-e",
            "trace=execve,mmap",
            "-o",
            str(logs / "trace"),
            *argv,
        ]
    case.w.run(argv, env, out, timeout=3600)
    rows = q.typed_rows(out, True)
    assert len(rows) == case.REG["native_unit_count"]
    body = q.keep_native(rows, out, state, env)
    if traced:
        original = native_owner.roster(logs)
        case.save(logs / "kernel.json", original)
    (exe,) = [
        Path(t["executable"]) for t in rows if t["target"]["name"] == "ruff" and t["target"]["kind"] == ["bin"]
    ]
    with exe.open("rb") as fd, mmap.mmap(fd.fileno(), 0, access=mmap.ACCESS_READ) as mm:
        sections, programs, bid = elf_gate.image(mm)
        section_table = {
            k: {
                "header": list(v),
                "sha256": hashlib.sha256(memoryview(mm)[v[4] : v[4] + v[5]]).hexdigest() if v[1] != 8 else None,
            }
            for k, v in sections.items()
        }
        loads = [
            [list(ph), hashlib.sha256(memoryview(mm)[ph[2] : ph[2] + ph[5]]).hexdigest()]
            for ph in programs
            if ph[0] == 1
        ]
        case.save(
            out / "native-sections.json",
            dict(elf=body["sha256"], sections=section_table, loads=loads, build_id=mm[bid : bid + 32].hex()),
        )
    products(rows, out)
    native_owner.snapshot(out / "native-inputs", rows)
    ev = prefix.events(out)
    selected = [
        x["out_dir"]
        for x in ev
        if x.get("reason") == "build-script-executed" and "#tikv-jemalloc-sys@" in x["package_id"]
    ]
    assert len(selected) == 1
    body["native_out_dir"] = selected[0] + "/build"
    body["external_nonfresh"] = sorted(
        x["target"]["name"] for x in rows if prefix.locked_git.external(x["package_id"]) and not x["fresh"]
    )
    if traced:
        body["physical_selected"] = [
            o["crate"] for o in original["rustcs"] if o["crate"] in ("portable_atomic", "salsa")
        ]
        paths = [sh for sh in original["rustcs"] if sh["crate"] == "ruff_linter"]
        if label in ("edited", "reverse"):
            assert paths and all(x["driver"] == case.sha(native_owner.DRIVER) for x in paths)
    body["true_empty"] = all(not x["fresh"] for x in rows)
    case.save(out / "snapshot.json", body)
    print(role, label, body["sha256"], body["bytes"], len(body["external_nonfresh"]), flush=True)
    return body


def compare_all(snapshots):
    failures = []
    for role, data in snapshots.items():
        for state in ("buggy", "fixed"):
            keys = [(name, value["sha256"]) for name, value in data.items() if STATES[name] == state]
            if len({v for k, v in keys}) != 1:
                failures.append([role, state, keys])
        if data["fully-empty-fixed"]["sha256"] == data["fully-empty-buggy"]["sha256"]:
            failures.append([role, "old and edit images equal"])
        for name in ("fully-empty-fixed", "fully-empty-buggy"):
            if not data[name]["true_empty"]:
                failures.append([role, name, "reused compiled units"])
        for name in ("edited", "settled-fixed", "reverse"):
            row = data[name]
            if row["physical_selected"]:
                failures.append([role, name, "real external native owner", row["physical_selected"]])
            if row["external_nonfresh"]:
                failures.append([role, name, "external nonfresh", row["external_nonfresh"]])
            raw = case.BASE / role / name / "native-inputs/portable_atomic/rustc.d"
            if b"/dev/null/ohm-untracked-relink-inputs" in raw.read_bytes():
                failures.append([role, name, "hard portable-atomic marker"])
    cross = {}
    for name in ("fully-empty-buggy", "fully-empty-fixed"):
        a, b = [snapshots[r][name] for r in ("P", "C")]
        if a["sha256"] == b["sha256"]:
            cross[name] = {"identical": True, "sha256": a["sha256"]}
            continue
        try:
            with tempfile.TemporaryDirectory(dir=case.ROOT) as tmp:
                files = []
                for role, k in (("P", a), ("C", b)):
                    dst = Path(tmp) / role
                    with dst.open("xb") as stream:
                        subprocess.run(
                            ["zstd", "-qc", "-d", MEM / (k["sha256"] + ".elf.zst")], stdout=stream, check=True
                        )
                    assert case.sha(dst) == k["sha256"]
                    files.append(dst)
                cross[name] = elf_gate.compare(*files, a["native_out_dir"], b["native_out_dir"])
        except (ValueError, AssertionError, TypeError, OSError, subprocess.SubprocessError) as err:
            failures.append([name, "cross-role ELF", str(err)])
    return failures, cross


def role_history(role):
    env = case.env()
    kit = case.old.activate(role)
    (native_owner.DRIVER,) = (case.w.SDK / "lib").glob("librustc_driver-*.so")
    case.w.OUT = case.BASE / role
    case.w.OUT.mkdir()
    case.save(case.w.OUT / "sdk.json", kit)
    case.fresh_state()
    data = {}

    def run(label, trace=False):
        data[label] = capture(label, role, env, trace)

    def empty(label):
        assert not list(case.w.STATE.iterdir())
        assert not Path(env["CARGO_TARGET_DIR"]).exists() and not Path(env["CARGO_BUILD_BUILD_DIR"]).exists()
        case.save(case.w.OUT / (label+"-entry.json"), {"entries": [], "state": str(case.w.STATE),
                  "target": env["CARGO_TARGET_DIR"], "build": env["CARGO_BUILD_BUILD_DIR"]})
        run(label)

    empty("fully-empty-buggy")
    run("edited", True)
    run("settled-fixed", True)
    run("reverse", True)
    case.source("fixed")
    src = case.w.SRC / case.REG["path"]
    good = src.read_bytes()
    src.write_bytes(good + case.ERROR)
    try:
        invalid = case.w.OUT / "invalid"
        case.w.run(case.BUILD, env, invalid, 101, timeout=3600)
        q.typed_rows(invalid, False)
    finally:
        src.write_bytes(good)
    run("repaired")
    case.fresh_state()
    empty("fully-empty-fixed")
    return data


def main():
    snapshots = {}
    errors = []
    for role in "CP":
        try:
            snapshots[role] = role_history(role)
        except Exception as exc:
            import traceback

            errors.append([role, str(exc), traceback.format_exc()])
            case.save(case.BASE / "errors.json", errors)
    if all(set(rows) == set(STATES) for rows in snapshots.values()) and set(snapshots) == {"P", "C"}:
        failures, cross = compare_all(snapshots)
    else:
        failures, cross = [["incomplete full history"]], {}
    result = {
        "errors": errors,
        "refusals": failures,
        "cross_role": cross,
        "roles": snapshots,
        "scored": False,
        "pass": not failures and not errors,
    }
    case.save(case.BASE / "native-verdict.json", result)
    if not result["pass"]:
        raise ValueError("native prerequisites refused; all physical images and histories are retained")


if __name__ == "__main__":
    main()
