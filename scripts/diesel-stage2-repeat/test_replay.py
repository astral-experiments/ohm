"""Offline positives and refusals covering the registered sources, roster, and graph attribution."""

import copy
import hashlib
import io
import tarfile
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from intake import BIND, members, official
from identity import ERROR, HEALTHY_A, PATCHED_B, diagnosis, trace, write
from repeat import positive_rows, roster, stage0_tools


def source_catalog():
    b = BIND
    r = {
        "id": b["run"],
        "head_sha": b["head"],
        "head_branch": b["branch"],
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
        "repository": {"full_name": b["repository"]},
        "head_repository": {"full_name": b["repository"]},
    }
    steps = [
        "Run the original optimized release command through all rustc PGO benchmarks",
        "Authenticate and escrow the instrumented native compiler and exact Cargo",
        "Save native instrumented runtime",
        "Run pinned original collector with only the real Diesel Opt benchmark",
    ]
    j = {
        "id": b["job"],
        "run_id": b["run"],
        "run_attempt": 1,
        "head_sha": b["head"],
        "name": b["job_name"],
        "conclusion": "success",
        "steps": [{"name": s, "conclusion": "success"} for s in steps],
    }
    art = dict(b["official"], expired=False, workflow_run={"id": b["run"], "head_sha": b["head"]})
    return r, j, art


def positive_fixture(root, unchanged=False):
    tool = root / "rustc"
    tool.write_bytes(b"distinct downloaded rustc")
    events = root / "events"
    events.mkdir()
    cases = [("A", False), ("A", True)] + ([("A", True)] if unchanged else []) + [("B", True)]
    prior = []
    for i, (s, inc) in enumerate(cases):
        wd = events / str(100 + i)
        wd.mkdir()
        pid = 900 + i
        rec = {
            "source": s,
            "source_sha256": HEALTHY_A if s == "A" else PATCHED_B,
            "argv": [
                str(tool),
                "--crate-name",
                "diesel",
                "--crate-type",
                "lib",
                "--edition=2021",
                "src/lib.rs",
                "--emit=dep-info,metadata,link",
                "opt-level=3",
                "-Zincremental-verify-ich",
                "-Zthreads=8",
                "-Zthreads=1",
            ],
            "environment": {
                "RUSTC_FORCE_RUSTC_VERSION": "rustc-perf",
                "RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER": "rustc-perf",
            },
            "cwd": str(root / "private"),
            "incremental": inc,
            "wrapper": 100 + i,
        }
        write(wd / "before.json", rec | {"pid": 0, "code": -1, "graphs": prior, "monotonic_ns": i * 10})
        write(
            wd / "running.json",
            {
                "wrapper": 100 + i,
                "pid": pid,
                "process": {
                    "path": str(tool),
                    "errno": 0,
                    "dev": tool.stat().st_dev,
                    "ino": tool.stat().st_ino,
                    "size": tool.stat().st_size,
                    "sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
                },
            },
        )
        prior = (
            [
                {
                    "path": "inc/s-" + str(i) + "/dep-graph.bin",
                    "sha256": str(i) * 64,
                    "size": 101,
                    "dev": 2,
                    "ino": 50 + i,
                }
            ]
            if inc
            else []
        )
        profiles = {
            f"default_{k}_{pid}.profraw": [70, k] for k in BIND["prior_evidence"]["runtime_profile_signatures"]
        }
        write(
            wd / "after.json",
            rec
            | {
                "pid": pid,
                "code": 0,
                "graphs": prior,
                "monotonic_ns": i * 10 + 8,
                "outputs": {"libdiesel.rlib": [200, "x"], "libdiesel.rmeta": [120, "y"]},
                "profile_files": profiles,
            },
        )
    return events, tool


