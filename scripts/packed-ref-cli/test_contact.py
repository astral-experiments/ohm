"""Replay source, native Cargo/SDK and physical donor positives; mutate each corresponding guard."""

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ctfe-crossover-pilot")]
import endpoints
import git_layout as git
import packed_donor as donors
import packed_sdk as sdk
import packed_watches as watches
import review


def fixture(name, expected=None):
    raw = gzip.decompress((HERE / "inputs" / (name + ".json.gz")).read_bytes())
    if expected:
        sdk.need(hashlib.sha256(raw).hexdigest() == expected, "foreign test original")
    return json.loads(raw)


def replace_label(path, old, new):
    prev = f"_r{old}_" if old else "_"
    curr = f"_r{new}_" if new else "_"
    parent, name = path.rsplit("/", 1)
    result, n = re.subn(r"(?<=_[a-f0-9]{16})" + prev, curr, name, count=1)
    sdk.need(n == 1, "the test control did not change the true session name")
    return parent + "/" + result


def inputs(role):
    # Adapt labels only on two real Ruff sessions to exercise prospective D/P registration.
    # The separately checked original kernel event fixture retains all original names.
    rec = fixture("original-fanotify")["sides"]["Don"]
    first = {"source": {"revision": git.B, "ref": git.Y}, "sessions": {}}
    second = {"source": {"revision": git.A, "ref": git.X}, "sessions": {}}
    for owner, sides in rec["donor-register"].items():
        for slot, rev in (
            ("Y", None if role == "D" else git.B[:16]),
            ("X", git.A[:16]),
        ):
            row = deepcopy(sides[slot])
            path = sides[slot + "_path"]
            newpath = (
                path
                if rev == row["revision"]
                else replace_label(path, row["revision"], rev)
            )
            row["revision"] = rev
            for table in row["tables"].values():
                table["path"] = newpath + "/" + table["path"].rsplit("/", 1)[1]
            second["sessions"][newpath] = row
            if slot == "Y":
                first["sessions"][newpath] = row
    work = Path(sides["Y_path"].split("/target/debug/incremental/")[0])
    return first, second, work, rec["X-B"]


