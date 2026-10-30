"""Calibrate, verify native behavior, and count a single prespecified matched pair."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ohm-aarch64-linux")]
import count_cycle
import qualify as q
import runtime as rt
import study_cgu
import tree_ir
from study import load, need, save, sha

GOLD = count_cycle.GOLDEN
ALLOCS = tuple(itertools.combinations(range(12), 6))
SEED = b"ohm:independent-cgus:3de892a4:ef23c9c3:whole-cargo-ir-v1"
SELECTION = ALLOCS[int.from_bytes(hashlib.sha256(SEED).digest(), "big") % len(ALLOCS)]


def order(index):
    return ("PC", "CP")[index + 2] if index < 0 else ("PC" if index in SELECTION else "CP")


def retire(name):
    for leaf in ("target", "shared", "cargo-home"):
        path = rt.WORK / leaf
        need(path.parent == rt.WORK and path.is_dir() and not path.is_symlink(), "unexpected private build directory")
        shutil.rmtree(path)


def verify_trial(result, role_dir):
    for kind in ("old", "new"):
        semantic = result["old" if kind == "old" else "cold"]
        want = GOLD[kind]
        need(len(semantic["native"]) == want["nobj"] and
             hashlib.sha256(json.dumps(semantic["native"]).encode()).hexdigest() == want["object_set"] and
             semantic["reader"] == want["reader"], "native products differ from independently admitted historical data")
    for phase, row in result["stages"].items():
        need(row["hard"] and not row["recheck"], "opaque assembly trigger was lost")
        if phase not in ("invalid", "empty-edited", "old-empty"):
            need(sorted(row["rustcs"]) == GOLD["changed_native_crates"], "ordinary rustc workload shifted")
        if phase != "invalid":
            native = load(role_dir / phase / "native.json")
            ast, = [r for r in native["rustcs"] if r["crate"] == "ruff_python_ast"]
            args = ast["argv"]
            opts = [v for k, v in zip(args, args[1:]) if k == "-C"]
            need("lto=off" in opts and sum(v.startswith("incremental=") for v in opts) == 1,
                 "missing actual developer settings on ordinary Ruff compilation")
        else:
            need(load(role_dir / phase / "verified.json")["error"] == "E0425", "invalid source escaped")


def block(index):
    need(-2 <= index < 12, "unknown pair")
    arms = order(index)
    output = {}
    for i, role in enumerate(arms):
        label = f"pair-{index}-arm-{i}-{role}"
        root = rt.LOG / label
        result = q.trial(label, role)
        save(root / "complete.json", result)
        need(result["measured"] is not None, f"settled counter failed: see {root}/counter-unavailable.json")
        verify_trial(result, root)
        counts = count_cycle.counted_cycle(root, role, result)
        counts["settled"] = load(root / "counter/verified.json")["Ir"]
        counts["edit-plus-repeat"] = counts["first-real-edit"] + counts["immediate-repeat"]
        output[role] = {"Ir": counts, "native": sha(root / "complete.json"),
                        "alloc": load(rt.LOG / (label + "-edit-cycle") / "allocated.json")}
    result = {"block": index, "order": arms, "arms": output, "qa": (rt.LOG / "qa-head").read_text().strip(),
              "manifest": load(rt.LOG / "received.json")["manifest"], "sources": [rt.PARENT, rt.CHILD],
              "ratios": {k: output["P"]["Ir"][k] / c for k,c in output["C"]["Ir"].items()}}
    save(rt.LOG / f"result-{index}.json", result)
    print("completed", index, arms, result["ratios"], flush=True)
    return result


def main():
    study_cgu.stable_selector()
    q.park = retire
    q.counter = tree_ir.measure
    q.prepare()
    tree_ir.calibrate()
    if sys.argv[1] == "pilot":
        rows = [block(i) for i in (-2, -1)]
        primary = ["first-real-edit", "immediate-repeat"]
        eligible = any(all(r["ratios"][e] > 2 for r in rows) for e in primary)
        save(rt.LOG / "pilot.json", {"eligible": eligible, "order": [r["order"] for r in rows], "primary": primary})
        with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
            print("eligible=" + str(eligible).lower(), file=stream)
    else:
        block(int(sys.argv[1]))


if __name__ == "__main__":
    main()
