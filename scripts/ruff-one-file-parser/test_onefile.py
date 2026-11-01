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
        fixed = c.read(p.HERE / "excluded-hosts.json")
        terminal = c.read(p.HERE / "excluded-catalogs.json.gz")
        original = terminal["one_file"]["book"]
        book = copy.deepcopy(original)
        book["replays"] = {
            k: [v["run"], [v["job"]], [v["artifact"]]] for k, v in terminal["catalogs"].items()
        }
        head = "a" * 40
        run, job = 500, 501
        now = book["current"] | dict(id=run, head_sha=head, head_branch=p.BRANCH)
        fresh = book["jobs"][0] | dict(id=job, run_id=run, runner_name="fresh",
                                       runner_id=2000, started_at="2026-11-01T23:00:00Z")
        book.update(current=now, jobs=[fresh], initial_artifacts=[])

        def accept(data, boot=str(uuid.UUID(int=300))):
            return intake.enroll(data, head, "fresh", boot)

        self.assertEqual(accept(book)["first"], fixed["previous"]["first"])
        self.assertEqual(len(accept(book)["refused_replays"]), 2)
        exclusions = list(fixed["replays"].values())
        for prev in exclusions:
            with self.assertRaises(ValueError):
                accept(book, prev["boot"])
            with self.assertRaises(ValueError):
                accept(book | {"jobs": [fresh | {"runner_id": prev["runner_id"]}]})
        for row in [*fixed["previous"]["six"], fixed["previous"]["first"]]:
            with self.assertRaises(ValueError):
                accept(book, row["boot"])
        for conflict in (
            {"replays": {}}, {"jobs": [fresh | {"started_at": "2026-11-01T20:59:00Z"}]},
            {"initial_artifacts": book["first_artifacts"]},
            {"first": book["first"] | {"head_sha": "0"*40}},
            {"previous": dict(six=fixed["previous"]["six"][::-1], first=fixed["previous"]["first"])},
        ):
            with self.assertRaises(ValueError):
                accept(book | conflict)
        for k in book["replays"]:
            bad = copy.deepcopy(book)
            bad["replays"][k][2][0]["digest"] = "sha256:" + "0"*64
            with self.assertRaises(ValueError):
                accept(bad)

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
