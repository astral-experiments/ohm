"""Package only a committed, direct child of #337. The build worker reopens every source tree and byte."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CRATES, HERE, LEGACY, PARENT, git, need, save, sha

KEEP = ("bootstrap_flags", "source_epoch", "kit", "target", "signed_cargo", "source_factory")
ALLOWED = tuple("compiler/" + s + "/" for s in (*CRATES, "rustc_codegen_cranelift", "rustc_session", "rustc_interface"))
COALESCER = ("compiler/rustc_llvm/llvm-wrapper/OhmRegisterCoalescer.cpp",
             "compiler/rustc_llvm/llvm-wrapper/ohm-register-coalescer", "library", "src/bootstrap", "src/stage0", "src/llvm-project",
             "src/tools/cargo")


def freeze(src, candidate, dest):
    old = json.loads((LEGACY / "registration.json").read_bytes())
    need(re.fullmatch("[0-9a-f]{40}", candidate) and git(src, "rev-parse", "HEAD", candidate + "^").splitlines() == [candidate, PARENT],
         "only an explicitly frozen direct git child of #337 can be packaged")
    need(not (dest / "registration.json").exists() and not (dest / "candidate.bundle").exists(), "enrollment already exists")
    changes = {}
    for entry in git(src, "diff", "--name-status", "--no-renames", PARENT, candidate).splitlines():
        status, name = entry.split("\t")
        need(status in ("A", "M") and (name.startswith(ALLOWED) or name.startswith(("tests/run-make/", "tests/ui/", "tests/incremental/"))),
             ("unexpected source diff", status, name))
        changes[name] = {role: (git(src, "rev-parse", rev + ":" + name) if role == "C" or status == "M" else None)
                         for role, rev in (("P", PARENT), ("C", candidate))}
    need(all(any(n.startswith("compiler/" + c + "/") for n in changes) for c in CRATES), "missing required source owner")
    common = {}
    for path in COALESCER:
        values = git(src, "rev-parse", PARENT + ":" + path, candidate + ":" + path).splitlines()
        need(len(values) == 2 and values[0] == values[1], ("unrelated compiler configuration changed", path))
        common[path] = values[0]
    # The verified original #337 transport remains the first leg. This second one carries just its direct child.
    tmp = dest / "candidate.partial.bundle"
    need(not tmp.exists(), "previous partial transport exists")
    subprocess.run(["git", "-C", src, "bundle", "create", "--version=2", str(tmp), "HEAD", "^" + PARENT], check=True)
    need(git(src, "bundle", "list-heads", str(tmp)) == candidate + " HEAD" and tmp.stat().st_size < 4 << 20, "incomplete or excessive source bundle")
    git(src, "bundle", "verify", str(tmp))
    roles = {"P": old["roles"]["C"], "C": {"revision": candidate, "tree": git(src, "rev-parse", candidate + "^{tree}"),
                                           "compiler": git(src, "rev-parse", candidate + ":compiler")}}
    reg = {k: old[k] for k in KEEP}
    reg.update(schema="ohm-osp-source-1", roles=roles, changed_sources=changes, unchanged=common,
               bundle={"sha256": sha(tmp), "bytes": tmp.stat().st_size, "branch": "HEAD", "prerequisite": PARENT},
               previous_bundle_sha256=old["bundle"]["sha256"])
    tmp.rename(dest / "candidate.bundle")
    save(dest / "registration.json", reg)
    print(candidate, roles["C"]["tree"], sha(dest / "registration.json"))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("checkout", type=Path)
    p.add_argument("candidate")
    p.add_argument("--dest", type=Path, default=HERE)
    a = p.parse_args()
    freeze(a.checkout.resolve(strict=True), a.candidate, a.dest.resolve(strict=True))
