"""Exercise source binding, real stock assembly and both native admissions without a distribution download."""

import copy
import gzip
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import prepare
import receive as r
import verify as v


def inputs():
    targets = v.TARGETS
    identity = {"full_name": r.REPO, "id": r.REPO_ID}
    run = {
        "id": r.RUN,
        "run_attempt": 1,
        "head_sha": r.PROVIDER,
        "head_branch": r.SOURCE_BRANCH,
        "event": "workflow_dispatch",
        "path": ".github/workflows/ci.yml",
        "repository": identity,
        "head_repository": identity,
        "status": "completed",
        "conclusion": "success",
    }
    jobs = []
    for i, (key, label) in enumerate(r.JOBS.items()):
        role = key.split("/")[0]
        steps = list(r.BASE_STEPS[role])
        if role == "build":
            steps.insert(
                2,
                "Install pinned LLVM BOLT tools"
                if key.endswith(targets[0])
                else "Install matching LLVM tools for native PGO",
            )
            steps.insert(5, "Capture macOS compiler crash")
        jobs.append(
            {
                "id": r.PLAN if role == "plan" else r.BUILD.get(key.removeprefix("build/"), 1000 + i),
                "name": label,
                "head_sha": r.PROVIDER,
                "run_id": r.RUN,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "steps": [
                    {
                        "name": x,
                        "status": "completed",
                        "conclusion": "skipped" if x == "Capture macOS compiler crash" else "success",
                    }
                    for x in steps
                ],
            }
        )
    assets = []
    for i, n in enumerate(
        [
            v.TOOLCHAIN + "-global",
            *[p + t for p in (v.TOOLCHAIN + "-", "rc23-final-source-") for t in targets],
        ]
    ):
        assets.append(
            {
                "name": n,
                "id": 300 + i,
                "size_in_bytes": 20 + i,
                "expired": False,
                "digest": "sha256:" + v.sha(n.encode()),
                "workflow_run": {
                    "id": r.RUN,
                    "head_sha": r.PROVIDER,
                    "head_branch": r.SOURCE_BRANCH,
                    "head_repository_id": r.REPO_ID,
                    "repository_id": r.REPO_ID,
                },
            }
        )
    return [run, {"total_count": len(jobs), "jobs": jobs}, {"total_count": len(assets), "artifacts": assets}]


def original(rows):
    f = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(f, "w") as z:
        warnings.simplefilter("ignore", UserWarning)
        for name, b, mode in rows:
            item = zipfile.ZipInfo(name)
            item.create_system = 3
            item.external_attr = mode << 16
            z.writestr(item, b)
    return zipfile.ZipFile(io.BytesIO(f.getvalue()))