class Cases(unittest.TestCase):
    def test_original_sdks(self):
        refs = {
            r: fixture("original-sdk-" + r, h)
            for r, h in zip(
                "DP",
                (
                    "8a4a285665d939bb3b5874e36833f04246203dc016c5653eac5b56dde6677c97",
                    "3f7efad9e49e7557673b0837e8388b079671b0eb272a3e5bbcfb140250e0f3dc",
                ),
                strict=True,
            )
        }
        self.assertEqual(sdk.verify_pair(refs), refs)
        changes = [
            lambda r: r["P"]["files"].pop("bin/cargo"),
            lambda r: r["P"]["files"].__setitem__(
                "bin/cargo", r["D"]["files"]["bin/cargo"]
            ),
            lambda r: r["P"]["files"][sdk.DRIVER].__setitem__(
                0, r["D"]["files"][sdk.DRIVER][0]
            ),
            lambda r: r["D"].__setitem__("source", sdk.P),
        ]
        for fn in changes:
            other = deepcopy(refs)
            fn(other)
            with self.assertRaises(ValueError):
                sdk.verify_pair(other)

    def test_true_cargo_and_allocated_stream(self):
        sample = fixture("original-output-layout")
        self.assertEqual(
            (sample["checks"], len(set(sample["phases"])), sample["official"]["run"]),
            (46, 46, 41312535998),
        )
        for phase, row, art, relative, physical, *_ in sample["native_examples"]:
            target = Path(row["out_dir"].split("/work/target/")[0])
            work = target / "work"

            def locate(r, arts=art):
                return watches.output_location(
                    [r, *arts],
                    target / "ruff",
                    work,
                    invalid=phase.endswith("/invalid"),
                )

            pkg, path, env = locate(row)
            self.assertEqual(
                (pkg, path, env), (row["package_id"], work / relative, row["env"])
            )
            self.assertEqual(
                watches.census_file({relative: physical}, path, work, physical[5]),
                [physical[0], physical[1], physical[5], physical[4] * 512],
            )
            for wrong in [
                str(work / "target/debug/build/ruff-0123456789abcdef/out"),
                str(path.parent / "out"),
                str(path) + "/../out",
            ]:
                with self.assertRaises(ValueError):
                    locate(row | {"out_dir": wrong})
            with self.assertRaises((ValueError, KeyError)):
                watches.census_file({relative: physical}, path, work, physical[5] + 1)
            with self.assertRaises(ValueError):
                watches.output_location(
                    [row, row, *art], target / "ruff", work, invalid=False
                )
            if not phase.endswith("/invalid"):
                with self.assertRaises(ValueError):
                    locate(
                        row
                        | {
                            "package_id": row["package_id"].replace(
                                "/crates/ruff#", "/crates/another#"
                            )
                        }
                    )
        self.assertIsNone(
            watches.output_location([], Path("/ruff"), Path("/work"), invalid=True)
        )

    def test_original_public_git_stdout(self):
        sample = fixture(
            "native-git-layout",
            "fa36de7783be82cb9538de88009336dc4d2c15aa5aea029d803ad7e1defc2095",
        )
        root = Path(sample["validated_path"])
        for phase, r in sample["roles"].items():
            raw = bytes.fromhex(r["stdout"])
            state = r["git"]
            revision = state["revision"]
            git.verify_snapshot(state, state["ref"], revision)
            row = (
                "original-test-package",
                Path("/work/run/stdout"),
                [["RUFF_COMMIT_HASH", revision]],
            )
            self.assertEqual(
                watches.verify_raw(raw, state, root, row)["validated"], r["parsed"]
            )
            with self.assertRaises(ValueError):
                watches.verify_raw(
                    raw, state, root, (row[0], row[1], [["RUFF_COMMIT_HASH", "0" * 40]])
                )
            if phase == "Y-B":
                with self.assertRaises(ValueError):
                    watches.verify_raw(
                        raw.replace(b"packed-refs", b"refs/heads/historical-feature"),
                        state,
                        root,
                        row,
                    )

    def test_physical_opens_and_roles(self):
        originals = fixture(
            "original-fanotify",
            "efdb13da48df9d2de03945db3e67d495cbbb98143a8f201c79ee0f4ab184ea6b",
        )
        for previous, side in (("Don", "X"), ("Eon", "Y")):
            a = originals["sides"][previous]
            a1, events, rows = a["donor-register"], a["donor-opens"], a["compilers"]

            def opens(e, s):
                return donors.dw.donors.verify_opens(
                    a1, e, rows, previous[0], expected_side=s
                )

            self.assertEqual(opens(events, side), a["donor-selected"])
            with self.assertRaises(ValueError):
                opens(events, "Y" if side == "X" else "X")
            other = deepcopy(events)
            other["events"][0]["pid"] += 100000
            with self.assertRaises(ValueError):
                opens(other, side)

    def test_x_a_y_b_registration(self):
        for role in "DP":
            first, second, work, rows = inputs(role)
            reg = donors.register(first, second, role, work)
            self.assertEqual(set(reg), set(donors.dw.OWN))
            donors.bind_sources(reg, rows)
            self.assertEqual(
                reg["ruff_python_ast"]["Y"]["revision"],
                None if role == "D" else git.B[:16],
            )
            with self.assertRaises(ValueError):
                donors.register(first, second, "D" if role == "P" else "P", work)
            with self.assertRaises((ValueError, RuntimeError)):
                donors.bind_sources(reg, rows[:1])
            tampered = deepcopy(second)
            _, r = next(
                (k, v)
                for k, v in tampered["sessions"].items()
                if k not in first["sessions"]
            )
            r["tables"]["dep-graph.bin"]["path"] = r["tables"]["query-cache.bin"][
                "path"
            ]
            with self.assertRaises(ValueError):
                donors.register(first, tampered, role, work)

    def test_actual_clocks_and_failed_command(self):
        source = fixture(
            "original-clock-sequences",
            "2335081b6c420d40b0a0f3a34077b492e6f0fff25c1b479d7a562a5f0bef9cb8",
        )
        for values in source["sequences"].values():
            original = {p: values[p] for p in endpoints.PHASES}
            sums = endpoints.count(original)
            self.assertEqual(
                sums["whole7"]["instructions"],
                sum(v["instructions"] for v in original.values()),
            )
            self.assertEqual(
                sums["whole7"]["elapsed_ns"],
                sum(v["stop"] - v["start"] for v in original.values()),
            )
            self.assertEqual(sums["phases"]["invalid"]["status"], 101)
            for p, k, value in [
                ("invalid", "code", 0),
                ("X-B", "instructions", 0),
                ("repair", "start", 1),
                ("X-A", "running", 1),
            ]:
                other = deepcopy(original)
                other[p][k] = value
                with self.assertRaises(ValueError):
                    endpoints.count(other)
            short = deepcopy(original)
            short["X-B"].update(running=999, enabled=1000)
            with self.assertRaises(ValueError):
                endpoints.count(short)
            with self.assertRaises(ValueError):
                endpoints.count(dict(reversed(original.items())))

    def test_collision_denominator(self):
        ex = sdk.read(HERE / "excluded-hosts.json")
        s = ex["concurrent"]
        names = [f"{i:02d}" for i in range(1, 7)]
        hosts = {
            p: dict(
                run=s["run"],
                head=s["head"],
                job=j,
                position=p,
                boot="sample-boot-" + p,
                runner="sample-runner-" + p,
                runner_id=20 + i,
            )
            for i, (p, j) in enumerate(zip(names, s["job_ids"], strict=True))
        }
        cert = dict(
            run=s["run"],
            head=s["head"],
            hosts=hosts,
            admitted=True,
            missing=[],
            outcomes_opened=0,
            reason=None,
        )
        current = {"job": 1, "runner": "sample-other", "runner_id": 1}
        with tempfile.TemporaryDirectory() as folder:
            dst = Path(folder) / "admission.json"

            def check(obj, where, new=current):
                raw = json.dumps(obj).encode()
                dst.write_bytes(raw)
                return review.concurrent_hosts(
                    ex, new, {"boot": where}, dst, hashlib.sha256(raw).hexdigest()
                )

            self.assertEqual(check(cert, "different")["hosts"], 6)
            for field, value in (
                ("boot", hosts["01"]["boot"]),
                ("runner", hosts["02"]["runner"]),
                ("job", hosts["03"]["job"]),
                ("runner_id", hosts["04"]["runner_id"]),
            ):
                with self.assertRaises(ValueError):
                    check(
                        cert,
                        value if field == "boot" else "different",
                        current | {field: value},
                    )
            with self.assertRaises(ValueError):
                check(cert | {"outcomes_opened": 1}, "different")
            with self.assertRaises(ValueError):
                check(
                    cert | {"hosts": {k: v for k, v in hosts.items() if k != "06"}},
                    "different",
                )

    def test_complete_exec_and_bad_bytes(self):
        exe = Path("/usr/bin/true").read_bytes()
        name = hashlib.sha256(exe).hexdigest()
        compressed = subprocess.check_output(
            ["zstd", "-q", "-1", "--stdout"], input=exe
        )
        stream = io.BytesIO()
        with ZipFile(stream, "w") as z:
            z.writestr(f"native-bodies/{name}.zst", compressed)
            z.writestr(f"native-bodies/{'0' * 64}.zst", compressed)
        with ZipFile(stream) as z:
            self.assertEqual(
                len(review.execute(z, {("reader", name, None): (len(exe), b"")})), 1
            )
            with self.assertRaises(ValueError):
                review.execute(z, {("reader", name, None): (len(exe), b"wrong")})
            with self.assertRaises(ValueError):
                review.execute(z, {("reader", "0" * 64, None): (len(exe), b"")})


