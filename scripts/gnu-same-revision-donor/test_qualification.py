"""Negative source, kernel, real unit-inventory and native body controls."""

import argparse, copy, json, os, re, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
import binding as reg
import bootstrap_subject
import donors, events, reopen
import reopen_ruff as reader
import workload as w


class Checks(unittest.TestCase):
    def test_exact_closed_pack_without_candidate_objects(self):
        spec = reader.load(HERE / "inputs/product.json")
        s = spec["source"]
        p = HERE / "inputs/child.pack"
        self.assertEqual(reg.sha(HERE / "inputs/product.json"), reg.SOURCE_RECEIPT)
        self.assertEqual(
            [p.stat().st_size, reg.sha(p)], [spec["pack"]["bytes"], spec["pack"]["sha256"]]
        )
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(["git", "init", "-q", "--bare", repo], check=True)
            key = reg.git(repo, "index-pack", "--stdin", body=p.read_bytes()).decode().split()[1]
            table = (
                reg.git(repo, "verify-pack", "-v", "objects/pack/pack-" + key + ".idx")
                .decode()
                .splitlines()
            )
            actual = sorted(line.split()[0] for line in table if re.match(r"^[0-9a-f]{40} ", line))
            self.assertEqual(actual, s["pack_objects"])
            self.assertEqual(len(actual), 9)
            header = (
                reg.git(repo, "cat-file", "commit", reg.NEW)
                .decode()
                .split("\n\n", 1)[0]
                .splitlines()
            )
            self.assertEqual([x for x in header if x.startswith("parent ")], ["parent " + reg.OLD])
            self.assertIn("tree " + reg.TREE, header)
            self.assertEqual(reg.rev(repo, reg.NEW + "^{tree}"), reg.TREE)
            self.assertEqual(set(s["blobs"]), reg.EXPECTED)
            for path, pair in s["blobs"].items():
                self.assertEqual(pair["candidate"][0], reg.rev(repo, reg.NEW + ":" + path))
                self.assertEqual(
                    pair["candidate"][1],
                    reg.digest(reg.git(repo, "cat-file", "blob", pair["candidate"][0])),
                )

    def test_original_materialized_source(self):
        if PRODUCT is None:
            self.skipTest("complete source is required during actual build after acquisition")
        self.assertEqual(reg.validate(PRODUCT)["pack"]["count"], 9)

    def test_job_scope(self):
        head = "a" * 40
        env = {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REPOSITORY": "astral-experiments/ohm",
            "GITHUB_REF": reg.REF,
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_JOB": "qualify",
            "REVIEWED_HEAD": head,
            "GITHUB_SHA": head,
        }
        with mock.patch.object(
            reg, "rev", lambda _, k: head if k == "HEAD" else reg.CARRIER_PARENT
        ):
            with mock.patch.dict(os.environ, env, clear=True):
                reg.job()
            for k, v in (
                ("GITHUB_REF", "refs/heads/main"),
                ("GITHUB_RUN_ATTEMPT", "2"),
                ("GITHUB_JOB", "other"),
                ("GITHUB_EVENT_NAME", "pull_request"),
                ("REVIEWED_HEAD", "b" * 40),
                ("GITHUB_REPOSITORY", "other/repo"),
            ):
                with self.subTest(k=k), mock.patch.dict(
                    os.environ, env | {k: v}, clear=True
                ), self.assertRaises(ValueError):
                    reg.job()

    def test_actual_test_inventories(self):
        rows = ["test persist::fs::tests::" + n + " ... ok" for n in reg.UNITS]
        summary = "test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
        self.assertEqual(bootstrap_subject.unit_log("\n".join(rows + [summary])), sorted(reg.UNITS))
        for body in (
            "",
            summary,
            "\n".join(rows[:-1] + [summary]),
            "\n".join(rows + [rows[0], summary]),
            "\n".join(rows + [summary.replace("7 passed", "0 passed")]),
        ):
            with self.assertRaises(ValueError):
                bootstrap_subject.unit_log(body)
        for name in reg.RUN_MAKE:
            body = (
                "running 1 tests\ntest [run-make] tests/run-make/"
                + name
                + " ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured"
            )
            reopen.native_pass(body, name)
            for bad in (
                body.replace("1 passed", "0 passed"),
                body.replace(name, "wrong"),
                body.replace(" ... ok", " ... ignored"),
                body + "\ninternal compiler error",
            ):
                with self.assertRaises(ValueError):
                    reopen.native_pass(bad, name)

    def test_authentic_kernel_contacts(self):
        f = HERE / "inputs/controls"
        spec = reader.load(f / "source.json")
        for n, pin in spec["bodies"].items():
            self.assertEqual(
                [(f / n).stat().st_size, reg.sha(f / n), reg.digest(reader.body(f / n))], pin
            )
        cold = reader.body(f / "cold-true.tsv.gz")
        self.assertEqual(len(events.reopen(cold, 0)["execs"]), 1)
        for bad, code in (
            (cold, 1),
            (cold[: cold.rindex(b"OK\t")], 0),
            (cold.replace(b"OK\t", b"BAD\t"), 0),
        ):
            with self.assertRaises(ValueError):
                events.reopen(bad, code)
        raw = reader.body(f / "ruff-before.tsv.gz")
        rd = w.smoke(OBSERVER)
        rows = reader.trace(raw, rd, False, 0)
        ids = {"files": spec["sdk"]}
        actual = reader.role_images(rows, ids, w.CLI)
        self.assertEqual(spec["observations"]["sha256"], reg.digest(raw))
        self.assertEqual([i["name"] for i in actual["comp"]], list(w.OWN))
        self.assertFalse(actual["wild"])
        with self.assertRaises(ValueError):
            reader.trace(raw[: raw.rindex(b"OK\t")], rd, False, 0)
        with self.assertRaises(ValueError):
            reader.role_images(rows, ids, w.CLI[:-1])
        bad = copy.deepcopy(rows)
        next(i for i in bad if "--crate-name" in i["argv"])["argv"].remove("-Zohm-branch-cache=yes")
        with self.assertRaises(ValueError):
            reader.role_images(bad, ids, w.CLI)
        bad = copy.deepcopy(ids)
        bad["files"]["bin/rustc"][2] += 1
        with self.assertRaises(ValueError):
            reader.role_images(rows, bad, w.CLI)

    def test_genuine_parent_donor_fds(self):
        import base64, gzip

        path = HERE / "inputs/controls/actual-parent-donor.json.gz"
        self.assertEqual(
            reg.digest(reader.body(path)),
            "3910635a32879b83fd97c3f6d971a9af9371a3efdf0502be06417b51ff3cfc05",
        )
        record = reader.load(path)
        self.assertTrue(record["complete"])
        self.assertEqual(record["prior_readers"], [])
        self.assertEqual(record["reader_source"], reg.digest(reg.git(
            HERE, "show",
            "d22c1c9d858def79d16332ab147b3ce98f140b2f:scripts/gnu-same-revision-donor/reopen_ruff.py",
        )))
        self.assertEqual(record["raw_info"], [512, 42835069])
        self.assertEqual(
            record["originals_sha256"],
            "744d04823b3156d2bdb096948032bd3396e6adbb03b4f44756eaa41fd139970a",
        )
        raw = {p: base64.b64decode(v, validate=True) for p, v in record["witnessed_files"].items()}
        images = reader.trace(gzip.decompress(raw["kernel.tsv.gz"]), w.smoke(OBSERVER), False, 0)
        ids = reader.load(HERE / "inputs/controls/source.json")["sdk"]
        physical = reader.role_images(images, {"files": ids}, w.CLI)
        selected = [c for c in physical["comp"] if c["mode"] == "compile"]
        self.assertEqual([c["name"] for c in selected], list(w.OWN))
        observed = json.loads(raw["kernel-file-opens.json"])
        registered = json.loads(raw["registered-donors.json"])
        self.assertEqual(donors.verify_opens(registered, observed, selected, "E"), record["opens"])
        wrong = copy.deepcopy(observed)
        wrong["events"][0]["pid"] += 100000
        with self.assertRaises(ValueError):
            donors.verify_opens(registered, wrong, selected, "E")
        wrong = copy.deepcopy(observed)
        wrong["registered"].append(wrong["registered"][0])
        with self.assertRaises(ValueError):
            donors.verify_opens(registered, wrong, selected, "E")
        with self.assertRaises(ValueError):
            donors.verify_opens(registered, observed, selected, "D")
        verify = json.loads(gzip.decompress(raw["live-drivers.json.gz"]))
        for c in selected:
            actual = verify["actual"][str(c["pid"])]
            self.assertEqual(actual["argv"][1:], c["argv"][1:])
            self.assertTrue(actual["maps"])
        self.assertEqual(record["checked_cgu"], 129)
        self.assertEqual(record["checked_executables"], 10)

    def test_original_overlay_refusal_and_same_path_wrong_mappings(self):
        import ast, base64, gzip
        import driver_map

        fixture = reader.load(HERE / "inputs/controls/mapped-driver-contacts.json.gz")
        raw = base64.b64decode(fixture["live_raw_bytes_base64"], validate=True)
        self.assertEqual(reg.digest(raw), fixture["live_sha256"])
        self.assertEqual(fixture["failed_source_run"]["run"], 41301552076)
        self.assertEqual(fixture["failed_source_run"]["head"], reg.CARRIER_PARENT)
        self.assertEqual(
            {(a["id"], a["sha256"]) for a in fixture["failed_source_run"]["artifacts"]},
            {
                (
                    13081547832,
                    "e0687db88c34318a6983fe124867d7a876b8c2530a014ed89a284ec61420fa3a",
                ),
                (
                    13082041115,
                    "9fd2cd8297c1a8ba345616d46a0d8deae2ac6894698bd491fc406f26754a7c8a",
                ),
            },
        )
        self.assertEqual(fixture["selected"][0], reopen.E_DRIVER)
        original = json.loads(gzip.decompress(raw))
        self.assertEqual(original["actual"], {})
        (refusal,) = original["refused"]
        why, line = ast.literal_eval(
            refusal.removeprefix("RuntimeError(").removesuffix(")")
        )
        self.assertEqual(why, "foreign mapped driver")
        path = Path(line.split(maxsplit=5)[5])
        raw_id = driver_map.identity(line, path)[0]
        self.assertEqual(
            (raw_id, tuple(fixture["selected"][1:3])), ((32, 7614425), (33, 7614425))
        )
        for case in fixture["same_path_after_replacement"]:
            before, replacement = case["initial_ref"], case["replaced_ref"]
            self.assertEqual(before["file"][0], replacement["file"][0])
            self.assertNotEqual(before["file"][1:3], replacement["file"][1:3])
            self.assertEqual(before["path"], replacement["path"])
            for proof, observation, accepts in (
                (before, case["actual"], True),
                (replacement, case["new_after_bind"], True),
                (replacement, case["old_after_bind"], False),
            ):
                subject = Path(proof["path"])
                self.assertTrue(
                    all(
                        line.split(maxsplit=5)[5] == str(subject)
                        for line in observation["lines"]
                    )
                )
                args = (
                    proof,
                    subject,
                    proof["file"],
                    observation["ns"],
                    observation["visible"],
                    observation["lines"],
                )
                if accepts:
                    driver_map.check_process(*args)
                else:
                    with self.assertRaisesRegex(
                        ValueError, "different mapped SDK object"
                    ):
                        driver_map.check_process(*args)
            old = case["actual"]
            with self.assertRaises(ValueError):
                driver_map.check_process(
                    before,
                    Path(before["path"]),
                    before["file"],
                    "mnt:[0]",
                    old["visible"],
                    old["lines"],
                )

    def test_live_driver_open_and_replacement(self):
        import ctypes.util
        import shutil
        import driver_map

        # Two copies of one real native library must remain distinguishable even when their bytes agree.
        lib = Path("/usr/lib/x86_64-linux-gnu") / ctypes.util.find_library("z")
        child = "import ctypes,sys; z=ctypes.CDLL(sys.argv[1]); z.zlibVersion.restype=ctypes.c_char_p; print(z.zlibVersion().decode(),flush=True); sys.stdin.readline()"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            selected = root / "lib-donor-contact.so"
            other = root / "second"
            shutil.copyfile(lib, selected)
            shutil.copyfile(lib, other)
            row = lambda: [reg.sha(selected), *driver_map.file_stat(selected.stat())]
            with subprocess.Popen(
                [sys.executable, "-IB", "-c", child, selected],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            ) as proc:
                try:
                    self.assertRegex(proc.stdout.readline(), r"^1\.")
                    pid = Path("/proc") / str(proc.pid)

                    def inspect(proof, current):
                        driver_map.check_process(
                            proof,
                            selected,
                            current,
                            os.readlink(pid / "ns/mnt"),
                            driver_map.file_stat(
                                (pid / "root" / selected.relative_to("/")).stat()
                            ),
                            driver_map.mappings(pid, selected),
                        )

                    original = row()
                    with driver_map.reference(selected, original) as proof:
                        inspect(proof, original)
                    other.replace(selected)
                    replacement = row()
                    self.assertEqual(original[0], replacement[0])
                    self.assertNotEqual(original[1:3], replacement[1:3])
                    with driver_map.reference(selected, replacement) as proof:
                        with self.assertRaises(ValueError):
                            inspect(proof, replacement)
                finally:
                    proc.stdin.close()
                    proc.wait(timeout=10)
                self.assertEqual(proc.returncode, 0)

    def test_original_real_client_search_order(self):
        fixture = HERE / "inputs/controls"
        allrows = [
            json.loads(l)
            for l in reader.body(fixture / "original-cold-cargo.jsonl.gz").splitlines()
        ]
        providers, argv = reader.external_args(
            [r for r in allrows if r["reason"] == "compiler-artifact"]
        )
        self.assertEqual(argv, reader.load(fixture / "real-client-prefix.json"))
        self.assertEqual(set(providers), set(w.OWN) | {"ruff_text_size"})
        dirs = [a.split("=", 1)[1] for a in argv if a.startswith("dependency=")]
        self.assertEqual(len(dirs), 33)
        self.assertNotEqual(sorted(dirs), dirs)

    def test_both_donors_and_negative_inputs(self):
        for role in ("D", "E"):
            rows = {}
            obs = {"registered": [], "events": []}
            comp = []
            for n, own in enumerate(w.OWN):
                rows[own] = {}
                comp.append({"pid": 20 + n, "name": own})
                for s, side in enumerate(("X", "Y")):
                    table = {}
                    for k, kind in enumerate(donors.TABLES):
                        entry = dict(
                            path="/enrolled/" + own + "/" + side + "/ohm-packed-" + kind,
                            dev=84,
                            ino=n * 100 + s * 10 + k + 1,
                            length=50 + k,
                            sha256=reg.digest((own + side + kind).encode()),
                        )
                        table[kind] = entry | {"blocks": 4096}
                        obs["registered"].append(entry)
                        if side == ("Y" if role == "E" else "X"):
                            obs["events"].append(
                                dict(
                                    dev=84,
                                    ino=entry["ino"],
                                    length=entry["length"],
                                    mask=donors.OPEN | donors.ACCESS,
                                    pid=20 + n,
                                )
                            )
                    rows[own][side] = {"tables": table}
            self.assertEqual(set(donors.verify_opens(rows, obs, comp, role)), set(w.OWN))
            with self.assertRaises(ValueError):
                donors.verify_opens(rows, obs, comp, "D" if role == "E" else "E")
            for mutation in (
                "alien_pid",
                "lost_query",
                "wrong_sha",
                "no_read",
                "wrong_size",
                "unmarked",
                "inode_alias",
                "absent_compiler",
            ):
                a, b, c = copy.deepcopy((rows, obs, comp))
                if mutation == "alien_pid":
                    b["events"][0]["pid"] += 50
                elif mutation == "lost_query":
                    b["events"].pop()
                elif mutation == "wrong_sha":
                    b["registered"][0]["sha256"] = "0" * 64
                elif mutation == "no_read":
                    b["events"][0]["mask"] = donors.OPEN
                elif mutation == "wrong_size":
                    b["events"][0]["length"] += 1
                elif mutation == "unmarked":
                    b["registered"].pop()
                elif mutation == "inode_alias":
                    a[w.OWN[0]]["X"]["tables"][donors.TABLES[0]]["ino"] = a[w.OWN[0]]["Y"][
                        "tables"
                    ][donors.TABLES[0]]["ino"]
                else:
                    c.pop()
                with self.subTest(role=role, mutation=mutation), self.assertRaises(ValueError):
                    donors.verify_opens(a, b, c, role)

    def test_wrong_original_body(self):
        with tempfile.TemporaryDirectory() as where:
            where = Path(where)
            data = b"complete original"
            v = w.out.store(where, data)
            self.assertEqual(reader.original(where, v), data)
            with self.assertRaises(ValueError):
                reader.original(where, [v[0] + 1, v[1]])
            (where / (v[1] + ".gz")).write_bytes(__import__("gzip").compress(data + b"!"))
            with self.assertRaises(ValueError):
                reader.original(where, v)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("observer", type=Path)
    ap.add_argument("--product-checkout", type=Path)
    args = ap.parse_args()
    OBSERVER = args.observer.resolve()
    PRODUCT = args.product_checkout
    unittest.main(argv=[sys.argv[0]], verbosity=2)
