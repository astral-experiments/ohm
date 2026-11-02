"""Reuse the signed installer and restrict its authenticated diagnostic to one library."""

import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study as p

CGU = HERE.parent / "ruff-cgu-inputs"
BASE = HERE.parent / "ruff-default-owner-pmu"
sys.path.insert(0, str(CGU))
import acquire_cgu as previous
from acquire_cgu import acquire, c

PARENT = "ba324a8a8c5e0e57d12ca8a9a0d0031ea9aa6056"
FRESH = {
    "run": 41362345812,
    "job": 125015217590,
    "runner": "nsc-runner-tpsnua4bbr77g",
    "runner_id": 1401,
    "boot": "46ef1515-041e-4853-bc0c-efe20768ef30",
}
CAPTURE = "da8f226fd69d8268b5e9b64b586a84f3c2e5f26d096d3009dd26a3bbe970b34b"
BOTH = b'(!strcmp(owner, "ruff_linter") || !strcmp(owner, "ruff_workspace"))'
WORKSPACE = b'!strcmp(owner, "ruff_workspace")'


def capture_source():
    src = (CGU / "capture.c").read_bytes()
    p.need(p.sha(src) == CAPTURE and src.count(BOTH) == 1, "unreviewed native recorder")
    return src.replace(BOTH, WORKSPACE)


def compile_recorder(root):
    body = capture_source()
    source, exe = root / "workspace-cgu.c", root / "workspace-cgu"
    source.write_bytes(body)
    subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", source, "-o", exe], check=True)
    return exe


def inherited():
    previous.verify_inherited_sources()
    for line in (HERE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        p.need(c.sha(HERE.parents[1] / name) == digest, ("unreviewed QA source", name))


def acquire_release():
    inherited()
    previous.BRANCH, previous.JOB = p.BRANCH, p.JOB
    old = previous.check_fresh

    def distinct(state, excluded):
        state = old(state, excluded)
        p.need(all(state[k] != v for k, v in FRESH.items()), "reused prior codegen worker or boot")
        return state

    previous.check_fresh = distinct
    os.environ["EXCLUDED_BOOT_CUSTODY"] = (HERE / "excluded-boots.json").read_text()
    with previous.registration():
        acquire.main()


if __name__ == "__main__":
    if sys.argv[1:] == ["acquire"]:
        acquire_release()
    elif sys.argv[1:] == ["sources"]:
        inherited()
    elif len(sys.argv) == 3 and sys.argv[1] == "compile":
        compile_recorder(Path(sys.argv[2]))
    else:
        raise SystemExit("sources | acquire | compile NEW-OWNED-DIR")
