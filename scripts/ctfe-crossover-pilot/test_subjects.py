"""Check source admission offline. The optional original mode reopens the native SDK without building."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import subprocess
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ctfe_pilot_subjects", HERE / "subjects.py")
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


def original_metadata():
    repository = {"full_name": s.REPO, "id": 123}
    origin = dict(id=s.RUN, head_sha=s.HEAD, head_branch=s.BRANCH, repository_id=123, head_repository_id=123)
    run = dict(id=s.RUN, head_branch=s.BRANCH, head_sha=s.HEAD, run_attempt=1, event="workflow_dispatch",
               path=".github/workflows/ci.yml", conclusion="success", status="completed",
               repository=repository, head_repository=repository)
    job = dict(id=s.JOB, run_id=s.RUN, head_sha=s.HEAD, head_branch=s.BRANCH, run_attempt=1,
               name="Build and qualify the exact GNU same-revision selector", conclusion="success", status="completed",
               labels=["namespace-profile-ubuntu-24-04-16"], steps=[
                   dict(number=i, name=n, status="completed", conclusion=c) for i, (n, c) in s.STEPS.items()])
    media = dict(total_count=2, artifacts=[
        dict(name=k, id=n, size_in_bytes=z, digest="sha256:"+h, expired=False, workflow_run=origin)
        for k, (n, z, h) in s.ARTIFACTS.items()])
    return run, job, media


class SourceTests(unittest.TestCase):
    def test_source_and_native_workload_must_both_pass(self):
        base = original_metadata()
        self.assertEqual(s.official(*base)["original_workflow"], "success")
        for index, key, value in ((0, "conclusion", "failure"), (0, "run_attempt", 2), (1, "id", s.JOB+1),
                                  (1, "head_sha", "0"*40)):
            with self.subTest(index=index, key=key):
                altered = copy.deepcopy(base)
                altered[index][key] = value
                with self.assertRaises(ValueError):
                    s.official(*altered)
        for step in (11, 12, 13):
            altered = copy.deepcopy(base)
            next(row for row in altered[1]["steps"] if row["number"] == step)["conclusion"] = "skipped"
            with self.assertRaises(ValueError):
                s.official(*altered)

    def test_reject_forged_expired_or_missing_original(self):
        for key, value in (("digest","sha256:"+"0"*64),("size_in_bytes",1),("id",3),("expired",True)):
            with self.subTest(key=key):
                r,j,m = original_metadata()
                m["artifacts"][0][key] = value
                with self.assertRaises(ValueError):
                    s.official(r,j,m)
        r,j,m = original_metadata()
        m["artifacts"].pop()
        with self.assertRaises(ValueError):
            s.official(r,j,m)

    def test_only_registered_regular_members_are_written(self):
        for mode in (stat.S_IFREG, stat.S_IFLNK):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp); payload = b"proof"
                archive = d/"original.zip"
                with zipfile.ZipFile(archive, "x") as z:
                    item=zipfile.ZipInfo("D/native-qualified.json")
                    item.external_attr=(mode|0o644)<<16
                    z.writestr(item, b'{"ok":true}')
                    item=zipfile.ZipInfo("D/overlay/0.zst")
                    item.external_attr=(stat.S_IFREG|0o644)<<16
                    z.writestr(item,payload)
                    # Ineligible archive rows are never joined or passed to an extractor.
                    z.writestr("../wrong",b"foreign")
                index={s.SOURCE_ARTIFACT:(9,archive.stat().st_size,s.sha(archive))}
                allowed={s.SOURCE_ARTIFACT:{name:(len(raw),hashlib.sha256(raw).hexdigest())
                          for name,raw in [("D/native-qualified.json",b'{"ok":true}'),("D/overlay/0.zst",payload)]}}
                with patch.object(s,"ARTIFACTS",index), patch.object(s,"MEMBERS",allowed):
                    if mode==stat.S_IFREG:
                        self.assertEqual(s.unpack({s.SOURCE_ARTIFACT:archive},d/"selected"),{"ok":True})
                        self.assertEqual((d/"selected/D/overlay/0.zst").read_bytes(),payload)
                        with self.assertRaises(FileExistsError):
                            s.unpack({s.SOURCE_ARTIFACT:archive},d/"selected")
                    else:
                        with self.assertRaises(ValueError):
                            s.unpack({s.SOURCE_ARTIFACT:archive},d/"selected")
                    self.assertFalse((d/"wrong").exists())
                    with archive.open("ab") as f:f.write(b"changed")
                    with self.assertRaises(ValueError):
                        s.unpack({s.SOURCE_ARTIFACT:archive},d/"tampered")

    def test_no_unregistered_role_can_move_a_toolchain(self):
        for role, rows in (("Doff",{"E":{},"D":{}}),("Eon",{"E":{}}),("Fon",{"E":{},"D":{}})):
            with self.subTest(role=role), self.assertRaises(ValueError):
                s.activate(role,rows,Path("."))

    def test_activation_binds_both_on_arms_to_own_manifest(self):
        rows = {"E": {}, "D": {}}
        active = Mock(return_value={"CARGO_ENCODED_RUSTFLAGS": "-Zohm-branch-cache=yes"})
        with patch.object(s, "policy", return_value=SimpleNamespace(b=SimpleNamespace(activate=active))):
            for arm in ("Eon", "Don"):
                env = s.activate(arm, rows, Path("/example"))
                self.assertEqual(env["CARGO_ENCODED_RUSTFLAGS"], "-Zohm-branch-cache=yes")
                active.assert_called_with(arm, rows, Path("/example"), permitted=("Eon", "Don"),
                                          source_manifest=s.MANIFEST[arm[0]])

    def test_pilot_and_donor_subjects_have_distinct_modules(self):
        with patch.dict(os.environ, {"RUNNER_TEMP":"/tmp"}):
            old=s.policy()
            self.assertIsNot(s,old.subjects)
            self.assertEqual(Path(old.subjects.__file__).resolve(),s.SCRIPTS/"branch-first-session-e-screen/subjects.py")
            self.assertIs(s.policy(),old)


def acquisition_imports(source):
    """Load the actual pilot, then stop the donor installer at its first GitHub request."""
    source = source.resolve(strict=True)
    call = ["gh", "api", "repos/astral-experiments/ohm/actions/runs/41199659076"]
    check_output = subprocess.check_output

    class AtSourceRequest(Exception):
        pass

    def intercept(argv, *args, **kwargs):
        if argv == call:
            raise AtSourceRequest
        if argv[0] != "git":
            raise AssertionError(("unexpected subprocess before source acquisition", argv))
        return check_output(argv, *args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"RUNNER_TEMP": tmp}):
        worker = runpy.run_path(str(HERE / "pilot.py"))
        previous = worker["subjects"].policy()
        assert previous.b.OUT.is_relative_to(Path(tmp).resolve())
        previous.b.OUT.mkdir(parents=True)
        with patch.object(subprocess, "check_output", intercept), unittest.TestCase().assertRaises(AtSourceRequest):
            previous.acquire(source)
        prior = sys.modules["prior"]
        old = source / "scripts/branch-return-source"
        assert Path(prior.__file__) == source / "scripts/branch-first-session-e-source/prior.py"
        for mod in (prior.s.reg, prior.locate, prior.old):
            assert Path(mod.__file__).parent == old
        assert prior.need is prior.s.reg.need and prior.s.reg is not worker["reg"]
        assert not any(previous.b.OUT.rglob("*.json")) and not previous.b.PARK.exists()
        print(json.dumps({"source": previous.checked_source.HEAD, "donor_registration": str(prior.s.reg.__file__),
                          "pilot_registration": str(worker["reg"].__file__), "intercepted_before_exec": call}))


def actual(archive_dir, official_path, original_e, scratch):
    original=json.loads(official_path.read_bytes())
    proof=s.official(original["run"],original["job"],original["artifacts"])
    archives={name:archive_dir/(str(row["id"])+"-"+name+".zip") for name,row in proof["artifacts"].items()}
    with tempfile.TemporaryDirectory(dir=scratch) as tmp, patch.dict(os.environ,{"RUNNER_TEMP":str(scratch)}):
        d=Path(tmp);transfer=d/"receipt";native=s.unpack(archives,transfer)
        b=s.policy().b
        parent=b.inventory(original_e)
        candidate=s.reconstruct(transfer,native,parent,original_e,d/"candidate",b)
        records={r:json.loads((transfer/"sdk"/(r+".json")).read_bytes()) for r in ("E","D")}
        wrong=copy.deepcopy(records);wrong["D"]["files"]["bin/cargo"][0]="0"*64
        with unittest.TestCase().assertRaises(ValueError):
            s.classify(parent,wrong,native)
        return {"run":proof["run"],"original_conclusion":proof["original_workflow"],
                "source":candidate["source"],"members":len(candidate["files"]),"shared_inodes":0,
                "driver":candidate["files"][s.DRIVER][0],"cargo":candidate["files"]["bin/cargo"][0],
                "wild":candidate["files"][b.WILD][0],"corrupted_cargo_refused":True}


if __name__=="__main__":
    if sys.argv[1:2]==["--acquisition-imports"]:
        acquisition_imports(Path(sys.argv[2]))
    elif sys.argv[1:2]==["--originals"]:
        print(json.dumps(actual(*map(Path,sys.argv[2:])),sort_keys=True))
    else:
        unittest.main()
