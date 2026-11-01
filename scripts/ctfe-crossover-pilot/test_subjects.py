"""Check source admission offline. The optional original mode reopens the native SDK without building."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
               path=".github/workflows/ci.yml", conclusion="failure", status="completed",
               repository=repository, head_repository=repository)
    job = dict(id=s.JOB, run_id=s.RUN, head_sha=s.HEAD, head_branch=s.BRANCH, run_attempt=1,
               name="GNU compiler and ordinary Ruff allocation identity", conclusion="failure", status="completed",
               labels=["namespace-profile-ubuntu-24-04-16"], steps=[
                   dict(number=i, name=n, status="completed", conclusion=c) for i, (n, c) in s.STEPS.items()])
    media = dict(total_count=2, artifacts=[
        dict(name=k, id=n, size_in_bytes=z, digest="sha256:"+h, expired=False, workflow_run=origin)
        for k, (n, z, h) in s.ARTIFACTS.items()])
    return run, job, media


class SourceTests(unittest.TestCase):
    def test_source_success_and_workload_failure_are_separate(self):
        base = original_metadata()
        self.assertEqual(s.official(*base)["original_workflow"], "failure")
        for index, key, value in ((0, "conclusion", "success"), (0, "run_attempt", 2), (1, "id", s.JOB+1),
                                  (1, "head_sha", "0"*40)):
            with self.subTest(index=index, key=key):
                altered = copy.deepcopy(base)
                altered[index][key] = value
                with self.assertRaises(ValueError):
                    s.official(*altered)
        for step in (10, 11):
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
                    item=zipfile.ZipInfo("C/native-qualified.json")
                    item.external_attr=(mode|0o644)<<16
                    z.writestr(item, b'{"ok":true}')
                    item=zipfile.ZipInfo("C/overlay/0.zst")
                    item.external_attr=(stat.S_IFREG|0o644)<<16
                    z.writestr(item,payload)
                    # Ineligible archive rows are never joined or passed to an extractor.
                    z.writestr("../wrong",b"foreign")
                index={s.SOURCE_ARTIFACT:(9,archive.stat().st_size,s.sha(archive))}
                allowed={s.SOURCE_ARTIFACT:{name:(len(raw),hashlib.sha256(raw).hexdigest())
                          for name,raw in [("C/native-qualified.json",b'{"ok":true}'),("C/overlay/0.zst",payload)]}}
                with patch.object(s,"ARTIFACTS",index), patch.object(s,"MEMBERS",allowed):
                    if mode==stat.S_IFREG:
                        self.assertEqual(s.unpack({s.SOURCE_ARTIFACT:archive},d/"selected"),{"ok":True})
                        self.assertEqual((d/"selected/C/overlay/0.zst").read_bytes(),payload)
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
        for role, rows in (("Coff",{"E":{},"C":{}}),("Eon",{"E":{}}),("Fon",{"E":{},"C":{}})):
            with self.subTest(role=role), self.assertRaises(ValueError):
                s.activate(role,rows,Path("."))

    def test_activation_binds_both_on_arms_to_own_manifest(self):
        rows = {"E": {}, "C": {}}
        active = Mock(return_value={"CARGO_ENCODED_RUSTFLAGS": "-Zohm-branch-cache=yes"})
        with patch.object(s, "policy", return_value=SimpleNamespace(b=SimpleNamespace(activate=active))):
            for arm in ("Eon", "Con"):
                env = s.activate(arm, rows, Path("/example"))
                self.assertEqual(env["CARGO_ENCODED_RUSTFLAGS"], "-Zohm-branch-cache=yes")
                active.assert_called_with(arm, rows, Path("/example"), permitted=("Eon", "Con"),
                                          source_manifest=s.MANIFEST[arm[0]])

    def test_pilot_and_donor_subjects_have_distinct_modules(self):
        with patch.dict(os.environ, {"RUNNER_TEMP":"/tmp"}):
            old=s.policy()
            self.assertIsNot(s,old.subjects)
            self.assertEqual(Path(old.subjects.__file__).resolve(),s.SCRIPTS/"branch-first-session-e-screen/subjects.py")
            self.assertIs(s.policy(),old)


def actual(archive_dir, official_path, original_e, scratch):
    original=json.loads(official_path.read_bytes())
    proof=s.official(original["run"],original["job"],original["artifacts"])
    archives={name:archive_dir/(str(row["id"])+"-"+name+".zip") for name,row in proof["artifacts"].items()}
    with tempfile.TemporaryDirectory(dir=scratch) as tmp, patch.dict(os.environ,{"RUNNER_TEMP":str(scratch)}):
        d=Path(tmp);transfer=d/"receipt";native=s.unpack(archives,transfer)
        b=s.policy().b
        parent=b.inventory(original_e)
        candidate=s.reconstruct(transfer,native,parent,original_e,d/"candidate",b)
        records={r:json.loads((transfer/"sdk"/(r+".json")).read_bytes()) for r in ("E","C")}
        wrong=copy.deepcopy(records);wrong["C"]["files"]["bin/cargo"][0]="0"*64
        with unittest.TestCase().assertRaises(ValueError):
            s.classify(parent,wrong,native)
        return {"run":proof["run"],"original_conclusion":proof["original_workflow"],
                "source":candidate["source"],"members":len(candidate["files"]),"shared_inodes":0,
                "driver":candidate["files"][s.DRIVER][0],"cargo":candidate["files"]["bin/cargo"][0],
                "wild":candidate["files"][b.WILD][0],"corrupted_cargo_refused":True}


if __name__=="__main__":
    if sys.argv[1:2]==["--originals"]:
        print(json.dumps(actual(*map(Path,sys.argv[2:])),sort_keys=True))
    else:
        unittest.main()
