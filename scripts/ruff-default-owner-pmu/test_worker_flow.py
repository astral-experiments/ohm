"""Replay the original hardware refusal under the worker's actual module and visit order."""

import gzip
import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
COLLECTOR, CONTRACT, SAMPLER = (Path(v).resolve() for v in sys.argv[1:4])
del sys.argv[1:4]
os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
sys.path.insert(0, str(HERE))
import worker as w


class WorkerFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        before = list(sys.path)
        sys.path.insert(0, str(HERE.parent / "ruff-repair-tables-pilot"))
        import guards

        assert Path(guards.__file__).resolve().parent == HERE.parent / "ruff-repair-tables-pilot"
        cls.topo, _ = w.instrument.compile_sources(COLLECTOR, CONTRACT, cls.work / "joined")
        cls.shadow = importlib.import_module("reopen")
        assert Path(cls.shadow.__file__).resolve() == HERE.parent / "ruff-repair-tables-pilot/reopen.py"
        # Load the final executable by its own absolute source, while the old name stays shadowed.
        spec = importlib.util.spec_from_file_location("registered_first_a_terminal", HERE / "reopen.py")
        cls.reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.reader)
        sys.path[:] = [str(cls.work / "joined"), str(HERE.parent / "ruff-repair-tables-pilot"), *before]
        cls.m = w.leaf_profile.support(SAMPLER)
        path = HERE / "first-a-leaf-calibration-original.zip"
        assert path.stat().st_size == 162370 and w.c.sha(path) == w.c.LEAF_REFUSED["digest"].split(":")[1]
        cls.z = ZipFile(path)
        assert len(cls.z.namelist()) == len(set(cls.z.namelist())) == 218
        assert not any(n.startswith(tuple(v + "/" for v in w.c.PHASES)) for n in cls.z.namelist())
        assert b"cannot import name 'Directory' from 'reopen'" in cls.z.read("refusal.txt")
        # Never execute a binary from the archive. The enrolled loop is only disassembled and hashed.
        for n in cls.z.namelist():
            if n.startswith("leaf-calibration/") or n == "counter-programs/loop":
                p = cls.work / "logs" / n
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(cls.z.read(n))
        cls.local = cls.work / "logs"
        cls.kit = w.c.read(cls.local / "leaf-calibration/tools.json")
        cls.root = Path(cls.kit["loop"]["path"]).parents[2]
        cls.loop = cls.local / "counter-programs/loop"

    @classmethod
    def tearDownClass(cls):
        cls.z.close()
        cls.tmp.cleanup()

    def test_previous_failure_and_all_native_calibration_from_worker_and_final(self):
        with self.assertRaises(ImportError):
            exec("from reopen import Directory", {})
        online = w.leaf_profile.check_local_calibration(self.local, self.root, self.loop, self.m, self.kit)
        final = self.reader.leaf_profile.check_calibration(self.z, self.root, self.loop, self.m, self.kit)
        self.assertEqual(online, final)
        self.assertEqual(
            {k: sorted(v["hot"].values()) for k, v in final.items()},
            {"child": [160000240], "thread": [160000240, 160000240], "empty": []},
        )
        self.assertEqual(
            {k: v["raw_sha256"] for k, v in final.items()},
            {
                "child": "949ad505d07101a4d461d4e4614d76df016d1985a0a6a78b7f861306ef0eda8d",
                "thread": "391455174c2ef2c74a3b8b085719f865a6484059297a81e462536fd58abbeaa1",
                "empty": "bef5e4c7b78dab7d5827d5baf85d46ccd9a4dfddc288e4c268549cd3b343cbfe",
            },
        )

    def test_original_refused_job_cannot_be_enrolled_as_current(self):
        original = self.reader.record(self.z, "enrollment.json")
        self.assertEqual(original["boot"], w.c.LEAF_REFUSED["boot"])
        with tempfile.TemporaryDirectory() as t, self.assertRaises(ValueError) as why:
            self.reader.replay(self.z, Path(t), original["head"], None, COLLECTOR, CONTRACT, SAMPLER, None)
        self.assertIn("current", str(why.exception))

    def test_worker_invoke_through_registered_terminal_decoder(self):
        # Acquisition itself is historical. Exercise actual worker forwarding, byte streams and final
        # hardware parsing on the exact recorded tree argv, event, mapping and native exit code.
        base = "leaf-calibration/thread/record"
        perf = self.reader.record(self.z, base + "/command.json")["argv"]
        stored = self.reader.record(self.z, base + "/target-environment.json")
        native = perf[perf.index("forward") + 2 :]
        calls = []

        def original(where, kit, cmd, cwd, env):
            records, dig = self.reader.leaf_profile.reopen_capture(
                self.z, self.root, base, kit, cmd, cwd, env
            )
            calls.append((len(records[0]), dig))
            return subprocess.CompletedProcess(
                cmd, 0, self.z.read(base + "/stdout"), self.z.read(base + "/stderr")
            )

        with tempfile.TemporaryDirectory() as t, patch.object(w, "REPO", self.root), patch.object(
            w, "ENV", stored["env"]
        ), patch.object(w.leaf_profile, "record", side_effect=original):
            folder = Path(t)
            self.assertEqual(w.invoke(folder, native, 0, self.kit), [])
            self.assertEqual(w.c.read(folder / "invocation.json")["argv"], native)
            self.assertEqual(
                gzip.decompress((folder / "cargo.stdout.gz").read_bytes()), self.z.read(base + "/stdout")
            )
            self.assertEqual(
                gzip.decompress((folder / "cargo.stderr.gz").read_bytes()), self.z.read(base + "/stderr")
            )
            self.assertGreater(calls[0][0], 0)
            with self.assertRaisesRegex(ValueError, "different sampled command"):
                w.invoke(folder, [*native, "--unexpected"], 0, self.kit)

    def test_real_middle_visit_routes_only_tree_to_sampler(self):
        with tempfile.TemporaryDirectory() as t, patch.object(w, "OUT", Path(t)), patch.object(
            w, "switch"
        ), patch.object(w, "source", return_value={"rev": "A"}):
            out = Path(t)
            selectors = self.reader.record(self.z, "selectors.json")
            w.c.save(out / "selectors.json", selectors)
            tools = self.root / "counter-kit/bin"
            for lane in ("plain-1", "attributed", "plain-2"):
                (out / lane).mkdir()
                with patch.object(
                    w, "invoke", side_effect=RuntimeError("entered native command")
                ) as inv, self.assertRaisesRegex(RuntimeError, "entered native command"):
                    w.run_visit(lane, "A", {}, tools, self.topo, self.kit)
                where, command, code = inv.call_args.args
                if lane == "attributed":
                    self.assertEqual(
                        command,
                        [
                            tools / "tree",
                            where / "trace",
                            "tree",
                            *[selectors[r][2] for r in self.topo.ROLES],
                            *w.c.CMD,
                        ],
                    )
                    self.assertIs(inv.call_args.kwargs["sampler"], self.kit)
                else:
                    self.assertEqual(command, [tools / "plain", where / "clock.json", *w.c.CMD])
                    self.assertIsNone(inv.call_args.kwargs["sampler"])
                self.assertEqual(code, 0)

    def test_middle_refusal_still_collects_the_after_clock_and_empty_error_repair(self):
        planned = [(k, phase) for k, phases in w.c.PHASES.items() for phase in phases]
        for refuse in (False, True):
            visits = []

            def visit(lane, phase, *args):
                visits.append((lane, phase))
                if refuse and (lane, phase) == ("attributed", "A"):
                    raise ValueError("real attribution exception is preserved")

            with tempfile.TemporaryDirectory() as t, patch.object(w, "OUT", Path(t)), patch.object(
                w.b, "fresh_outputs"
            ), patch.object(w, "switch"), patch.object(w.c, "git", return_value=b""), patch.object(
                w, "run_visit", side_effect=visit
            ):
                w.run_histories(None, None, None)
                self.assertEqual(
                    visits,
                    [v for v in planned if not (refuse and v[0] == "attributed" and v[1] not in ("A", "B"))],
                )
                refusal = Path(t) / "attribution-refusal.txt"
                self.assertEqual(refusal.exists(), refuse)
                if refuse:
                    self.assertIn("real attribution exception is preserved", refusal.read_text())


if __name__ == "__main__":
    unittest.main()