def prior_native(path):
    with path.open("rb") as f:
        sdk.need(
            hashlib.file_digest(f, "sha256").hexdigest()
            == "aeef5d5226815f3d5cd8a11210a1f2265ee1291214e5e885eddee1dc2c3cbb65",
            "wrong complete historical CLI original",
        )
    with ZipFile(path) as z:
        key = "clean/Foff/B"
        old = review.get(z, key + "/native.json.gz")

        def records(edited):
            return {
                (k, old[k]["whole"], edited if k == "cli" else None): (
                    old[k]["size"],
                    b""
                    if k == "cli"
                    else gzip.decompress(z.read(key + "/reader-run.stdout.gz")),
                )
                for k in ("cli", "reader")
            }

        print(json.dumps(review.execute(z, records(False)), sort_keys=True))
        try:
            review.execute(z, records(True))
        except (ValueError, RuntimeError):
            return
        raise ValueError(
            "genuine unedited historical CLI passed as a different program"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-checkout", type=Path)
    parser.add_argument("--prior-native", type=Path)
    options = parser.parse_args()
    if options.source_checkout:
        subprocess.run(
            [
                sys.executable,
                "-IB",
                HERE / "receive_p.py",
                "--source-preflight",
                options.source_checkout,
            ],
            check=True,
        )
    if options.prior_native:
        prior_native(options.prior_native)
    unittest.main(argv=[sys.argv[0]])
