"""Repeat a kernel-witnessed compiler outside Cargo's native proof and ALL counted windows."""

import argparse
import fcntl
import gzip
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import read
from ingress import need, put, sha

EXTRAS = ["-Zprint-mono-items", "-Zhuman-readable-cgu-names", "-Zverbose-internals"]


def jobserver(value):
    m = re.fullmatch(r"-j --jobserver-fds=(\d+),(\d+) --jobserver-auth=\1,\2", value)
    need(
        m and len(set(m.groups())) == 2 and all(2 < int(s) < 256 for s in m.groups()),
        "unknown inherited Cargo jobserver",
    )
    return [int(s) for s in m.groups()]


def launch(spec):
    env = spec["environment"]
    slots = jobserver(env["CARGO_MAKEFLAGS"])
    # The measured cargo process exited. Reconstitute its -j4 anonymous pipe at its actual FD numbers.
    r, w = os.pipe()
    os.write(w, b"+++")
    held = [fcntl.fcntl(f, fcntl.F_DUPFD_CLOEXEC, max(slots) + 1) for f in (r, w)]
    os.close(r)
    os.close(w)
    for fd, slot in zip(held, slots):
        os.dup2(fd, slot, inheritable=True)
        os.close(fd)
    os.chdir(spec["cwd"])
    os.execve(spec["proxy"], [spec["proxy"], "+ohm", *spec["argv"][1:]], env)


def argv_special(row, out):
    original = row["argv"]
    args = original.copy()
    need(
        args.count("--out-dir") == 1
        and "--emit=dep-info,metadata,link" in args
        and all(x not in args for x in EXTRAS),
        "unknown ordinary compiler argv",
    )
    inc = [n for n, x in enumerate(args) if x.startswith("incremental=") or x.startswith("-Cincremental=")]
    need(len(inc) == 1 and args.count("--extern") == 3, "unexpected shared graph or external dep set")
    i = inc[0]
    args[i] = args[i].split("=", 1)[0] + "=" + str(out / "incremental")
    i = args.index("--out-dir") + 1
    args[i] = str(out / "native")
    external = {
        name: sha(Path(path))
        for m, a in enumerate(original)
        if a == "--extern"
        for name, path in [original[m + 1].split("=", 1)]
    }
    need(set(external) == {"anstyle", "memchr", "unicode_width"}, "missing true external input")
    return [*args, *EXTRAS], external


def acquisition(args):
    sys.path.insert(0, str(args.adapter))
    import workload as wl

    cell = args.cell
    w = args.work
    out = args.out
    sdk = args.sdk
    need(
        read(cell / "complete.json")["lane"] == "structural" and not (out / "raw").exists(),
        "mono needs closed ordinary proof",
    )
    # The sealed ordinary cells parked the warm edit+repaired tree here. Its dependencies are unchanged.
    original = w / "parked-empty"
    active = w / "slot"
    saved = w / "mono-displaced-empty-invalid"
    need(
        not original.is_symlink() and original.is_dir() and active.is_dir() and not saved.exists(),
        "unexpected prior slots",
    )
    active.rename(saved)
    shutil.copytree(original, active, symlinks=True)
    src = w / "source"
    seen = {}
    for phase, state in [("old", "old"), ("edit", "new")]:
        location = out / "raw" / phase
        location.mkdir(parents=True)
        scratch = w / ("mono-" + phase)
        scratch.mkdir()
        (scratch / "native").mkdir()
        wl.stage(src, location, "source-map", state)
        need(
            read(location / "sources" / state / "source.json")
            == read(cell / "sources" / state / "source.json"),
            "observation source differs",
        )
        native = read(cell / "raw" / phase / "native.json")
        (row,) = [x for x in native["compilers"] if x["name"] == "annotate_snippets"]
        args2, external = argv_special(row, scratch)
        captured = read(cell / "states" / phase / "state.json")["dependency_rmeta"]
        for name, value in external.items():
            item = captured[name]
            path = Path(item["path"])
            need(
                item["sha256"] == value == sha(cell / "objects" / value)
                and path.stat().st_size == item["bytes"]
                and any(v == name + "=" + str(path) for v in row["argv"])
                and item["compiler_opens"],
                "mono observation external input bytes differ from actual ordinary compile",
            )
        env = dict(s.split("=", 1) for s in row["environment"])
        need(
            len(env) == len(row["environment"])
            and not {"RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER", "GITHUB_TOKEN", "GH_TOKEN"} & env.keys(),
            "duplicate or uncontrolled environment",
        )
        need(
            row["cwd"] == str(src)
            and Path(row["path"]).samefile(sdk / "bin/rustc")
            and row["argv"][0] == row["path"]
            and row["driver_opens"],
            "ordinary native executable differs",
        )
        proxy = Path(shutil.which("rustc", path=env["PATH"]))
        need(proxy.samefile(args.proxies / "rustup"), "foreign rustup proxy")
        count = jobserver(env["CARGO_MAKEFLAGS"])
        spec = {
            "argv": args2,
            "environment": env,
            "cwd": row["cwd"],
            "proxy": str(proxy),
            "ordinary_path": row["path"],
            "ordinary_argv": row["argv"],
            "ordinary_trace_sha256": sha(cell / "raw" / phase / "strace.gz"),
            "ordinary_native_sha256": sha(cell / "raw" / phase / "native.json"),
            "ordinary_pid": row["pid"],
            "real_rustc_sha256": sha(sdk / "bin/rustc"),
            "jobserver": {"fds": count, "capacity": 4, "available_tokens": 3, "fresh_anon_pipe": True},
            "external_rmeta": external,
        }
        put(location / "intent.json", spec)
        p = subprocess.run(
            [sys.executable, "-IB", __file__, "child", location / "intent.json"],
            capture_output=True,
            timeout=300,
        )
        for name, data in [("stdout", p.stdout), ("stderr", p.stderr)]:
            (location / (name + ".gz")).write_bytes(gzip.compress(data, mtime=0))
        put(
            location / "terminal.json",
            {
                "status": p.returncode,
                "stdout": sha(location / "stdout.gz"),
                "stderr": sha(location / "stderr.gz"),
            },
        )
        need(
            p.returncode == 0
            and p.stdout
            and all(l.startswith(b"MONO_ITEM ") and b" @@ " in l for l in p.stdout.splitlines()),
            "emission failed or contains unexpected stdout",
        )
        need(b"jobserver" not in p.stderr.lower(), "inoperative inherited jobserver")
        seen[phase] = {
            "rows": len(p.stdout.splitlines()),
            "native": sha(location / "intent.json"),
            "source": sha(location / "sources" / state / "source.json"),
            "work_products": read(cell / "states" / phase / "state.json")["work_products"],
        }
    put(out / "acquired.json", seen)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "child":
        launch(read(Path(sys.argv[2])))
    else:
        p = argparse.ArgumentParser(description=__doc__)
        for key in ("work", "sdk", "cell", "adapter", "out", "proxies"):
            p.add_argument("--" + key, type=Path, required=True)
        acquisition(p.parse_args())