class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "coordinator"
        subprocess.run(["git", "init", "-q", cls.root], check=True)
        repo = HERE.parents[1]
        common = subprocess.check_output(
            ["git", "-C", repo, "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True
        ).strip()
        (cls.root / ".git/objects/info/alternates").write_text(common + "/objects\n")
        subprocess.run(["git", "-C", cls.root, "update-ref", "--no-deref", "HEAD", v.COORDINATOR], check=True)
        for name in (v.MANIFEST, "scripts/install.sh", "scripts/assemble-release.sh"):
            f = cls.root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(subprocess.check_output(["git", "-C", repo, "show", v.COORDINATOR + ":" + name]))
        cls.manifest = v.coordinator(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def reject(self, func, *args):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            func(*args)

    def test_genuine_manifest_and_component_source(self):
        d = v.coordinator(self.root)
        self.assertEqual(d["sources"]["rust"]["revision"], "a3fc6da13921586bc374586dee00883e9210aecd")
        original_path = self.root / v.MANIFEST
        raw = original_path.read_bytes()
        self.assertEqual(v.sha(raw), v.MANIFEST_SHA)
        try:
            original_path.write_bytes(raw.replace(v.SOURCES["rust"].encode(), prepare.OLD.encode()))
            self.reject(v.coordinator, self.root)
        finally:
            original_path.write_bytes(raw)

    def test_published_predecessor_rejects_rc_and_swapped_media(self):
        def blob(commit, path):
            return subprocess.check_output(["git", "-C", self.root, "show", commit + ":" + path])

        manifest = blob(prepare.LEGACY, prepare.PUBLISHED + "22.json")
        release = json.loads(blob(prepare.LEGACY, prepare.PUBLISHED + "published-assets.json"))
        actors = json.loads(blob(prepare.SUITES, prepare.BASE + "published-actors.json"))
        checked = prepare.published_predecessor(manifest, release, actors)
        self.assertEqual(checked["sources"], prepare.PUBLISHED_PINS)
        self.assertEqual(set(checked["archives"]), set(v.TARGETS))

        for before, after in (
            (prepare.PUBLISHED_PINS["rust"], "556a8364f1485a03be31b1a50c250d63198a943d"),
            (prepare.PUBLISHED_PINS["cargo"], "8269d772aa1ef02e5efaa331dfb40eb55d71f719"),
        ):
            rc_manifest = manifest.replace(before.encode(), after.encode())
            self.reject(prepare.published_predecessor, rc_manifest, release, actors)
        self.reject(prepare.published_predecessor, manifest, release | {"id": 13057710231}, actors)
        swapped = {v.TARGETS[0]: actors[v.TARGETS[1]], v.TARGETS[1]: actors[v.TARGETS[0]]}
        self.reject(prepare.published_predecessor, manifest, release, swapped)
        duplicate = copy.deepcopy(release)
        duplicate["assets"].append(checked["archives"][v.TARGETS[0]])
        self.reject(prepare.published_predecessor, manifest, duplicate, actors)

    def test_exact_source_receipt_and_substitutions(self):
        t = v.TARGETS[1]
        protocol = json.loads((HERE / "provider-source.json").read_bytes())
        trees = {k: {"revision": row["end"], "tree": row["tree"]} for k, row in protocol["sources"].items()}
        src = {
            "target": t,
            "source_trees": trees,
            "manifest": self.manifest,
            "coordinator": v.COORDINATOR,
            "manifest_sha256": v.MANIFEST_SHA,
            "workflow": r.PROVIDER,
            "run": str(r.RUN),
            "attempt": "1",
        }

        def compare(data):
            with original(
                [
                    (r.SOURCE, json.dumps(data).encode(), stat.S_IFREG),
                    (r.SLOT, b"prior transport", stat.S_IFREG),
                ]
            ) as z:
                return r.native_source(z, self.manifest, t)

        self.assertEqual(compare(src)["source_trees"], trees)
        # Both native jobs used the same Rust and Cargo. Preserve their distinct formatter and package.
        earlier = copy.deepcopy(src)
        earlier["source_trees"]["rustfmt"]["revision"] = "4b772602480c276b46cd51d44ae3ac0770ca81f5"
        self.reject(compare, earlier)
        self.reject(compare, src | {"coordinator": "201eb25ab858598493d22e0d0f9cbe743e1ef60c"})
        self.reject(compare, src | {"run": "41348186330"})
        for field, val in (
            ("target", v.TARGETS[0]),
            ("attempt", "2"),
            ("manifest_sha256", "0" * 64),
            ("workflow", v.COORDINATOR),
        ):
            self.reject(compare, src | {field: val})
        changed = copy.deepcopy(src)
        changed["source_trees"]["rust"]["revision"] = prepare.OLD
        self.reject(compare, changed)

    def test_complete_original_workflow_only(self):
        good = inputs()
        self.assertEqual(r.official(*good)["jobs"]["build/" + v.TARGETS[1]], r.BUILD[v.TARGETS[1]])
        for mutate in (
            lambda x: x[0].update(run_attempt=2),
            lambda x: x[0].update(status="in_progress"),
            lambda x: x[0].update(conclusion="failure"),
            lambda x: x[0].update(head_sha=v.COORDINATOR),
            lambda x: x[0]["repository"].update(id=1),
            lambda x: x[1]["jobs"].pop(),
            lambda x: x[1]["jobs"][2].update(id=1),
            lambda x: next(
                s
                for j in x[1]["jobs"]
                for s in j["steps"]
                if s["name"] == "Build optimized extended Rust distribution"
            ).update(conclusion="skipped"),
            lambda x: next(
                s for j in x[1]["jobs"] for s in j["steps"] if s["name"] == "Smoke test Ohm toolchain"
            ).update(conclusion="failure"),
            lambda x: x[2]["artifacts"].pop(),
            lambda x: x[2]["artifacts"][0].update(expired=True),
            lambda x: x[2]["artifacts"][0].update(id=x[2]["artifacts"][1]["id"]),
            lambda x: x[2]["artifacts"][0]["workflow_run"].update(head_sha=v.COORDINATOR),
        ):
            bad = copy.deepcopy(good)
            mutate(bad)
            self.reject(r.official, *bad)

    def test_upload_job_binds_digest_length_and_id(self):
        a = {"id": 123, "bytes": 77, "sha256": "1" * 64}
        name = v.TOOLCHAIN + "-" + v.TARGETS[1]
        lines = [
            "SHA256 digest of uploaded artifact is " + a["sha256"],
            f"Artifact {name} successfully finalized. Artifact ID 123",
            f"Artifact {name} has been successfully uploaded! Final size is 77 bytes. Artifact ID is 123",
            f"Artifact download URL: https://github.com/{r.REPO}/actions/runs/{r.RUN}/artifacts/123",
        ]
        r.upload(lines, name, a)
        for bad in (
            lines[:1] + lines,
            lines + lines[2:3],
            lines[:-1],
            lines[:2] + [lines[2].replace("77", "78")] + lines[3:],
            [lines[0].replace("111", "222")] + lines[1:],
        ):
            self.reject(r.upload, bad, name, a)

    def test_zip_members_and_aliases(self):
        reg = stat.S_IFREG | 0o644
        with original([("wanted", b"ok", reg)]) as z:
            self.assertEqual(set(r.members(z, {"wanted": 2})), {"wanted"})
        for rows in (
            [("wanted", b"ok", reg)] * 2,
            [("../wanted", b"x", reg)],
            [("wanted", b"x", stat.S_IFLNK | 0o777)],
            [("wanted", b"long", reg)],
            [("wanted", b"x", reg), ("extra", b"x", reg)],
            [],
        ):
            with original(rows) as z:
                self.reject(r.members, z, {"wanted": 2})

    def test_real_stock_assembly_and_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            combined = work / "combined"
            combined.mkdir()
            for t in v.TARGETS:
                s = v.TOOLCHAIN + "-" + t
                p = {
                    "schema_version": 1,
                    "toolchain": v.TOOLCHAIN,
                    "target": t,
                    "bundled_tools": self.manifest["bundled_tools"] if t == v.TARGETS[0] else {},
                    "coordinator": {"repository": r.REPO, "revision": v.COORDINATOR},
                    "manifest": {"path": v.MANIFEST, "sha256": v.MANIFEST_SHA},
                    "sources": {k: {"revision": val} for k, val in v.SOURCES.items()},
                }
                for name, raw in (
                    (s + ".tar.gz", gzip.compress(t.encode(), mtime=0)),
                    (s + "-provenance.json", json.dumps(p).encode()),
                ):
                    (combined / name).write_bytes(raw)
                    (combined / (name + ".sha256")).write_text(v.sha(raw) + "  " + name + "\n")
            subprocess.run(
                [
                    "bash",
                    self.root / "scripts/assemble-release.sh",
                    self.root / v.MANIFEST,
                    combined,
                    v.TOOLCHAIN,
                ],
                cwd=work,
                capture_output=True,
                check=True,
            )
            for t in v.TARGETS:
                release = work / t
                release.mkdir()
                for n in v.GLOBAL | v.names(t):
                    shutil.copyfile(combined / n, release / n)
                self.assertEqual(len(v.staged(self.root, release, t)["files"]), 7)
                self.reject(v.staged, self.root, release, next(other for other in v.TARGETS if other != t))
                installer = release / "ohm-installer.sh"
                old = installer.read_bytes()
                installer.write_bytes(old + b"echo altered\n")
                sums = release / "SHA256SUMS"
                previous = sums.read_bytes()
                sums.write_bytes(previous.replace(v.sha(old).encode(), v.digest(installer).encode()))
                self.reject(v.staged, self.root, release, t)
                installer.write_bytes(old)
                sums.write_bytes(previous)
                body = release / (v.TOOLCHAIN + "-" + t + "-provenance.json")
                bad = body.read_bytes().replace(v.COORDINATOR.encode(), r.PROVIDER.encode())
                prev = v.digest(body)
                body.write_bytes(bad)
                (release / (body.name + ".sha256")).write_text(v.sha(bad) + "  " + body.name + "\n")
                sums.write_bytes(previous.replace(prev.encode(), v.sha(bad).encode()))
                self.reject(v.staged, self.root, release, t)

    def test_hosted_only(self):
        with patch.dict("os.environ", {}, clear=True):
            self.reject(r.hosted, self.root, v.TARGETS[0], self.root / "out", self.root / "report")

    def test_failed_stream_retained_without_poisoning_retry_or_raw_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            dest = folder / "official.zip"
            raw = b"authenticated transport"
            row = {"id": 1, "bytes": len(raw), "sha256": v.sha(raw)}

            def cmd(data):
                return [sys.executable, "-c", "import sys;sys.stdout.buffer.write(" + repr(data) + ")"]

            with patch("receive.endpoint", return_value=cmd(b"!" * len(raw))):
                self.reject(r.download, "unused", row, dest, 0)
            self.assertFalse(dest.exists())
            (partial,) = folder.glob("official.zip.partial-*")
            self.assertEqual(partial.read_bytes(), b"!" * len(raw))
            with patch("receive.endpoint", return_value=cmd(raw)):
                r.download("unused", row, dest, 0)
            self.assertEqual(dest.read_bytes(), raw)
            self.assertTrue(partial.exists())
            rawlog = b"\x1b[36moriginal\x1b[0m\n"
            if shutil.disk_usage(folder).free >= (512 * r.MIB) + len(rawlog):
                with patch("receive.endpoint", return_value=cmd(rawlog)):
                    self.assertEqual(r.log("unused", 1, folder / "job.log.gz"), rawlog)
                self.assertEqual(gzip.decompress((folder / "job.log.gz").read_bytes()), rawlog)

    def test_reviewed_native_host_rejects_wrong_cpu_ref_job_or_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            report = base / "rc23-final-reports"
            report.mkdir()
            work = base / "rc23-original"
            ev = base / "event.json"
            candidate = "8" * 40
            ev.write_text(
                json.dumps({"inputs": {"reviewed_head": candidate}, "repository": {"full_name": r.REPO}})
            )
            env = {
                "GITHUB_ACTIONS": "true",
                "GITHUB_REPOSITORY": r.REPO,
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_JOB": "native",
                "GITHUB_REF": "refs/heads/" + r.BRANCH,
                "GITHUB_EVENT_PATH": str(ev),
                "GITHUB_SHA": candidate,
                "GITHUB_WORKSPACE": str(self.root),
                "RUNNER_OS": "Linux",
                "RUNNER_TEMP": str(base),
            }
            with (
                patch("receive.head", return_value=candidate),
                patch("platform.system", return_value="Linux"),
                patch("platform.machine", return_value="x86_64"),
            ):
                with patch.dict("os.environ", env, clear=True):
                    r.hosted(self.root, v.TARGETS[0], work, report)
                    self.reject(r.hosted, self.root, v.TARGETS[1], work, report)
                    self.reject(r.hosted, self.root, v.TARGETS[0], base / "other", report)
                for name, val in (
                    ("GITHUB_RUN_ATTEMPT", "2"),
                    ("GITHUB_JOB", "build"),
                    ("GITHUB_REF", "refs/heads/main"),
                    ("GITHUB_SHA", "1" * 40),
                    ("RUNNER_OS", "macOS"),
                ):
                    with patch.dict("os.environ", env | {name: val}, clear=True):
                        self.reject(r.hosted, self.root, v.TARGETS[0], work, report)

    def test_stored_zip_must_still_match_official_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "original.zip"
            raw = b"authenticated bytes"
            f.write_bytes(raw)
            row = {"id": 1, "bytes": len(raw), "sha256": v.sha(raw)}
            # No network should be contacted on this verified reopen.
            r.download("not-a-command", row, f, 0)
            f.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            self.reject(r.download, "not-a-command", row, f, 0)
            self.reject(r.download, "not-a-command", row | {"bytes": len(raw) + 1}, f, 0)

    def test_prior_installer_code_must_match_original_line_once(self):
        row = '    "candidate": ("' + prepare.OLD + '", "' + v.SOURCES["cargo"] + '"),'
        self.assertIn(v.SOURCES["rust"].encode(), prepare.candidate_installer_checks(row.encode()))
        for bad in (b"", row.replace("candidate", "prior").encode(), (row + "\n" + row).encode()):
            self.reject(prepare.candidate_installer_checks, bad)

    def test_source_matched_cross_rows_and_old_fixture_refusal(self):
        with patch.dict(sys.modules):
            sys.path.insert(0, str(HERE / "cross"))
            try:
                import check

                self.assertEqual(check.sources(), {"gnu": [31, 8], "musl": [13, 3]})
                self.reject(check.markers, (check.V1 + "\n").encode(), True)
                self.reject(check.markers, (check.V2 + "\n" + check.BAD + "\n").encode(), True)
            finally:
                sys.path.pop(0)


if __name__ == "__main__":
    unittest.main()
