"""Recompute the eight paired results from their original Actions clock and Cargo streams."""

import argparse
import hashlib
import json
import shutil
import statistics
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OBS = "ohm-remat-comparison/observations"
LOGS = "ohm-branch-object-qa/logs"
PHASES = ("old", "new", "unchanged", "invalid", "repair")


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def archive(directory, pair, fetch):
    path = directory / f"{pair['run']}-{pair['artifact']}.zip"
    if fetch:
        endpoint = (
            f"repos/astral-experiments/ohm/actions/artifacts/{pair['artifact']}/zip"
        )
        with path.open("xb") as output:
            subprocess.run(
                [
                    shutil.which("gh-auto") or "gh",
                    "api",
                    "--allow-escape-sequences",
                    endpoint,
                ],
                check=True,
                stdout=output,
            )
    assert path.stat().st_size == pair["size"] and digest(path) == pair["sha256"], path
    return zipfile.ZipFile(path)


def check_command(z, path, suite, phase, observation):
    clock = json.loads(z.read(path + "/clock.json"))
    assert clock["event_errno"] == 0 and 0 < clock["running"] <= clock["enabled"]
    assert clock["running"] * 100 >= 99 * clock["enabled"]
    assert clock["instructions"] == observation["cargo"] and clock["instructions"] > 0
    rows = [
        json.loads(line)
        for line in z.read(path + "/outer.stdout").splitlines()
        if line.startswith(b"{")
    ]
    good = phase != "invalid"
    assert rows[-1] == {"reason": "build-finished", "success": good}
    assert sum(r.get("reason") == "build-finished" for r in rows) == 1
    assert clock["code"] == (0 if good else 101)
    if not good:
        assert observation["error"] == "E0308"
        assert any(
            r.get("reason") == "compiler-message"
            and r["message"].get("code")
            and r["message"]["code"]["code"] == "E0308"
            for r in rows
        )
    elif phase in ("new", "unchanged"):
        dirty = sorted(
            r["target"]["name"]
            for r in rows
            if r.get("reason") == "compiler-artifact" and not r["fresh"]
        )
        if suite == "build":
            assert dirty == (["ruff_workspace"] if phase == "new" else [])
        else:
            assert dirty == (["e2e", "ty_server"] if phase == "new" else ["e2e"])
            assert observation["test_count"] == 152
            assert b"test workspace_folders::single_file_workspace ... ok" in z.read(
                path + "/execute/outer.stdout"
            )
    return clock["instructions"]


def check_products(z, stem, suite):
    if suite == "build":
        old = z.read(stem + "-edit/old/client/field.stdout")
        clean = z.read(stem + "-clean/clean-new/client/field.stdout")
        sibling = z.read(stem + "-edit/old/client/sibling.stdout")
        assert (
            b"globset` documentation" not in old and b"globset` documentation" in clean
        )
        for stage in (
            "edit/old",
            "edit/new",
            "edit/unchanged",
            "edit/repair",
            "clean/clean-new",
        ):
            path = f"{stem}-{stage}/client/"
            for case, code in (
                ("field", 0),
                ("sibling", 0),
                ("missing", 2),
                ("invalid", 1),
            ):
                assert json.loads(z.read(path + case + ".json"))["exit"] == code
            assert z.read(path + "field.stdout") == (
                old if stage == "edit/old" else clean
            )
            assert z.read(path + "sibling.stdout") == sibling
            assert not z.read(path + "missing.stdout")
            assert b'"code":"E0308"' in z.read(path + "invalid.stderr")
        return

    target = b"workspace_folders::single_file_workspace"
    clean = sorted(z.read(stem + "-clean/clean-new/list/outer.stdout").splitlines())
    old = sorted(z.read(stem + "-edit/old/list/outer.stdout").splitlines())
    assert len(set(old)) == len(old) == 151
    assert target + b": test" not in old and sorted([*old, target + b": test"]) == clean
    for stage in (
        "edit/new",
        "edit/unchanged",
        "edit/repair",
        "clean/clean-new",
        "clean/negative",
        "clean/restored-new",
    ):
        path = f"{stem}-{stage}/"
        assert sorted(z.read(path + "list/outer.stdout").splitlines()) == clean
        result = b"FAILED" if stage == "clean/negative" else b"ok"
        assert (
            b"test " + target + b" ... " + result
            in z.read(path + "execute/outer.stdout").splitlines()
        )


