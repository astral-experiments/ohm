"""Off-clock attribution of a nonfresh registry native library on the unmodified historical CLI build."""

from pathlib import Path
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import case
import qualification as q
import prefix

REG = json.loads((HERE / "native-owner.json").read_bytes())
B = case.BASE / "native-owner"
HASH = lambda v: hashlib.sha256(v).hexdigest()
DRIVER = None


def file_record(p):
    stat = p.stat()
    return {
        "dev": stat.st_dev,
        "ino": stat.st_ino,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "mode": stat.st_mode,
        "bytes": stat.st_size,
        "sha256": case.sha(p),
    }


def snapshot(path, rows):
    path.mkdir(exist_ok=True)
    result = {}
    for crate in ("portable_atomic", "salsa"):
        (row,) = [r for r in rows if r["target"]["name"] == crate and r["target"]["kind"] == ["lib"]]
        (rlib,) = [Path(n) for n in row["filenames"] if n.endswith(".rlib")]
        unit = rlib.parent.parent
        (dep,) = rlib.parent.glob(crate + "-*.d")
        fn = unit / "fingerprint" / ("dep-lib-" + crate)
        key = path / crate
        key.mkdir()
        raw = dep.read_bytes()
        translated = fn.read_bytes()
        (key / "rustc.d").write_bytes(raw)
        (key / "cargo.bin").write_bytes(translated)
        for name in ("lib-" + crate + ".json", "ohm-message-provenance-lib-" + crate):
            f = fn.parent / name
            if f.is_file():
                shutil.copyfile(f, key / name)
        result[crate] = {
            "row": row,
            "outputs": {str(f): file_record(f) for f in [*map(Path, row["filenames"]), dep, fn]},
            "dep_info": file_record(dep),
            "translated": file_record(fn),
            "reports_hard": b"/dev/null/ohm-untracked-relink-inputs" in raw,
        }
    case.save(path / "physical.json", result)
    return result


def cli(rows, env):
    (row,) = [r for r in rows if r["target"]["name"] == "ruff" and r["target"]["kind"] == ["bin"]]
    exe = Path(row["executable"])
    res = {}
    for name, decorator, expr, old, _ in q.PROBES:
        source = f"import attr\n@{decorator}\nclass Example:\n    value: list[int] = {expr}\n"
        proc = subprocess.run(
            [
                exe,
                "check",
                "--isolated",
                "--no-cache",
                "--select",
                "RUF009",
                "--output-format=json",
                "--stdin-filename=case.py",
                "-",
            ],
            cwd=case.w.SRC,
            env=env,
            input=source.encode(),
            capture_output=True,
            timeout=30,
        )
        msgs = json.loads(proc.stdout)
        assert proc.returncode == old and proc.stderr == b"" and [m["code"] for m in msgs] == ["RUF009"] * old
        res[name] = {"exit": old, "stdout": proc.stdout.decode(), "source": source}
    return {"sha256": case.sha(exe), "bytes": exe.stat().st_size, "runtime": res}


def roster(traces):
    all_exec = []
    owned = []
    alias = {str(case.w.SDK / "bin/rustc"), str(case.ROOT / "rustup/toolchains/ohm/bin/rustc")}
    for f in sorted(traces.glob("trace.*")):
        raw = f.read_bytes()
        ls = raw.decode().splitlines()
        hits = []
        for s in ls:
            if not s.startswith('execve("') or not s.endswith(") = 0"):
                continue
            binary, argvraw = s[8:].split('", [', 1)
            argv, _ = json.JSONDecoder().raw_decode("[" + argvraw)
            all_exec.append([int(f.name.split(".")[1]), binary, HASH(s.encode())])
            if binary in alias and "--crate-name" in argv and "--out-dir" in argv:
                maps = [
                    x
                    for x in ls
                    if x.startswith("mmap(")
                    and "PROT_EXEC" in x
                    and "<" + str(DRIVER) + ">" in x
                    and re.search(r" = 0x[0-9a-f]+$", x)
                ]
                assert maps
                hits.append(
                    {
                        "pid": int(f.name.split(".")[1]),
                        "crate": argv[argv.index("--crate-name") + 1],
                        "exe": binary,
                        "argv": argv,
                        "driver": case.sha(DRIVER),
                        "maps": maps,
                    }
                )
        assert len(hits) <= 1
        owned.extend(hits)
        with (f.parent / (f.name + ".gz")).open("xb") as out:
            out.write(gzip.compress(raw, compresslevel=3, mtime=0))
        f.unlink()
    return {"execs": all_exec, "rustcs": owned}


def observe_proc(stop, found):
    actual = case.w.SDK / "bin/rustc"
    while not stop.is_set():
        for directory in Path("/proc").iterdir():
            if not directory.name.isdigit() or directory.name in found:
                continue
            try:
                if not (directory / "exe").samefile(actual):
                    continue
                cmd = (directory / "cmdline").read_bytes().split(b"\0")[:-1]
                if b"--crate-name" not in cmd:
                    continue
                crate = cmd[cmd.index(b"--crate-name") + 1].decode()
                if crate not in ("portable_atomic", "salsa"):
                    continue
                maps = [
                    ln
                    for ln in (directory / "maps").read_text().splitlines()
                    if str(DRIVER) in ln and ln.split()[1] == "r-xp"
                ]
                if not maps:
                    continue
                p = directory
                chain = []
                for _ in range(32):
                    status = (p / "status").read_text()
                    p = Path("/proc") / re.search(r"^PPid:\s*(\d+)", status, re.M)[1]
                    if int(p.name) < 2:
                        break
                    binary = (p / "exe").resolve(strict=True)
                    parent = (p / "cmdline").read_bytes().split(b"\0")[:-1]
                    chain.append(
                        {"pid": int(p.name), "exe": str(binary), "argv": [os.fsdecode(c) for c in parent]}
                    )
                    if binary.samefile(case.w.SDK / "bin/cargo") and b"build" in parent and b"ruff" in parent:
                        found[directory.name] = {
                            "crate": crate,
                            "argv": [os.fsdecode(c) for c in cmd],
                            "driver_mapping": maps,
                            "driver": case.sha(DRIVER),
                            "cargo_ancestry": chain,
                        }
                        break
            except (OSError, ValueError, IndexError, AttributeError):
                pass
        stop.wait(0.004)


