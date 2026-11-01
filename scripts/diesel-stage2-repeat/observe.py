"""Read an actual Eprintln child's workspace and Darwin process identity, outside the primary."""

import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intake import BIND, free_guard, need, sha, write
from identity import HEALTHY_A, PATCHED_B, Q
from escrow import safe_for_clone
from worker import check_clone


def graph_rows(cwd, inc, dest):
    if inc is None or not inc.is_dir():
        return []
    rows = []
    for f in sorted(inc.glob("diesel-*/s-*/dep-graph.bin")):
        if f.parent.name.endswith("-working"):
            continue
        need(
            f.is_file()
            and not f.is_symlink()
            and f.resolve().is_relative_to(cwd)
            and 0 < f.stat().st_size < 512 << 20,
            "unexpected graph",
        )
        st = f.stat()
        h = sha(f)
        dest.mkdir(exist_ok=True)
        target = dest / h
        if not target.exists():
            free_guard(dest, st.st_size)
            shutil.copyfile(f, target)
        end = f.stat()
        need(
            (st.st_dev, st.st_ino, st.st_size, st.st_ctime_ns)
            == (end.st_dev, end.st_ino, end.st_size, end.st_ctime_ns)
            and sha(target) == h,
            "graph changed in custody",
        )
        rows.append(
            {"path": str(f.relative_to(cwd)), "sha256": h, "size": st.st_size, "dev": st.st_dev, "ino": st.st_ino}
        )
    return rows


def physical(pid):
    buf = ctypes.create_string_buffer(4096)
    lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    result = lib.proc_pidpath(ctypes.c_int(pid), buf, ctypes.c_uint32(len(buf)))
    if result <= 0:
        return {"path": None, "errno": ctypes.get_errno()}
    name = Path(os.fsdecode(buf.value))
    st = name.stat()
    return {
        "path": str(name),
        "errno": 0,
        "dev": st.st_dev,
        "ino": st.st_ino,
        "size": st.st_size,
        "sha256": sha(name),
    }


def registered(argv, env):
    need(
        env["RUSTC_FORCE_RUSTC_VERSION"] == env["RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER"] == "rustc-perf"
        and "-Zincremental-verify-ich" in argv
        and [a for a in argv if a.startswith("-Zthreads=")][-1:] == ["-Zthreads=1"]
        and "--emit=dep-info,metadata,link" in argv
        and argv[argv.index("--crate-name") + 1] == "diesel"
        and argv[argv.index("--crate-type") + 1] == "lib"
        and "opt-level=3" in argv
        and "--edition=2021" in argv
        and "src/lib.rs" in argv,
        "different real Diesel rustc settings",
    )


def observe(phase, wrapper, pid, code, argv):
    root = Path(os.environ["OHM_DIESEL_WORK"])
    dest = Path(os.environ["OHM_DIESEL_RECORD"])
    prefix = dest / "events" / str(wrapper)
    cwd = Path.cwd().resolve()
    need(
        cwd.name.startswith(".tmp") and cwd.parent == Path(os.environ["TMPDIR"]).resolve(),
        "outside this focused private timing root",
    )
    registered(argv, os.environ)
    tool = Path(argv[0])
    need(tool.samefile(os.environ["OHM_DIESEL_RUSTC"]), "different compiler pathname")
    if phase == "running":
        # A fast failure may exit before proc_pidpath. Preserve that observation and let the
        # collector preserve its native failure before any success qualification.
        write(prefix / "running.json", {"pid": pid, "wrapper": wrapper, "process": physical(pid)})
        return
    state = {HEALTHY_A: "A", PATCHED_B: "B"}.get(sha(cwd / Q))
    need(state, "different source")
    incs = [Path(x.partition("=")[2]).resolve() for x in argv if x.startswith("incremental=")]
    need(not incs or incs == [cwd / "incremental-state"], "different incremental root")
    inc = incs[0] if incs else None
    rows = graph_rows(cwd, inc, dest / "graphs")
    record = {
        "monotonic_ns": time.monotonic_ns(),
        "pid": pid,
        "wrapper": wrapper,
        "code": code,
        "argv": argv,
        "cwd": str(cwd),
        "source": state,
        "source_sha256": sha(cwd / Q),
        "incremental": bool(inc),
        "graphs": rows,
    }
    if phase == "before":
        prefix.mkdir()
        need(
            not any(
                t in name.upper()
                for t in ("TOKEN", "PASSWORD", "SECRET", "CREDENTIAL", "AUTHORIZATION")
                for name in os.environ
            ),
            "unexpected credential in diagnostic environment",
        )
        record["environment"] = dict(os.environ)
        write(prefix / "before.json", record)
        if state == "B" and inc:
            need(rows, "patched B lacks previous graph")
            safe_for_clone(cwd)
            dst = root / "before-patched-B"
            need(not dst.exists(), "B already captured")
            free_guard(root, 1 << 30)
            subprocess.run(["/bin/cp", "-cRp", cwd, dst], check=True)
            check_clone(cwd, dst)
    else:
        need(phase == "after", "unknown observation")
        stderr = cwd / "eprintln"
        if stderr.is_file():
            shutil.copyfile(stderr, prefix / "rustc.stderr")
        profiles = {}
        for p in sorted(Path(os.environ["LLVM_PROFILE_FILE"]).parent.glob(f"*_{pid}.profraw")):
            profiles[p.name] = [p.stat().st_size, sha(p)]
            saved = dest / "native-profiles"
            saved.mkdir(exist_ok=True)
            os.link(p, saved / p.name)
        out = Path(argv[argv.index("--out-dir") + 1]).resolve()
        need(out.is_relative_to(cwd), "Diesel output outside observed timing root")
        record["outputs"] = {
            p.name: [p.stat().st_size, sha(p)]
            for p in out.glob("libdiesel-*")
            if p.is_file() and p.suffix in (".rlib", ".rmeta")
        }
        record["profile_files"] = profiles
        write(prefix / "after.json", record)


if __name__ == "__main__":
    observe(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5:])
