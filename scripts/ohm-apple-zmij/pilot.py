"""Short signed-release pilot. Neither a candidate compiler build nor any score is needed."""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from execs import ExecTrace
from measure import capture, fresh, installation, marked, native_rows, retire, typed
from native_inputs import run_archive_check
from objects import bag
from wrapper import WrapperTrace
from study import (
    ARGS,
    EDIT,
    EXPECTED,
    MISSING,
    RECHECK,
    RUFF,
    ZMIJ,
    ZMIJ_LIB,
    change_source,
    check_host,
    compress_bytes,
    digest,
    env_for,
    load,
    need,
    run,
    save,
    sha,
    source_values,
)

VECTOR = b'asm!("/*{:v}*/", inout(vreg) extended);'


def observer_probe(root):
    probe = root / "observer"
    probe.mkdir()
    clang = run(["xcrun", "--find", "clang"]).decode().strip()
    ld = Path(run(["xcrun", "--find", "ld"]).decode().strip())
    source = probe / "main.c"
    source.write_text("int main(void){return 29;}\n")
    output = probe / "linked"
    trace = ExecTrace()
    try:
        trace.ready()
        with tempfile.TemporaryFile() as o, tempfile.TemporaryFile() as e:
            code, rows = trace.command(
                [clang, str(source), "-o", str(output)], env=os.environ, cwd=probe, out=o, err=e
            )
        accepted = [r for r in rows if Path(r["path"]).is_file() and Path(r["path"]).samefile(ld)]
        need(
            code == 0 and len(accepted) == 1 and any(str(output) in r["argv"] for r in accepted),
            "lost actual Apple linker exec",
        )
        need(subprocess.run([str(output)], check=False).returncode == 29, "wrong native arm64 executable")
        need(
            any(Path(r["path"]).is_file() and Path(r["path"]).samefile(clang) for r in rows),
            "clang missing from native process group",
        )
        save(
            root / "receipts/observer.json",
            {"clang": sha(clang), "ld": sha(ld), "executable": sha(output), "exit": 29, "rows": rows},
        )
    finally:
        trace.close()


