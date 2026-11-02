"""Build both authentic Ruff revisions into independent empty roots. No clocks or compiler changes."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-default-owner-pmu"))
import worker as w
sys.path.insert(0, str(HERE))
import capture
from acquire_dictionary import spec

c = w.c


def empty_roots():
    result = {}
    for n in ("build", "target"):
        p = w.WORK / n
        c.need(p.resolve(strict=True) == p and p.is_dir() and not any(p.iterdir()), "nonempty independent roots")
        info = p.stat()
        result[n] = [str(p), info.st_dev, info.st_ino, []]
    c.need(result["build"][1:3] != result["target"][1:3], "aliased independent roots")
    return result


def visit(branch):
    w.switch(branch)
    w.b.fresh_outputs()
    where = w.OUT / branch
    where.mkdir()
    c.save(where / "empty.json", empty_roots())
    before = w.source(branch, branch)
    c.save(where / "source.json", before)
    profiles = w.WORK / ("query-profile-" + branch)
    profiles.mkdir()
    env = w.ENV
    w.ENV = env | {
        "RUSTC_WRAPPER": str(HERE / "capture.py"), "PROFILE_SIGNED_SDK": str(w.b.SDK),
        "PROFILE_RECEIPT": str(where), "PROFILE_DIRECTORY": str(profiles),
        "PROFILE_RUFF_ROOT": str(w.REPO), "PROFILE_WORK_ROOT": str(w.WORK),
    }
    try:
        rows = w.invoke(where, c.CMD, 0)
    finally:
        w.ENV = env
    w.ownership.check_roots(rows, w.WORK)
    graph, products = w.ownership.graph(rows)
    c.need(products and all(not p["fresh"] for p in products), "cold Cargo build reused a local artifact")
    c.save(where / "cargo-graph.json.gz", graph)
    artifacts = [r for r in rows if r.get("reason") == "compiler-artifact" and r["target"]["name"] == "ruff_workspace" and r["target"]["kind"] == ["lib"]]
    owner, = artifacts
    c.need(not owner["fresh"] and Path(owner["target"]["src_path"]).samefile(w.REPO / "crates/ruff_workspace/src/lib.rs"), "Cargo owner")
    native = {f: {"sha256": c.sha(Path(f)), "bytes": Path(f).stat().st_size} for f in owner["filenames"]}
    c.need(any(f.endswith(".rlib") for f in native) and any(f.endswith(".rmeta") for f in native), "physical native owner library and metadata")
    c.save(where / "owner-products.json", {"cargo":owner, "files":native})
    args = [os.fsdecode(s) for s in (where/"owner.original.nul").read_bytes().rstrip(b"\0").split(b"\0")]
    ref = [os.fsdecode(s) for s in (HERE/"original-owner-A.nul").read_bytes().rstrip(b"\0").split(b"\0")]
    actual = capture.original_identity(args[1:])
    expected = capture.original_identity(ref[1:])
    c.save(where / "argv-comparison.json", {"original":expected, "actual":actual, "complete_argv_equality":args==ref})
    c.need(c.sha(HERE/"original-owner-A.nul") == spec["original_owner_sha256"], "enrolled original argv")
    if branch == "A":
        c.need(actual == expected, ("different original A rustc owner", [k for k in expected if actual[k]!=expected[k]]))
    c.need(c.read(where / "process.json")["owner_identity"] == actual, "actual compiler owner changed")
    w.native.observed(rows, branch, c.EXPECTED[branch], env, w.ROOT, w.REPO, w.WORK, where)
    after = w.source(branch, branch)
    c.need(before == after, "source changed during cold Cargo build")
    c.save(where/"complete.json", {"source":before["rev"], "tree":before["tree"], "ordinary_cargo_argv":c.CMD, "cargo_products":len(products)})


def main():
    c.need(not any(os.environ.get(k) for k in ("GH_TOKEN","GITHUB_TOKEN","RUSTC_WRAPPER","RUSTFLAGS","LD_PRELOAD")), "interposed runner")
    w.inputs()
    for branch in ("A", "B"):
        visit(branch)
    c.need(w.acquire.verify_sdk(w.b.SDK) == c.read(w.OUT / "sdk.json"), "signed native SDK changed")


if __name__ == "__main__":
    main()
