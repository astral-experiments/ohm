"""Compile and qualify the event observer before installing or running the Ruff SDK."""
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def capture(argv, directory, name):
    with (directory / (name + ".stdout")).open("xb") as out, (directory / (name + ".stderr")).open("xb") as err:
        subprocess.run(argv, stdout=out, stderr=err, stdin=subprocess.DEVNULL, check=True, timeout=180)


def main(tools, out):
    if out.exists() or tools.exists() or os.getuid() == 0:
        raise ValueError("fixture requires empty private destinations and an unprivileged tracee")
    out.mkdir()
    shutil.copytree(HERE / "kernel", tools)
    cc = str(Path(shutil.which("cc")).resolve(strict=True))
    for name, args in (("observe", ["-O2", "-g0", "-Wall", "-Wextra", "-Werror", str(tools / "observe.c"), "-lcrypto"]),
                       ("fixture", ["-O2", "-Wall", "-Wextra", "-Werror", "-pthread", str(tools / "fixture.c")])):
        capture([cc, *args, "-o", str(tools / name)], out, "build-" + name)
    witness = tools / "witness"
    try:
        capture([sys.executable, "-IB", tools / "run_cases.py", witness], out, "run-cases")
        capture([sys.executable, "-IB", tools / "qualify.py", "cases", witness, "--physical"], out, "kernel-verdict")
    finally:
        preserved = out / "original"
        preserved.mkdir()
        if witness.is_dir():
            for member in sorted(witness.iterdir()):
                if member.is_symlink():
                    if member.name != "relative-exe" or os.readlink(member) != "/usr/bin/true":
                        raise ValueError(("unexpected native fixture symlink", str(member)))
                elif member.is_file():
                    shutil.copy2(member, preserved / member.name)
                else:
                    raise ValueError(("unexpected native fixture member", str(member)))
    native = json.loads((out / "kernel-verdict.stdout").read_bytes())
    assert native["live_physical_reopen"] is True and len(native["positive"]) == 6
    assert len(native["negative"]) == 2 and len(native["mutations_rejected"]) == 16 and native["long_argument_bytes"] == 98003
    capture([sys.executable, "-IB", HERE / "test_projection.py"], out, "projection")
    projection = json.loads((out / "projection.stdout").read_bytes())
    assert len(projection["refusals"]) == 12
    for name in ("observe", "fixture"):
        shutil.copy2(tools / name, out / (name + ".elf"))
    result = {"qualified": True, "cc": cc, "cc_sha256": digest(Path(cc)), "observer_sha256": digest(tools / "observe"),
              "originals": {p.name: digest(p) for p in sorted(preserved.iterdir())},
              "sources": {p.name: digest(p) for p in sorted((HERE / "kernel").iterdir()) if p.is_file()},
              "native": native, "ruff_projection": projection}
    with (out / "qualified.json").open("x") as f:
        json.dump(result, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")


if __name__ == "__main__":
    main(*map(Path, sys.argv[1:]))
