"""Exercise the original signed native parser harness, earlier full CLI records, and refusals."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol as p
import parser_tests as pt
import inventory
import intake
import instrument
import verify

f, c = p.f, p.c


class Original(unittest.TestCase):
    def test_both_cli_observations_and_stale_substitution(self):
        cases = c.read(p.HERE / "cli-before.json.gz")
        self.assertEqual(len({v["sha256"] for v in cases}), 2)
        for raw in cases:
            # Only the original executable's private path is replaced in this offline fixture.
            binary = Path("/registered") / raw["sha256"]
            row = dict(
                **raw,
                path=str(binary),
                expected="baseline",
                argv=[str(binary), *f.CLI_ARGS],
                version_argv=[str(binary), "version", "--output-format", "json"],
            )
            f.validate(row, binary, "baseline")
            with self.assertRaises(ValueError):
                f.validate(row | {"expected": "edited"}, binary, "edited")
            with self.assertRaises(ValueError):
                f.validate(row, binary.parent / "other", "baseline")
            m = copy.deepcopy(row)
            m["cases"]["cause-without-exception"]["exit"] = 0
            with self.assertRaises(ValueError):
                f.validate(m, binary, "baseline")

    def test_signed_parser_snapshots(self):
        original = c.read(p.HERE / "parser-native-control.json.gz")
        for label, raw in original.items():
            repo = Path(raw["exact"]["workspace_root"])
            binary = Path(raw["exact"]["argv"][0])
            names = {v.removesuffix(": test") for v in raw["list"]["stdout"].splitlines()}
            pt.verify_calls(raw, names, label, binary, repo)
            with self.assertRaises(ValueError):
                pt.verify_calls(
                    raw, names, "edited" if label == "baseline" else "baseline", binary, repo
                )
            for key in ("list", "original-suite", "list-plus-one", "exact"):
                other = copy.deepcopy(raw)
                other[key]["argv"][0] = "/other/fixtures"
                with self.assertRaises(ValueError):
                    pt.verify_calls(other, names, label, binary, repo)
            missing = copy.deepcopy(raw)
            missing["list"]["stdout"] = missing["list"]["stdout"].split("\n", 1)[1]
            with self.assertRaises(ValueError):
                pt.verify_calls(missing, names, label, binary, repo)

    def test_refuses_runtime_file_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            src = repo / f.FIXTURE
            snap = repo / f.SNAP
            src.parent.mkdir(parents=True)
            snap.parent.mkdir(parents=True)
            snap.write_bytes(b"foreign")
            with self.assertRaises(FileExistsError):
                with pt.injected(repo):
                    self.fail("collision admitted")
            self.assertEqual(snap.read_bytes(), b"foreign")
            self.assertFalse(src.exists())
            snap.unlink()
            with pt.injected(repo):
                self.assertEqual(
                    (f.sha(src.read_bytes()), f.sha(snap.read_bytes())), (f.FIXTURE_SHA, pt.SNAP_SHA)
                )
            self.assertFalse(src.exists())
            self.assertFalse(snap.exists())

    def test_actual_twenty_compilers_and_wild(self):
        data = c.read(c.HERE / "physical-fixture.json.gz")
        repo = Path("/home/runner/work/_temp/ohm-branch-object-qa/ruff")
        work = repo.parent / "work"
        _, _, units, _ = p.graph(data["rows"], "cli", repo, work)
        evs = data["events"]
        chains = {int(k): v for k, v in data["chains"].items()}
        selected = {
            v["serial"]: v
            for v in evs
            if v["kind"] == 1
            and "--crate-name" in v["argv"]
            and "--out-dir" in v["argv"]
            or v["kind"] in (2, 4)
            and "-o" in v["argv"]
        }

        def analyze(sel):
            return inventory.classify(
                "cli",
                repo,
                work,
                units,
                data["inodes"],
                {},
                p.command("cli"),
                evs[0]["pid"],
                evs,
                sel,
                dict.fromkeys([0, *sel], 0),
                chains,
                chains,
            )

        report = analyze(selected)
        self.assertEqual((len(report["owners"]), report["wild"]), (20, 1))
        altered = selected.copy()
        (wild,) = [i for i, v in selected.items() if v["kind"] == 4]
        del altered[wild]
        with self.assertRaises(ValueError):
            analyze(altered)
        # Preserve the true signed writer; append an independent foreign writer in that same rustc tree.
        wrong = copy.deepcopy(next(v for v in evs if v["kind"] == 3 and "-o" in v["argv"]))
        wrong.update(kind=0, serial=max(v["serial"] for v in evs) + 1, path="/usr/bin/foreign")
        evs.append(wrong)
        with self.assertRaisesRegex(ValueError, "foreign child output writer"):
            analyze(selected)
        evs.pop()
        pos = next(v for v in evs if v["kind"] == 4 and "-o" in v["argv"])
        pos["argv"][pos["argv"].index("-o") + 1] += ".foreign"
        with self.assertRaises(ValueError):
            analyze(selected)

    def test_separate_workers_and_frozen_custody(self):
        jobtime = lambda i: f"2026-11-01T18:00:0{i}+00:00"
        boot = lambda i: str(uuid.UUID(int=i))
        head = "a" * 40
        run = dict(
            run_attempt=1,
            event="workflow_dispatch",
            path=".github/workflows/ci.yml",
            status="completed",
            repository=dict(full_name=c.REPO),
        )
        six = run | dict(id=c.PREVIOUS, head_sha=c.PREVIOUS_HEAD)
        jobs, arts, sealed = [], [], []
        for i, job in enumerate(c.BLOCKED_JOBS, 1):
            jobs.append(
                dict(
                    id=job,
                    name=f"GNU sorted packed Ruff CLI confirmation {i:02}",
                    status="completed",
                    runner_name=f"old{i:02}",
                    runner_id=100 + i,
                    completed_at=jobtime(0),
                )
            )
            art = dict(
                id=i,
                name=f"gnu-sorted-packed-ruff-cli-confirmation-{i:02}",
                digest=f"sha256:{i:064x}",
                size_in_bytes=1000,
            )
            arts.append(art)
            sealed.append(dict(job=job, artifact=i, digest=art["digest"], boot=boot(i)))
        first = run | dict(id=200, head_sha=p.FIRST, head_branch=c.BRANCH)
        prev = dict(
            id=220,
            run_id=200,
            name="Signed GNU Ruff first-A instruction owners",
            status="completed",
            runner_id=220,
            runner_name="first-stage",
            started_at=jobtime(1),
            completed_at=jobtime(2),
        )
        original = dict(
            id=221,
            name="signed-gnu-ruff-default-first-a-owners",
            size_in_bytes=123,
            digest="sha256:" + "a" * 64,
            expired=False,
            workflow_run=dict(id=200, head_sha=p.FIRST),
        )
        now = run | dict(id=300, head_sha=head, head_branch=p.BRANCH, status="in_progress")
        fresh = dict(
            id=320, run_id=300, name=p.JOB, runner_id=320, runner_name="one-file", started_at=jobtime(3)
        )
        prior = dict(run=200, job=220, artifact=221, digest=original["digest"], boot=boot(20))
        book = dict(
            six=six,
            six_jobs=jobs,
            six_artifacts=arts,
            previous=dict(six=sealed, first=prior),
            first=first,
            first_jobs=[prev],
            first_artifacts=[original],
            current=now,
            jobs=[fresh],
            initial_artifacts=[],
        )

        def accept(book, actual_boot=boot(30)):
            return intake.enroll(book, head, "one-file", actual_boot)

        self.assertEqual(accept(book)["first"], prior)
        for conflict in (
            {"jobs": [fresh | dict(runner_id=220)]},
            {"jobs": [fresh | dict(started_at=jobtime(1))]},
            {"initial_artifacts": [original]},
            {"first": first | dict(head_sha="0" * 40)},
            {"first_artifacts": [original | dict(digest="sha256:" + "b" * 64)]},
            {"first_artifacts": [original | dict(workflow_run=dict(id=101, head_sha=p.FIRST))]},
            {"previous": dict(six=sealed[::-1], first=prior)},
        ):
            with self.assertRaises(ValueError):
                accept(book | conflict)
        for occupied in (boot(1), boot(20)):
            with self.assertRaises(ValueError):
                accept(book, occupied)

    def test_wrong_causal_or_meter_scope(self):
        self.assertEqual(
            p.command("parser"),
            [
                "cargo",
                "+ohm",
                "test",
                "-p",
                "ruff_python_parser",
                "--test",
                "fixtures",
                "--no-run",
                "--locked",
                "--offline",
                "-j4",
                "--message-format=json",
            ],
        )
        self.assertEqual(p.command("cli"), c.CMD)
        valid = dict(code=0, event_errno=0, instructions=512, enabled=99, running=99)
        self.assertEqual(instrument.clock_value(valid), 512)
        for bad in ({"code": 1}, {"event_errno": 1}, {"running": 98}, {"instructions": 0}):
            with self.assertRaises(ValueError):
                instrument.clock_value(valid | bad)
        a = {
            "head": f.B,
            "tree": f.B_TREE,
            "branch": f.BRANCH,
            "source_sha256": f.SOURCE_SHA["edited"],
            "index_sha256": "0" * 64,
            "status": " M " + f.SRC,
        }
        a["watched"] = {
            k: [f.sha(text.encode()), 1, 2, 3, 4]
            for k, text in {"HEAD": "ref: " + f.BRANCH + "\n", f.BRANCH: f.B + "\n"}.items()
        }
        verify.source(a, "edited")
        for key, val in [
            ("head", "0" * 40),
            ("status", ""),
            ("source_sha256", f.SOURCE_SHA["baseline"]),
        ]:
            with self.assertRaises(ValueError):
                verify.source(a | {key: val}, "edited")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        with tempfile.TemporaryDirectory() as temp:
            topo, _ = instrument.compile_sources(
                *[Path(s).resolve() for s in sys.argv[1:]], Path(temp) / "frozen"
            )
            assert inventory.decoder(topo).ROLES == ("rustc", "cc", "collect2", "wild")
        sys.argv[1:] = []
    unittest.main()
