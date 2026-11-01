"""Exercise the original-capture path using authenticated external inputs without invoking rustc."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identity import ERROR, HEALTHY_A, HERE, PATCHED_B, Q, diagnosis, extra, need, sha, trace, write
from worker import decode, first


def run(workdir, corpus, baseline_graph, log, output):
    published = json.loads((HERE / "recorded.json").read_bytes())
    need(sha(log) == published["original_log_sha256"], "not the authenticated original Darwin log")
    full = log.read_text()
    training = trace(full)
    failed = diagnosis(full, training)
    source = (corpus / Q).read_bytes()
    need(hashlib.sha256(source).hexdigest() == HEALTHY_A, "not the actual pinned Diesel 2.2.10")
    line = b"        methods::DistinctDsl::distinct(self)"
    need(source.count(line) == 1, "invalid source intervention")
    changed = source.replace(line, b'        println!("testing");\n' + line)
    need(hashlib.sha256(changed).hexdigest() == PATCHED_B, "not the actual patched source")
    graph = baseline_graph.read_bytes()
    # This offset is source-authenticated for exactly the two native subjects in tiny-eager-control.
    need(
        len(graph) == 21423
        and hashlib.sha256(graph).hexdigest() == "2b238171ac989db97480711a9b731eebb6908e6468102e46ecb60f0b814caef8",
        "different isolated GNU native writer",
    )
    patched = bytearray(graph)
    patched[254] ^= 2
    need(
        hashlib.sha256(patched).hexdigest() == "be8ed978277c726af389af81c8bda4b435a0689a368b064080a00b216f39b8e5",
        "different one-bit intervention",
    )
    with tempfile.TemporaryDirectory(dir=workdir) as temporary:
        root = Path(temporary).resolve()
        w, tmp = root / "work", root / "tmp"
        w.mkdir()
        tmp.mkdir()
        r = w / "source/reports/diesel-pgo"
        r.mkdir(parents=True)
        old_work = str(Path(training["build"]).parents[2])
        old_tmp = Path(failed["cwd"]).parent
        from_tmp = Path(failed["inc"]).parent.parent
        rebound = full.replace(str(old_tmp), str(tmp)).replace(str(from_tmp), str(tmp)).replace(old_work, str(w))
        # Only relocate physical temp and work prefixes for this local control.
        d = diagnosis(rebound, trace(rebound))
        cwd = Path(d["cwd"])
        (cwd / Q).parent.mkdir(parents=True)
        (cwd / Q).write_bytes(changed)
        (cwd / "eprintln").write_text(ERROR + "\n")
        need(Path(d["inc"]).resolve() == cwd.resolve() / "incremental-state", "invalid mock location")
        Path(extra(d["argv"], "--out-dir")).mkdir(parents=True)
        provider = Path(extra(d["argv"], "--extern").split("=", 1)[1])
        provider.parent.mkdir(parents=True)
        provider.write_bytes(b"synthetic exogenous provider; never executed")
        inc = cwd / "incremental-state/diesel-fixture"
        for name, body in [("s-original-full", graph), ("s-original-failed", patched)]:
            x = inc / name
            x.mkdir(parents=True)
            (x / "dep-graph.bin").write_bytes(body)
        current = inc / "s-working-copy-working"
        current.mkdir()
        os.link(inc / "s-original-failed/dep-graph.bin", current / "dep-graph.bin")
        (r / "original-opt-dist.log").write_text(rebound)
        write(r / "primary.json", {"code": 1, "stopped_after_completed_rustc_profiles": False})
        first(w, r)
        decode(w, r)
        own = json.loads((r / "before-replay.json").read_bytes())
        decoded = [json.loads(p.read_bytes()) for p in sorted(r.glob("original-graph-decode.*.json"))]
        need(
            len(decoded) == 2
            and sum(d["eager_headers"].get("all_node_headers_passed", False) for d in decoded) == 1,
            "valid/invalid graph discrimination failed",
        )
        (rejected,) = [d["eager_headers"] for d in decoded if d["eager_headers"].get("assertion")]
        need(
            rejected["failure"] == "duplicate node index" and rejected["offset"] == 293 and rejected["index"] == 0,
            "wrong first eager rejection",
        )
        need(
            len(own["graphs"]) == 3
            and own["failed_timing_root"]
            and own["original_workspace"]["sha256"] == sha(r / "original-workspace.tar.gz"),
            "first custody did not seal both graphs",
        )
        result = {
            "control": "rebound authentic historic Darwin log and pinned Diesel B source, authentic GNU graph and one known intervention, no compiler executed here",
            "original_run": published["run"],
            "old_log_sha256": sha(log),
            "source_sha256": sha(cwd / Q),
            "valid_graph": sha(baseline_graph),
            "changed_graph": hashlib.sha256(patched).hexdigest(),
            "difference": [254, 2],
            "target_path_count": own["original_workspace"]["paths"],
            "physical_graph_paths": len(own["graphs"]),
            "unique_graphs_decoded": len(decoded),
            "eager_rejection": rejected,
            "archived_untouched": True,
        }
    write(output, result)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("workdir", "corpus", "baseline_graph", "log", "output"):
        p.add_argument(name, type=Path)
    run(**vars(p.parse_args()))