def causal(root, trace, output_label="causal"):
    work = root / "causal-work"
    work.mkdir(exist_ok=True)
    repo = root / "ruff"
    env = env_for(work, root / "signed")
    select = [x if x != "ruff_python_ast" else "zmij" for x in ARGS]
    original = None
    summary = {}
    for name in ("untouched", "omit-vector-comment", "restored"):
        fresh(work, root / "seed")
        (crate,) = (work / "cargo-home/registry").glob("cache/*/zmij-1.0.10.crate")
        need(sha(crate) == ZMIJ, "foreign crate")
        prefix = crate.parent.name
        src = work / "cargo-home/registry/src" / prefix / "zmij-1.0.10"
        if not src.is_dir():
            src.parent.mkdir(exist_ok=True, parents=True)
            with tarfile.open(crate) as archive:
                archive.extractall(src.parent, filter="data")
            (src / ".cargo-ok").write_text('{"v":1}')
        lib = src / "src/lib.rs"
        need(sha(lib) == ZMIJ_LIB and lib.read_bytes().count(VECTOR) == 1, "source or grammar mismatches")
        original = lib.read_bytes()
        if name == "omit-vector-comment":
            lib.write_bytes(original.replace(VECTOR, b"/* native isolated deletion control */"))
        rows = []
        for i, label in enumerate(("cold", "repeat-1", "repeat-2")):
            dest = root / "receipts" / output_label / name / label
            ret, o, e, events, sums = capture(select, repo, env, dest, trace)
            need(ret == 0, "signed native dependency build failed: " + e.decode(errors="replace")[-500:])
            arts, dirty, _, _ = typed(o, True)
            zs = [a for a in arts if a["target"]["name"] == "zmij"]
            need(
                len(zs) == 1 and Path(zs[0]["target"]["src_path"]).samefile(lib),
                "cargo used a different source",
            )
            roster = native_rows(events, root / "signed") if events is not None else None
            m, raw = marked(work)
            compress_bytes(dest / "zmij.dep.gz", raw)
            hard = name != "omit-vector-comment"
            count = int(hard or i == 0)
            need(
                (roster is None or roster["cargo"] in (None, 1) and roster["full"].count("zmij") == count)
                and zs[0]["fresh"] == (count == 0)
                and m["hard"] == hard
                and m["recheck"] == (not hard),
                "signed causal discriminator failed",
            )
            (rlib,) = [Path(p) for p in zs[0]["filenames"] if p.endswith(".rlib")]
            objects = {}
            for member in run(["ar", "t", str(rlib)]).decode().splitlines():
                if member.endswith(".o"):
                    body = run(["ar", "p", str(rlib), member])
                    need(
                        body[:8] == bytes.fromhex("cffaedfe0c000001") and body[12:16] == b"\1\0\0\0",
                        "not ARM64 Mach-O object",
                    )
                    need(member not in objects, "ambiguous archive")
                    objects[member] = digest(body)
            need(objects, "missing native archive objects")
            row = {
                "full": roster["full"] if roster else None,
                "linkers": roster["linkers"] if roster else None,
                "typed_zmij_dirty": not zs[0]["fresh"],
                "mark": m,
                "source": sha(lib),
                "objects": objects,
                "rlib": sha(rlib),
                "streams": sums,
            }
            save(dest / "verified.json", row)
            rows.append(row)
        need(len({r["rlib"] for r in rows}) == 1, "signed full crate changed within a stable source")
        summary[name] = rows
        retire(work)
    need(
        summary["untouched"][0]["rlib"] == summary["restored"][0]["rlib"],
        "restored full authentic crate differs",
    )
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("calibrate", "release"))
    p.add_argument("root", type=Path)
    a = p.parse_args()
    root = a.root.resolve()
    root.mkdir(exist_ok=True)
    receipts = root / "receipts"
    receipts.mkdir(exist_ok=True)
    if a.action == "calibrate":
        check_host(root)
        run(
            [
                sys.executable,
                "-IB",
                str(Path(__file__).with_name("run.py")),
                "calibrate",
                str(receipts / "calibration"),
            ],
            timeout=180,
        )
        try:
            observer_probe(root)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            save(
                receipts / "observer-unavailable.json",
                {
                    "reason": str(error)[:800],
                    "fallback": "separate unwrapped Cargo and diagnostic physical-compiler wrapper; linker census unavailable",
                },
            )
        return
    kernel = (receipts / "observer.json").exists()
    need(kernel or (receipts / "observer-unavailable.json").is_file(), "missing observer calibration")
    repo = root / "ruff"
    values = source_values(repo)
    change_source(repo, values, "old")
    trace = ExecTrace() if kernel else WrapperTrace()
    try:
        trace.ready()
        unwrapped = None
        if not kernel:
            causal(root, None, "causal-unwrapped")
            unwrapped = installation(root, "S", receipts / "ruff-unwrapped", invalid=True)
            uref = installation(root, "S", receipts / "ruff-unwrapped-clean", clean_only="new")
            for k in ("edit", "repeat-1", "repeat-2", "repair"):
                need(
                    bag(unwrapped[k]["reader"]) == bag(uref["clean-new"]["reader"]),
                    "unwrapped native clean failed",
                )
            run_archive_check(root, "S", None, "S-unwrapped")
            save(
                receipts / "unwrapped-core.json",
                {
                    "status": "passed",
                    "native_process_counts": None,
                    "reader": uref["clean-new"]["reader"],
                    "native_archive": sha(receipts / "native-input/S-unwrapped/terminal.json"),
                },
            )
        causes = causal(root, trace)
        current = installation(root, "S", receipts / "ruff-signed", trace=trace, invalid=True)
        clean = installation(root, "S", receipts / "ruff-signed-clean", trace=trace, clean_only="new")
        old = installation(root, "S", receipts / "ruff-signed-clean-old", trace=trace, clean_only="old")
        run_archive_check(root, "S", trace)
        if unwrapped:
            for phase, r in current.items():
                other = unwrapped[phase]
                need(
                    r["dirty"] == other["dirty"]
                    and r["roster"] == other["roster"]
                    and r["codes"] == other["codes"]
                    and (
                        r["reader"] is None
                        or r["reader"]["value"] == other["reader"]["value"]
                        and bag(r["reader"]) == bag(other["reader"])
                    ),
                    "observing physical rustc changed ordinary product or roster",
                )
        need(
            current["cold"]["reader"]["value"] == old["clean-old"]["reader"]["value"] == EXPECTED["old"],
            "base reader",
        )
        for k in ("edit", "repeat-1", "repeat-2", "repair"):
            need(
                current[k]["reader"]["value"] == clean["clean-new"]["reader"]["value"] == EXPECTED["new"],
                "changed reader",
            )
            need(
                bag(current[k]["reader"]) == bag(clean["clean-new"]["reader"]),
                "incremental Mach-O objects differ from clean",
            )
        save(
            receipts / "mechanism.json",
            {
                "status": "passed",
                "scores": 0,
                "ruff": [RUFF, EDIT],
                "signed_release": sha(receipts / "release.json"),
                "calibration": sha(receipts / "calibration/result.json"),
                "observer": sha(receipts / ("observer.json" if kernel else "observer-unavailable.json")),
                "observer_scope": trace.kind,
                "native_phases": {k: v["native"] for k, v in current.items()},
                "signed_verdicts": {
                    k: v["reader"]["value"] if v["reader"] else v["codes"] for k, v in current.items()
                },
                "causal_counts": {
                    name: [r["full"].count("zmij") for r in rows] for name, rows in causes.items()
                },
                "independent_native_readers": [old["clean-old"]["reader"], clean["clean-new"]["reader"]],
                "native_archive": sha(receipts / "native-input/S/terminal.json"),
            },
        )
    finally:
        trace.close()
        change_source(repo, values, "old")


if __name__ == "__main__":
    main()