def read_pair(directory, pair, registry, factory, fetch):
    with archive(directory, pair, fetch) as z:
        assert len(z.namelist()) == len(set(z.namelist()))

        def read(path):
            return json.loads(z.read(path))

        enrollment = read(LOGS + "/enrollment.json")
        identity = read(OBS + "/identity.json")
        assert (enrollment["run"], enrollment["head"]) == (
            pair["run"],
            registry["study_sha"],
        )
        assert (
            enrollment["boot"] == identity["boot"]
            and identity["study_mode"] == "matched-rustc"
        )
        order = (
            identity["order"].split(",")
            if pair["suite"] == "build"
            else identity["order"]
        )
        assert order == pair["order"] and set(order) == {"normal", "defer"}
        assert read(LOGS + "/received-compilers.json")["compiler_study"] == factory
        observations = read(OBS + "/observations.json")
        records = {(r["arm"], r["history"], r["phase"]): r for r in observations}
        assert (
            len(records)
            == len(observations)
            == (12 if pair["suite"] == "build" else 16)
        )
        clocks = {}
        for index, arm in enumerate(order):
            check_products(z, f"{OBS}/{index}-{arm}", pair["suite"])
            values = {}
            for phase in PHASES:
                path = f"{OBS}/{index}-{arm}-edit/{phase}"
                row = records[arm, "edit", phase]
                qualified = read(path + "/qualified.json")
                if pair["suite"] == "build":
                    qualified = dict(arm=arm, history="edit", phase=phase, **qualified)
                assert qualified == row
                values[phase] = check_command(z, path, pair["suite"], phase, row)
            clocks[arm] = values
    return enrollment, clocks


def report(directory, fetch):
    registry = json.loads((HERE / "runs.json").read_bytes())
    registration = HERE / "registration.json"
    assert digest(registration) == registry["preregistration_sha256"]
    factory = json.loads((HERE.parent / "factory.json").read_bytes())
    assert (
        factory["run"]
        == registry["factory"]
        == json.loads(registration.read_bytes())["factory_run"]
    )
    boots = set()
    workers = set()
    reductions = []
    edit_and_next = []
    print(
        "Run          Suite    Order         Parent instructions   Candidate instructions   Reduction"
    )
    for pair in registry["pairs"]:
        enrollment, clocks = read_pair(directory, pair, registry, factory, fetch)
        assert enrollment["boot"] not in boots and enrollment["runner"] not in workers
        boots.add(enrollment["boot"])
        workers.add(enrollment["runner"])
        p, c = clocks["normal"], clocks["defer"]
        gain = 100 * (1 - c["new"] / p["new"])
        order = "parent first" if pair["order"][0] == "normal" else "child first"
        print(
            f"{pair['run']}  {pair['suite']:<7}  {order:<12}  {p['new']:>19,}   {c['new']:>22,}   {gain:+.3f}%"
        )
        if pair["suite"] == "build":
            reductions.append(gain)
            edit_and_next.append(
                100 * (1 - (c["new"] + c["unchanged"]) / (p["new"] + p["unchanged"]))
            )
    assert len(boots) == 8 and len(reductions) == 6
    assert (
        sum(
            p["order"][0] == "normal"
            for p in registry["pairs"]
            if p["suite"] == "build"
        )
        == 3
    )
    print(
        f"Build paired median {statistics.median(reductions):.4f}%, range {min(reductions):.4f}–{max(reductions):.4f}%"
    )
    print(f"Edit plus next build paired median {statistics.median(edit_and_next):.4f}%")
    if all(x > 0 for x in reductions) or all(x < 0 for x in reductions):
        print(f"Exact two-sided sign-test p = {2 / 2 ** len(reductions):.5f}")


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Run the verifier with Python assertions enabled")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archives",
        type=Path,
        help="Read existing RUN-ARTIFACT.zip files instead of downloading them",
    )
    args = parser.parse_args()
    if args.archives:
        report(args.archives, False)
    else:
        with tempfile.TemporaryDirectory() as temp:
            report(Path(temp), True)