def main():
    global DRIVER
    B.mkdir()
    kit = case.old.activate("C")
    assert kit["driver"] == REG["C_driver"] and kit["cargo"] == REG["common_cargo"]
    (DRIVER,) = (case.w.SDK / "lib").glob("librustc_driver-*.so")
    case.save(B / "sdk.json", kit)
    env = case.env()
    case.fresh_state()
    case.source("buggy")
    phases = {}
    for phase, cmd in [("check", case.CHECK), ("build", case.BUILD)]:
        root = B / ("dependency-seed-" + phase)
        case.w.run(cmd, env, root, timeout=2400)
        q.typed_rows(root, True)
        phases[phase] = root
    seed = q.typed_rows(phases["build"], True)
    initial = snapshot(B / "seed", seed)
    initial_cli = cli(seed, env)
    locked = tomllib.loads((case.w.SRC / "Cargo.lock").read_text())
    capture = prefix.Prefix(
        case.w.STATE, case.w.SRC, case.ROOT / "cargo", B / "registry-prefix", locked, phases
    )
    capture.fresh("enter-native")
    case.source("buggy")
    before = snapshot(B / "before-first", seed)
    assert before == initial
    traces = B / "observed"
    traces.mkdir()
    first = B / "first"
    case.w.run(
        [
            "/usr/bin/strace",
            "-ff",
            "-qq",
            "-yy",
            "-s",
            "260000",
            "-e",
            "trace=execve,mmap",
            "-o",
            str(traces / "trace"),
            *case.BUILD,
        ],
        env,
        first,
        timeout=2400,
    )
    raw = roster(traces)
    case.save(B / "kernel.json", raw)
    rows = q.typed_rows(first, True)
    after = snapshot(B / "after-first", rows)
    first_cli = cli(rows, env)
    stop = threading.Event()
    found = {}
    observer = threading.Thread(target=observe_proc, args=(stop, found))
    observer.start()
    second = B / "untraced-repeat"
    try:
        case.w.run(case.BUILD, env, second, timeout=2400)
    finally:
        stop.set()
        observer.join()
        case.save(B / "untraced-processes.json", found)
    repeats = q.typed_rows(second, True)
    last = snapshot(B / "after-repeat", repeats)
    last_cli = cli(repeats, env)
    subject = [x for x in raw["rustcs"] if x["crate"] == "portable_atomic"]
    (owner,) = subject
    assert any(v["crate"] == "portable_atomic" for v in found.values())
    assert (
        "--emit=dep-info,metadata,link" in owner["argv"]
        and "-Zohm-check-relink-inputs" in owner["argv"]
        and set(['feature="default"', 'feature="fallback"']) <= set(owner["argv"])
    )
    compiled = [x for x in owner["argv"] if "/portable-atomic-1.11.0/src/lib.rs" in x]
    assert (
        len(compiled) == 1
        and Path(compiled[0]).resolve()
        == Path(initial["portable_atomic"]["row"]["target"]["src_path"]).resolve()
    )
    hard = bytes.fromhex(REG["hard_translated_bytes"])
    assert all(
        (B / n / "portable_atomic/cargo.bin").read_bytes() == hard
        for n in ("seed", "before-first", "after-first", "after-repeat")
    )
    assert all(
        (B / n / "salsa/cargo.bin").stat().st_size == 14
        for n in ("seed", "before-first", "after-first", "after-repeat")
    )
    assert all(
        report["portable_atomic"]["reports_hard"] and not report["salsa"]["reports_hard"]
        for report in (initial, before, after, last)
    )
    expected = REG["original_prefix"]["native-portable"]
    original_hash = next(v[1] for k, v in expected.items() if k.endswith(".d"))
    raw_hash = initial["portable_atomic"]["dep_info"]["sha256"]
    dep_external = sorted(
        r["target"]["name"] for r in rows if prefix.locked_git.external(r["package_id"]) and not r["fresh"]
    )
    report = {
        "prior": REG["worker"],
        "first_source_argv": owner,
        "traced_nonfresh_external": dep_external,
        "traced_true_owners": [x["crate"] for x in raw["rustcs"]],
        "untraced_selected": {k: v["crate"] for k, v in found.items()},
        "original_rustc_d_sha256": original_hash,
        "current_rustc_d_sha256": raw_hash,
        "original_rustc_d_exact": raw_hash == original_hash,
        "same_3_cli": initial_cli == first_cli == last_cli,
        "native": [initial_cli, first_cli, last_cli],
        "hard_marker_sha256": HASH(hard),
    }
    case.save(B / "outcome.json", report)
    assert dep_external == ["portable_atomic", "salsa"] and initial_cli == first_cli == last_cli
    print(
        "Real native owners",
        report["traced_true_owners"],
        "settled",
        report["untraced_selected"],
        "original raw dep-info byte-exact",
        report["original_rustc_d_exact"],
    )


if __name__ == "__main__":
    main()
