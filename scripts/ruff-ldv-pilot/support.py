"""Physical admission for the signed LLVM probe. All observation files are outside the Cargo roots."""

import ast
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
for directory in ("ruff-workspace-link-census", "ruff-workspace-remat", "ruff-workspace-option-edit",
                  "ruff-cgu-inputs", "ruff-repair-tables-pilot"):
    sys.path.insert(0, str(HERE.parent / directory))
import census
import e2e
import guards
import native
import physical
import replay
import study

need = replay.need
sha = replay.sha
put = replay.put
PLUGIN = "2f7bd28c5b34158babc46b0047d718e7caaec04eb0b57f757a47879846c2b34e"
LLVM = "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
WILD = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
SDK_LLVM = "lib/libLLVM.so.23.1-rust-1.99.0-beta"
EXEC = re.compile(r'^execve\(("(?:\\.|[^"\\])*"), (\[.*?\]), (.*)\)\s+= 0$')
REASONS = re.compile(rb"^OHM_LDV_REASONS((?: [0-9]+){8})$", re.M)


def setup_tools(here, sdk):
    here.mkdir()
    lib = here / "guard.so"
    lib.write_bytes(gzip.decompress((HERE / "guard.so.gz").read_bytes()))
    need(sha(lib) == PLUGIN and sha(sdk / SDK_LLVM) == LLVM, "different probe or LLVM")
    kit = HERE.parent / "ruff-workspace-link-census/wild-diagnostic"
    for src, exe, extra in ((HERE / "wrapper.c", "wrap", []), (HERE / "load.c", "load.so", ["-fPIC", "-shared", "-ldl"]),
                            (kit / "count.c", "count", []), (kit / "calibrate.c", "toy", ["-pthread"])):
        subprocess.run(["/usr/bin/cc", "-O2", "-Wall", src, *extra, "-o", here / exe], check=True)
    return {name: sha(here / name) for name in ("guard.so", "load.so", "wrap", "count", "toy")}


def calibrate(here, out):
    values = {}
    out.mkdir()
    for case in ("empty", "loop", "thread", "fork"):
        result = out / (case + ".json")
        subprocess.run([here / "count", result, here / "toy", here / "toy", case], check=True)
        v = json.loads(result.read_bytes())
        need(v["status"] == 0 and v["enabled"] == v["running"] > 0, ("unqualified PMU", case, v))
        values[case] = v["instructions"]
    for case in ("loop", "thread", "fork"):
        need(3_800_000 <= values[case] - values["empty"] <= 4_400_000, ("counter inheritance", values))
    put(out / "accepted.json", values)


