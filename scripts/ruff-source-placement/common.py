"""Bindings shared by the one source factory and the independent Ruff workers."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
LEGACY = SCRIPTS / "ruff-ldv-physical-stage"
WORKFLOW = SCRIPTS / "ruff-ldv-physical-workflow"
PARENT = "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5"
REPO = "astral-experiments/ohm"
BRANCH = "charlie/qa-ruff-workspace-link-census-20261102"
HOST = "x86_64-unknown-linux-gnu"
CRATES = ("rustc_middle", "rustc_incremental", "rustc_codegen_ssa", "rustc_llvm", "rustc_codegen_llvm")
SCORED = ("old", "new", "unchanged")
sys.path.insert(0, str(LEGACY))
import capsule

need, sha, save = capsule.need, capsule.sha, capsule.save


def git(where, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", where, *args], text=True
    ).strip()


def source_binding():
    reg = json.loads((HERE / "registration.json").read_bytes())
    previous = json.loads((LEGACY / "registration.json").read_bytes())
    need(reg["roles"]["P"] == previous["roles"]["C"] and reg["roles"]["P"]["revision"] == PARENT,
         "requires the actual #337 compiler as parent")
    need(all(reg[k] == previous[k] for k in ("bootstrap_flags", "source_epoch", "kit", "target", "signed_cargo", "source_factory")),
         "changed bootstrap, archived LLVM or shipped native tools")
    need(all(any(p.startswith("compiler/" + c + "/") for p in reg["changed_sources"]) for c in CRATES),
         "experiment is missing a participating compiler crate")
    need(reg["roles"]["C"]["revision"] != PARENT and re.fullmatch("[0-9a-f]{40}", reg["roles"]["C"]["revision"]),
         "missing frozen direct child")
    return reg


def enrollment():
    need(os.environ["GITHUB_REPOSITORY"] == REPO and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
         and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
         and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
         and git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
         "not the reviewed immutable QA head")
    spec = json.loads((HERE / "protocol.json").read_bytes())
    for r, tree in spec["inherited_trees"].items():
        need(git(HERE, "rev-parse", "HEAD:scripts/" + r) == tree, ("changed inherited evidence code", r))
    reg = source_binding()
    need(reg["roles"]["C"]["revision"] == os.environ["PLACEMENT_SOURCE"],
         "different candidate from the explicit dispatch")
    cap = HERE / "candidate.bundle"
    need(cap.is_file() and not cap.is_symlink() and cap.stat().st_size == reg["bundle"]["bytes"]
         and sha(cap) == reg["bundle"]["sha256"], "source bundle content differs")
    capsule.HERE, capsule.REG = HERE, reg
    return reg
