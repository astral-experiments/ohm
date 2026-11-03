"""Run the original Ron argv with the captured Cargo pipe ABI on new private fds."""

import argparse
import array
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import termios

HERE = Path(__file__).resolve().parent


def exercise(work):
    inv = json.loads((HERE / "inputs/invocation.json").read_bytes())
    abi = inv["raw_jobserver"]
    assert abi["abi_fds"] == [5, 7] and abi["private_tokens"] == 3
    base = work / "input"

    def at(s):
        return s.replace("$ROLE", str(base))

    env = {
        k: os.environ[k] for k in ("HOME", "USER", "PATH", "LANG") if k in os.environ
    }
    env.update({k: at(v) for k, v in inv["compiler_env"].items()})
    env.update(
        CARGO_MAKEFLAGS=abi["flags"],
        RUSTUP_HOME=str(work / "rustup"),
        TMPDIR=str(work / "tmp"),
    )
    argv = list(map(at, inv["argv"]))
    out = work / "jobserver-history"
    out.mkdir()
    products = out / "output"
    products.mkdir()
    argv[argv.index("--out-dir") + 1] = str(products)
    rows = {}
    # This standalone process is solely a pipe provider to its child. Preserve
    # existing descriptors by refusing if the requested ABI slots are in use.
    for fd in abi["abi_fds"]:
        try:
            os.fstat(fd)
        except OSError:
            continue
        raise RuntimeError(f"FD {fd} is already occupied")
    r, w = os.pipe()
    spare = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 50) for fd in (r, w)]
    os.close(r)
    os.close(w)
    for source, dest in zip(spare, abi["abi_fds"]):
        os.dup2(source, dest, inheritable=True)
        os.close(source)
    a, b = [os.fstat(fd) for fd in abi["abi_fds"]]
    assert stat.S_ISFIFO(a.st_mode) and (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    assert os.write(7, b"+++") == 3
    for name in ("regular", "traced"):
        phase = out / name
        phase.mkdir()
        cmd = argv
        if name == "traced":
            cmd = [
                "strace",
                "-ff",
                "-qq",
                "-yy",
                "-s",
                "256",
                "-o",
                str(phase / "sys"),
                "-e",
                "trace=%file,%desc,%memory",
                "--",
                *argv,
            ]
        with (phase / "stdout").open("xb") as stdout, (phase / "stderr").open(
            "xb"
        ) as stderr:
            result = subprocess.run(
                cmd,
                cwd=at(inv["cwd"]),
                env=env,
                pass_fds=(5, 7),
                stdout=stdout,
                stderr=stderr,
                timeout=150,
            )
        assert result.returncode == 0, (phase / "stderr").read_text()[:600]
        available = array.array("i", [0])
        fcntl.ioctl(5, termios.FIONREAD, available, True)
        assert available[0] == 3
        files = {}
        for p in products.iterdir():
            with p.open("rb") as f:
                files[p.suffix] = hashlib.file_digest(f, "sha256").hexdigest()
            p.rename(phase / p.name)
        assert set(files) == {".d", ".rlib", ".rmeta"}
        rows[name] = files
    assert (
        rows["regular"][".d"] == rows["traced"][".d"]
        and rows["regular"][".rlib"] == rows["traced"][".rlib"]
    )
    original = json.loads((work / "phases/regular/result.json").read_bytes())["outputs"]
    assert rows["regular"][".rlib"] == next(
        v for k, v in original.items() if k.endswith(".rlib")
    )
    logs = "\n".join(p.read_text() for p in (out / "traced").glob("sys.*"))
    assert f"pipe:[{a.st_ino}]" in logs and any(
        "mmap(" in l and "libserde_core-" in l for l in logs.splitlines()
    )
    summary = {
        "cargo_flags": abi["flags"],
        "abi": [5, 7],
        "pipe_device": a.st_dev,
        "pipe_inode": a.st_ino,
        "returned_tokens": 3,
        "rows": rows,
    }
    (out / "result.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n"
    )
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--work",
        type=Path,
        required=True,
        help="Completed private replay from replay.py",
    )
    print(
        json.dumps(exercise(p.parse_args().work.resolve(strict=True)), sort_keys=True)
    )