def instrument(env, tools, sdk, arm, capture):
    need(not ({"LD_PRELOAD", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER"} & env.keys())
         and not any("TRUST" in key or key.startswith("QA_LDV") for key in env), "impure Cargo environment")
    if arm == "plain":
        return env.copy()
    need(arm in ("sham", "original", "guard"), ("unknown loader arm", arm))
    return {**env, "RUSTC_WRAPPER": str(tools / "wrap"), "QA_LDV_INJECT": "no" if arm == "sham" else "implicit",
            "QA_LDV_SHIM": str(tools / "load.so"), "QA_LDV_FRONTEND": str(sdk / "bin/rustc"),
            "QA_LDV_PLUGIN": str(tools / "guard.so"), "QA_LDV_LLVM": str(sdk / SDK_LLVM),
            "QA_LDV_RECORD": str(capture), "OHM_LDV_GUARD": arm}


def real_program(path, name):
    try:
        return Path(path).is_absolute() and Path(path).samefile(name)
    except FileNotFoundError:
        return False


def observed(dest, sdk, arm, include_env):
    tree = census.genealogy(dest / "trace")
    rusts = []
    depth = Counter()
    installs = 0
    for f in sorted((dest / "trace").glob("exec.[0-9]*")):
        pid = int(f.suffix[1:])
        for line in f.read_text(errors="strict").splitlines():
            if not line.startswith(("execve(", "execveat(")) or not re.search(r" = 0$", line):
                continue
            m = EXEC.fullmatch(line)
            need(m is not None, ("unsupported successful exec", line[:120]))
            exe, args = map(ast.literal_eval, m.groups()[:2])
            cc = real_program(exe, sdk / "bin/rustc") and "--crate-name" in args
            if include_env:
                env = dict(v.split("=", 1) for v in ast.literal_eval(m[3]))
                if "LD_PRELOAD" in env:
                    need(cc and arm in ("original", "guard") and env["LD_PRELOAD"] == env["QA_LDV_SHIM"],
                         ("leaked loader", exe, arm))
                    installs += 1
            if not real_program(exe, sdk / "bin/rustc"):
                continue
            name = args[args.index("--crate-name") + 1] if cc else ""
            probe = any(a in ("--print", "-vV", "-V", "--version") or a.startswith("--print=") for a in args)
            link_only = any(re.fullmatch(r"(?:-Z)?link-only(?:=.+)?", a) for a in args)
            role = "probe" if probe else ("link-only" if link_only else ("full" if cc else "other"))
            file = dest / "native" / (str(pid) + ".stderr")
            raw = file.read_bytes() if arm != "plain" and cc else b""
            complete = [[int(v) for v in line.split()] for line in REASONS.findall(raw)]
            reason_totals = [sum(row[i] for row in complete) for i in range(8)]
            if arm in ("sham", "plain"):
                need(b"OHM_LDV_" not in raw, ("unrequested activation", arm))
            if arm == "original":
                need(b"OHM_LDV_REASONS" not in raw and b"OHM_LDV_GUARD guard" not in raw, "wrong pass")
            if arm == "guard":
                need(b"OHM_LDV_GUARD original" not in raw, "wrong mode")
            rusts.append({"pid": pid, "name": name, "kind": role, "argv": args, "exec": exe, "selected": cc,
                      "diagnostic_file": str(file.name) if file.exists() else None,
                      "activation": raw.count(("OHM_LDV_GUARD " + arm).encode()),
                      "complete_reason_rows": len(complete), "reason_totals": reason_totals,
                      "unparsed_reason_prefixes": raw.count(b"OHM_LDV_REASONS") - len(complete)})
            depth[(role, name)] += 1
    if include_env and arm in ("original", "guard"):
        need(installs == sum(r["selected"] for r in rusts), ("missing physical injection", installs, len(rusts)))
    captured = {int(f.stem) for f in (dest / "native").glob("*.stderr")}
    need(captured == ({r["pid"] for r in rusts if r["selected"]} if arm != "plain" else set()),
         ("unmatched native stderr", captured))
    links = Counter()
    for obj in tree["linkers"]:
        owner = obj["owning_rustc"]
        label = "signed-Wild" if real_program(obj["path"], sdk / WILD) else obj["name"]
        links[(label, owner["owner"] if owner else "")] += 1
    summary = {"rustc": [list(k) + [v] for k, v in sorted(depth.items())],
               "linkers": [list(k) + [v] for k, v in sorted(links.items())]}
    put(dest / "kernel.json", {"tree": tree, "compilers": rusts, **summary})
    return rusts, summary


def visit(dest, work, repo, sdk, tools, arm, env, cmd, expected=0, score=False, include_env=False):
    dest.mkdir()
    for name in ("native", "trace"):
        (dest / name).mkdir()
    eff = instrument(env, tools, sdk, arm, dest / "native")
    argv = [str(x) for x in cmd]
    if score:
        proxy = shutil.which("cargo", path=eff["PATH"])
        need(argv[0] == "cargo" and proxy, "expected ordinary Cargo proxy")
        argv = [str(tools / "count"), str(dest / "pmu.json"), proxy, *argv]
    args = ["/usr/bin/strace", "-ff", "-qq", "-s", "131072", "-e", "trace=%process",
            "-o", str(dest / "trace/exec"), *(["-v"] if include_env else []), "--", *argv]
    put(dest / "command.json", {"ordinary": cmd, "actual": args, "environment": eff})
    code = guards.run(args, repo, eff, dest, work, dest, timeout=3000)
    need(code == expected, (str(dest), code, (dest / "outer.stderr").read_bytes()[-2000:]))
    count = None
    if score:
        pm = json.loads((dest / "pmu.json").read_bytes())
        need(os.waitstatus_to_exitcode(pm["status"]) == code and pm["enabled"] == pm["running"] > 0
             and pm["instructions"] > 0, ("rejected hardware count", pm))
        count = pm["instructions"]
    rusts, roster = observed(dest, sdk, arm, include_env)
    return count, rusts, roster
