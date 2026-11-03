"""Prove each measured arm grew its own cold A. Identical product hashes are valid."""

from pathlib import Path
import os, sys, time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CHECK, ENV, SRC, TARGET, CARGO, RUSTC, EV, read, save, require, sha


def validate(tree, compiler_id):
    root = tree["root"]
    require(tree["exits"][root] == 0, "cold Cargo exit")
    (launch,) = [v for v in tree["images"] if v["pid"] == root]
    require(launch["exe"] == str(CARGO), "cold Cargo image")
    calls = [v for v in tree["images"] if v["file"] == compiler_id]
    emits = [v for v in calls if any(x.startswith("--emit=") for x in v["argv"])]
    require(
        len(emits) > 100 and len({v["pid"] for v in emits}) == len(emits),
        "expected full cold dependency compilation",
    )
    images = {v["pid"]: v["exe"] for v in tree["images"]}
    cargo_children = []
    probes = []
    for x in emits:
        pid = x["pid"]
        parent = pid
        while parent in tree["births"]:
            parent = tree["births"][parent]
            if parent in images:
                break
        require(x["exe"] == x["argv"][0] == str(RUSTC) and parent in images, "cold rustc file/parent")
        if images[parent] == str(CARGO):
            require(
                x["argv"].count("--crate-name") == 1 and tree["exits"][pid] == 0,
                "cold authored Cargo rustc did not succeed",
            )
            cargo_children.append(pid)
        else:
            script = Path(images[parent])
            require(
                script.is_relative_to(TARGET / "debug/build")
                and script.name in ("build_script_build", "build-script-build")
                and tree["exits"][pid] in (0, 1),
                "unidentified emitted rustc compile probe",
            )
            probes.append({"pid": pid, "parent": parent, "script": str(script), "exit": tree["exits"][pid]})
    require(len(cargo_children) > 100, "missing original Cargo compiler tasks")
    return {
        "root_pid": root,
        "all_executed_images": len(tree["images"]),
        "all_emitting_rustcs": len(emits),
        "cargo_compilers": len(cargo_children),
        "build_script_probes": probes,
        "compiler_id": compiler_id,
        "exits": len(tree["exits"]),
    }


def capture(d):
    require(not TARGET.exists() and not d.exists(), "cold must start without any target")
    d.mkdir()
    fid = EV["file_id"](RUSTC)
    t = time.monotonic_ns()
    EV["capture"](d, CHECK, ENV, str(SRC), fid)
    end = time.monotonic_ns()
    ev = d / "kernel-events.json"
    proof = validate(EV["decode"](read(ev)), fid)
    save(
        d / "cold-processes.json",
        proof | {"start_ns": t, "end_ns": end, "events": sha(ev), "command": CHECK, "target_absent": True},
    )
    return proof
