"""Software checks on original archives. No new hardware checks, compiler runs or synthetic effect measurements."""

import argparse
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as c
import inputs
import prior
import support


def rejects(f):
    try:
        f()
    except (ValueError, AssertionError, KeyError):
        return True
    raise AssertionError("accepted corrupted fixture")


def extract_public(root, rev, path, names):
    for n in names:
        target = path / n
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "-C", root, "show", rev + ":" + n]))


def calibration_replay(software, tar):
    c.require(
        inputs.sha(tar) == "058716b88b220a32d746fef1c2cb831498fc4ec8ea7e974270858e004529dd68",
        "different prior source capsule",
    )
    outputs = {}
    with (
        tarfile.open(fileobj=io.BytesIO(subprocess.check_output(["zstd", "-qdc", tar]))) as t,
        tempfile.TemporaryDirectory(dir="/dev/shm") as tmp,
    ):
        files = json.load(t.extractfile("files.json"))
        for k in ("01", "02"):
            store = Path(tmp) / k
            rows = files[k]
            for key, h in rows.items():
                if not key.startswith(("calibration/", "observers/")):
                    continue
                v = t.extractfile(h).read()
                c.require(hashlib.sha256(v).hexdigest() == h, "source content digest")
                p = store / key
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(v)
            proof = software.calibration(store / "observers", store, replay=True)
            outputs[k] = {
                "admitted_sha256": inputs.sha(store / "calibration/admitted.json"),
                "whole_shapes": len(proof["whole28"]),
                "nested_scopes": len(proof["nested"]["tree"]),
            }
    return outputs


def mapper(zipname):
    # Native argv/images are actual historical observations; ancestry and numbers in this
    # isolated reader fixture are imposed test inputs. They are never emitted as costs.
    with ZipFile(zipname) as z:
        src = json.loads(z.read("trace/edited/command.json"))["working_directory"]
        root = Path(src).parent
        before = c.typed(gzip.decompress(z.read("trace/edited/stdout.jsonl.gz")), root)[1]
        rows = prior.decode(z, "trace/edited/execs.json.gz")
        events = []
        selected = {}
        counts = {0: 10000}
        parents = {}
        pids = {}
        for pid, _, image, argv in rows:
            if "--crate-name" in argv and "--out-dir" in argv:
                owner, output = c.compiler(argv, root)
                kind = 1
                pids[output] = pid
            elif "-o" in argv:
                outfile = c.option(argv, "-o")
                kind = 3 if image.endswith("collect2") else 4 if image.endswith("ld.bfd") else 2
                pids[(outfile, kind)] = pid
            elif image == before["build_script_build"]:
                kind = 0
            else:
                continue
            i = len(events) + 1
            events.append({"serial": i, "pid": pid, "path": image, "argv": argv, "kind": kind})
            if kind in (1, 2, 4):
                selected[i] = events[-1]
                counts[i] = {1: 200, 2: 100, 4: 50}[kind]
        outer = 0
        for e in events:
            pid, kind = e["pid"], e["kind"]
            parents[pid] = [pid, outer] if kind in (0, 1) else None
            if kind not in (0, 1):
                output = c.option(e["argv"], "-o")
                parents[pid] = [pids[(output, k)] for k in range(kind, 1, -1)] + [pids[output], outer]

        def call(ev=events, sel=selected, edges=parents, subjects=before, pmu=counts):
            return c.classify(root, subjects, True, outer, ev, sel, pmu, edges, edges)

        ok = call()
        require = c.require
        require(
            set(ok["compilers"]) == c.EDIT and ok["eight_inclusive"] == 1600, "test reader arithmetic"
        )
        ix = next(
            i
            for i, e in enumerate(events)
            if "--crate-name" in e["argv"] and c.option(e["argv"], "--crate-name") == "ruff_db"
        )
        leaf = events[ix]
        other = next(x for x in events if x["kind"] == 4)
        bad = copy.deepcopy(parents)
        bad[other["pid"]].insert(-1, leaf["pid"])
        false_src = copy.deepcopy(events)
        a = false_src[ix]["argv"]
        a[a.index("crates/ruff_db/src/lib.rs")] = "crates/other/src/lib.rs"
        sub = selected | {leaf["serial"]: false_src[ix]}
        wrong = before | {"ruff_db": before["ty_project"]}
        bad_meta = copy.deepcopy(parents)
        bad_meta[leaf["pid"]].insert(-1, ok["compilers"]["ty_project"]["pid"])
        results = {
            "unexpected_native_child": rejects(lambda: call(edges=bad)),
            "different_rustc_source": rejects(lambda: call(ev=false_src, sel=sub)),
            "wrong_returned_typed_artifact": rejects(lambda: call(subjects=wrong)),
            "nested_selected_compilers": rejects(lambda: call(edges=bad_meta)),
            "missing_eighth_scope": rejects(
                lambda: call(sel={i: e for i, e in selected.items() if i != leaf["serial"]})
            ),
            "overlapping_counts": rejects(lambda: call(pmu=counts | {0: 100})),
            "observer_spread": rejects(lambda: c.ceiling(100, 112, 100, 55)),
            "overstated_component": rejects(lambda: c.ceiling(100, 101, 100, 100)),
        }
        require(
            c.ceiling(100, 101, 102, 40)["outcome"] == "below-2x"
            and c.ceiling(100, 101, 102, 51)["outcome"] == "unresolved"
            and c.ceiling(100, 101, 102, 60)["outcome"] == "room-for-investigation",
            "ceiling direction",
        )
        return {
            "original_argv_count": len(events),
            "corruption_rejections": results,
            "test_only_no_new_observations": True,
        }


def main(a):
    previous = prior.main(a.archives)
    c.require(
        previous == inputs.load(HERE / "prior.json"), "original ZIPs disagreed with prior summary"
    )
    with tempfile.TemporaryDirectory(dir="/dev/shm") as tmp:
        d = Path(tmp)
        src = inputs.load(HERE / "sources.json")
        base = d / "base"
        counter = d / "counter"
        extract_public(a.feature, c.FEATURELESS, base, src["featureless"])
        extract_public(a.collector, c.COLLECTOR, counter, src["counter"])
        study, pmu, topology = support.load_modules(base, counter, d / "joined", verify_git=False)
        c.require(
            study.panel.E2E == c.CLI and study.ENROLL["e2e"]["patch_sha256"] == c.PATCH,
            "ordinary argv disagrees",
        )
        controls = calibration_replay(pmu, a.capsule)
    (signed,) = [x for x in a.archives if "13027159509" in x.name]
    return {
        "historical_zip_sha256s": {k: v["original_sha256"] for k, v in previous.items()},
        "calibrations": controls,
        "raw_argv_without_hardware": mapper(signed),
        "tests": "software only",
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archives", nargs=4, type=Path)
    for k in ("feature", "collector", "capsule"):
        p.add_argument("--" + k, type=Path, required=True)
    v = main(p.parse_args())
    print(json.dumps(v, sort_keys=True, indent=2))
