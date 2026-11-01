import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from escrow import facts, keep_graphs, pack, safe_for_clone
from identity import ALIGNED, ERROR, PATCHED_B, Q, SECTION, TREE, diagnosis, sha, trace
from supervise import finished, run_child
from worker import check_clone, check_paths, command, first

ORIGINAL = gzip.decompress((HERE / "known-failure.log.gz").read_bytes()).decode()
MARKER = (
    "[2026-11-01T01:38:52.310Z INFO  opt_dist::timer] Section "
    + chr(96)
    + SECTION
    + chr(96)
    + " ended: OK (957.79s)"
    + chr(96)
)
POSITIVE = (
    "\n".join(
        l
        for l in ORIGINAL.splitlines()
        if l.startswith("Finished benchmark ") or not any(v in l for v in ("collector error:", "ended: FAIL"))
    )
    + "\n"
    + MARKER
    + "\n"
)


class Tests(unittest.TestCase):
    def test_full_original_binding(self):
        recorded = json.loads((HERE / "recorded.json").read_bytes())
        self.assertEqual(hashlib.sha256(ORIGINAL.encode()).hexdigest(), recorded["selected_original_lines_sha256"])
        native = trace(ORIGINAL)
        self.assertEqual(native["argv"][-2:], ["--jobs", "4"])
        failure = diagnosis(ORIGINAL, native)
        self.assertEqual(Path(failure["cwd"]).name, ".tmpGktchz")
        self.assertEqual(len(failure["argv"]), 49)
        self.assertEqual(failure["argv"][0], native["argv"][9])

    def test_wrong_training_or_source(self):
        for old, new in (
            ("--jobs 4", "--jobs 1"),
            ("externs,ctfe", "ctfe"),
            ("Check,Debug,Opt", "Opt"),
            ("/stage2-tools-bin/cargo", "/stage0/bin/cargo"),
            ("DIST_TRY_BUILD=0", "DIST_TRY_BUILD=1"),
            ("LC_ALL=", "UNENROLLED_OVERRIDE="),
        ):
            with self.subTest(old=old), self.assertRaises((ValueError, IndexError)):
                trace(ORIGINAL.replace(old, new))
        for old, new in (
            ("serialized.rs:382:13", "serialized.rs:380:1"),
            ("mod.rs:527", "mod.rs:528"),
            ("-Zthreads=1", "-Zthreads=4"),
        ):
            with self.subTest(old=old), self.assertRaises(ValueError):
                diagnosis(ORIGINAL.replace(old, new), trace(ORIGINAL))
        # Different Diesel errors still permit identifying and sealing the
        # real input. Only the final diagnosis and replay become ineligible.
        self.assertTrue(diagnosis(ORIGINAL.replace(ERROR, "different"), trace(ORIGINAL), exact=False))

    def test_full_roster_before_early_stop(self):
        self.assertEqual(finished(POSITIVE)["argv"][-1], "4")
        for text in (
            ORIGINAL,
            POSITIVE.replace("Finished benchmark externs", "Never finished externs"),
            POSITIVE.replace("externs (5/9)", "bitmaps-3.2.1 (1/9)"),
            POSITIVE + "\ncollector error: other",
        ):
            with self.assertRaises(ValueError):
                finished(text)

    def test_real_subprocess_stops_only_after_qualified_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tag, log, expected in (
                ("complete", POSITIVE, 0),
                ("reject", POSITIVE.replace("Finished benchmark externs", "not finished externs"), 71),
            ):
                inp = root / (tag + ".txt")
                inp.write_text(log)
                after = root / (tag + ".survived")
                script = "import pathlib,sys,time;sys.stdout.write(pathlib.Path(sys.argv[1]).read_text());sys.stdout.flush();time.sleep(.4);pathlib.Path(sys.argv[2]).touch();sys.exit(71)"
                # Run the actual supervisor but keep the test's fixture log local.
                runner = root / (tag + ".py")
                runner.write_text(
                    "import sys; from pathlib import Path;sys.path.insert(0,"
                    + repr(str(HERE))
                    + ");from supervise import run_child;raise SystemExit(run_child("
                    + repr([sys.executable, "-c", script, str(inp), str(after)])
                    + ",Path("
                    + repr(str(root))
                    + "),Path("
                    + repr(str(root / tag))
                    + ")))"
                )
                call = subprocess.run([sys.executable, "-IB", runner], capture_output=True, timeout=10)
                self.assertEqual(call.returncode, expected, call.stderr)
                self.assertEqual(after.exists(), tag == "reject")
                self.assertEqual(
                    json.loads((root / tag / "primary.json").read_bytes())[
                        "stopped_after_completed_rustc_profiles"
                    ],
                    tag == "complete",
                )

    def test_all_source_revisions(self):
        body = (HERE / "aligned-rust.commit").read_bytes()
        self.assertEqual(hashlib.sha1(b"commit " + str(len(body)).encode() + b"\0" + body).hexdigest(), ALIGNED)
        self.assertEqual(body.splitlines()[0].decode(), "tree " + TREE)
        self.assertEqual(
            sha(HERE / "aligned-manifest.json"), "03d0d484c81c5ed7ad28c95285bc111657a8c2a79f477eb6b74db4a6b463ec28"
        )

    def test_full_directory_and_both_graph_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "fixture"
            project.mkdir()
            a = project / "incremental-state/diesel-x/s-1-2-done"
            a.mkdir(parents=True)
            b = a.with_name("s-2-3-working")
            b.mkdir()
            (a / "dep-graph.bin").write_bytes(b"first genuine-named input")
            os.link(a / "dep-graph.bin", b / "dep-graph.bin")
            (b / "dep-graph.part.bin").write_bytes(b"partial")
            (a / "query-cache.bin").write_bytes(b"query")
            (project / "included-link").symlink_to(a.relative_to(project) / "dep-graph.bin")
            (project / "empty").touch()
            before = facts(project)
            safe_for_clone(project)
            proof = keep_graphs(project, root / "graphs")
            self.assertEqual(len(proof), 4)
            self.assertEqual(len({v["ino"] for v in proof if v["path"].endswith("/dep-graph.bin")}), 1)
            archive = root / "workspace.tar.gz"
            result = pack(project, archive)
            self.assertEqual(result["sha256"], sha(archive))
            self.assertEqual(before, facts(project))
            with tarfile.open(archive) as f:
                self.assertEqual(len([m for m in f if m.islnk()]), 1)
            with self.assertRaises(ValueError):
                facts(project, ceiling=1)
            (project / "escaped").symlink_to(root / "outside")
            with self.assertRaises(ValueError):
                safe_for_clone(project)

    def test_clone_preserves_hardlinks_without_aliasing_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "original"
            dest = root / "clone"
            src.mkdir()
            (src / "obj").write_bytes(b"payload")
            os.link(src / "obj", src / "work")
            (src / "same-bytes-different-file").write_bytes(b"payload")
            shutil.copytree(src, dest)
            self.assertFalse((dest / "obj").samefile(dest / "work"))
            check_clone(src, dest)
            self.assertTrue((dest / "obj").samefile(dest / "work"))
            self.assertFalse((dest / "obj").samefile(src / "obj"))
            self.assertFalse((dest / "obj").samefile(dest / "same-bytes-different-file"))
            (dest / "work").unlink()
            os.link(src / "work", dest / "work")
            with self.assertRaisesRegex(ValueError, "aliases the parked"):
                check_clone(src, dest)

    def test_passing_primary_requires_nine_and_real_merged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp).resolve()
            original = trace(POSITIVE)
            prior = Path(original["build"]).parents[2]
            log = POSITIVE.replace(str(prior), str(work))
            merged = Path(trace(log)["build"]) / "opt-artifacts/rustc-pgo.profdata"
            merged.parent.mkdir(parents=True)
            for present in (False, True):
                report = work / ("yes-profile" if present else "no-profile")
                report.mkdir()
                (report / "primary.json").write_text('{"code":-15,"stopped_after_completed_rustc_profiles":true}')
                (report / "original-opt-dist.log").write_text(log)
                if present:
                    merged.write_bytes(b"isolated positive fixture")
                    first(work, report)
                    self.assertFalse(json.loads((report / "before-replay.json").read_bytes())["failed_timing_root"])
                else:
                    with self.assertRaisesRegex(ValueError, "missing actual merged"):
                        first(work, report)

    def test_originals_are_uploaded_before_any_diagnostic_compiler(self):
        # Local stdlib-only contract test also runs on the fresh sparse CI checkout.
        workflow = (HERE.parents[1] / ".github/workflows/ci.yml").read_text()
        stages = [
            "worker.py first",
            "id: originals",
            "worker.py decode",
            "worker.py runtime",
            "worker.py direct",
            "worker.py focused",
        ]
        self.assertEqual(
            [workflow.index(value) for value in stages], sorted(workflow.index(value) for value in stages)
        )
        for step in ("decode", "runtime", "direct", "focused"):
            code = workflow.split("id: " + step + "\n", 1)[1].split("run: python3", 1)[0].replace("''", "'")
            self.assertIn("steps.escrow.outcome == 'success'", code)
            self.assertIn("steps.originals.outcome == 'success'", code)
        self.assertIn("timeout-minutes: 180", workflow)
        self.assertEqual(workflow.count("runs-on:"), 1)
        self.assertIn("runs-on: macos-15", workflow)
        self.assertNotIn("actions: write", workflow)

    def test_diagnostic_timeouts_leave_a_terminal_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "deadline exceeded"):
                command(
                    root / "timeout", [sys.executable, "-Is", "-c", "import time;time.sleep(10)"], root, {}, 0.05
                )
            row = json.loads((root / "timeout/exit.json").read_bytes())
            self.assertNotEqual(row["code"], 0)
            self.assertIn("deadline", row["refusal"])
            self.assertEqual(
                command(root / "natural", [sys.executable, "-Is", "-c", "raise SystemExit(7)"], root, {}, 2), 7
            )

    def test_unrelated_paths_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / ".tmpCASE"
            p.mkdir()
            (p / "incremental-state").mkdir()
            (p / "out").mkdir()
            r = p / "dep.rlib"
            r.write_bytes(b"exact")
            argv = ["rustc", "--out-dir", str(p / "out"), "--extern", "x=" + str(r)]
            check_paths(p, p / "incremental-state", argv, root)
            with self.assertRaises(ValueError):
                check_paths(p, p / "incremental-state", argv, root / "other")
            outside = root / "outside"
            outside.write_bytes(b"other")
            with self.assertRaises(ValueError):
                check_paths(p, p / "incremental-state", argv[:-1] + ["x=" + str(outside)], root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