class Test(unittest.TestCase):
    def test_physical_stage0(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bin").mkdir()
            expected = {}
            for name in ("cargo", "rustc"):
                value = bytes.fromhex("cffaedfe") + name.encode()
                (root / "bin" / name).write_bytes(value)
                expected[name] = {"binary": [len(value), hashlib.sha256(value).hexdigest()]}
            self.assertEqual(set(stage0_tools(root, expected)), {"cargo", "rustc"})
            for name in expected:
                p = root / "bin" / name
                data = p.read_bytes()
                for altered in [b"ELF!" + data[4:], data[:-1] + b"!", data[:-1]]:
                    p.write_bytes(altered)
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        stage0_tools(root, expected)
                p.write_bytes(data)

    def test_streaming_restore(self):
        data = b"MachO fixture"
        inv = {
            "unique_bytes": len(data),
            "entries": {
                "bin": {"type": "dir", "mode": 0o755},
                "bin/rustc": {
                    "type": "file",
                    "mode": 0o755,
                    "dev": 1,
                    "ino": 2,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                },
            },
        }
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            d = tarfile.TarInfo("bin")
            d.type = tarfile.DIRTYPE
            d.mode = 0o755
            t.addfile(d)
            f = tarfile.TarInfo("bin/rustc")
            f.size = len(data)
            f.mode = 0o755
            t.addfile(f, io.BytesIO(data))
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td)
            summary = members(io.BytesIO(buf.getvalue()), inv, dst)
            self.assertEqual(summary, {"members": 2, "distinct_regular_inodes": 1, "unique_bytes": len(data)})
            self.assertEqual((dst / "bin/rustc").read_bytes(), data)
        for typ, mode, sha in [
            ("symlink", 0o755, hashlib.sha256(data).hexdigest()),
            ("file", 0o777, hashlib.sha256(data).hexdigest()),
            ("file", 0o755, "0" * 64),
        ]:
            other = copy.deepcopy(inv)
            other["entries"]["bin/rustc"].update(type=typ, mode=mode, sha256=sha)
            with self.assertRaises(ValueError):
                members(io.BytesIO(buf.getvalue()), other)

    def test_original_failure(self):
        old = gzip.decompress((HERE.parent / "darwin-pgo-diesel/known-failure.log.gz").read_bytes()).decode()
        rec = diagnosis(old, trace(old))
        self.assertEqual(Path(rec["cwd"]).name, ".tmpGktchz")
        for token in (
            ERROR,
            "SerializedDepGraph>::decode",
            "-Zincremental-verify-ich",
            "-Zthreads=1",
            "mod.rs:527",
        ):
            with self.subTest(token=token), self.assertRaises((ValueError, IndexError)):
                diagnosis(old.replace(token, "UNENROLLED"), trace(old))

    def test_official(self):
        r, j, a = source_catalog()
        official(r, j, a)
        for index, key, value in [
            (0, "run_attempt", 2),
            (0, "conclusion", "failure"),
            (1, "head_sha", "later"),
            (1, "steps", []),
            (2, "expired", True),
            (2, "id", 523),
            (2, "digest", "sha256:other"),
        ]:
            args = copy.deepcopy([r, j, a])
            args[index][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                official(*args)

    def test_roster(self):
        expected = BIND["roster"]
        benches = sorted(BIND["trees"])
        for role, names, phases in [
            ("primary", benches, expected),
            ("focused", ["diesel-2.2.10"], [p for p in expected if p.startswith("Running diesel-2.2.10: Opt ")]),
        ]:
            count = len(names)
            lines = [f"Running with {4 if count==9 else 1} job(s)", "Profiling Test with Eprintln", *phases]
            lines += [
                f"{action} benchmark {name} ({i+1}/{count})"
                for action in ("Executing", "Finished")
                for i, name in enumerate(names)
            ]
            ok = "\n".join(lines)
            self.assertEqual(roster(ok, role), phases)
            for bad in (
                ok + "\n" + phases[0],
                ok.replace("FrontendThreads(1)", "FrontendThreads(8)", 1),
                ok + "\ncollector error:",
                ok.replace("Finished benchmark", "Skipped benchmark", 1),
            ):
                with self.assertRaises(ValueError):
                    roster(bad, role)

    def test_two_actual_schedules(self):
        for unchanged in (False, True):
            with tempfile.TemporaryDirectory() as td:
                events, rustc = positive_fixture(Path(td), unchanged)
                self.assertEqual(len(positive_rows(events, rustc)), 3 + int(unchanged))

    def test_refuse_misattribution(self):
        for name, mutate in [
            (
                "false verification",
                lambda e, t: [r["argv"].remove("-Zincremental-verify-ich") for r in (e["before"], e["after"])],
            ),
            (
                "wrong forced header",
                lambda e, t: e["before"]["environment"].update(RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER="other"),
            ),
            (
                "wrong physical source",
                lambda e, t: [r.update(source_sha256="0" * 64) for r in (e["before"], e["after"])],
            ),
            ("wrong image", lambda e, t: e["running"].update(process={"path": str(Path(__file__))})),
            ("vanished child", lambda e, t: e["running"].update(process={"path": None})),
            ("wrong PID", lambda e, t: e["running"].update(pid=1)),
            ("changed physical compiler", lambda e, t: e["running"]["process"].update(sha256="0" * 64)),
            ("other modules", lambda e, t: e["after"].update(profile_files={})),
            ("missing link product", lambda e, t: e["after"].update(outputs={"one.rmeta": [20, "h"]})),
            ("different graph", lambda e, t: e["before"]["graphs"][0].update(sha256="0" * 64)),
            ("wrong source", lambda e, t: e["before"].update(source="A")),
            ("no graph", lambda e, t: e["before"].update(graphs=[])),
            ("wrong chronology", lambda e, t: e["before"].update(monotonic_ns=9)),
        ]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                events, tool = positive_fixture(Path(td))
                final = events / "102"
                records = {p.stem: json.loads(p.read_bytes()) for p in final.glob("*.json")}
                mutate(records, tool)
                for key, row in records.items():
                    (final / (key + ".json")).write_text(json.dumps(row))
                with self.assertRaises((ValueError, TypeError)):
                    positive_rows(events, tool)


if __name__ == "__main__":
    unittest.main()
