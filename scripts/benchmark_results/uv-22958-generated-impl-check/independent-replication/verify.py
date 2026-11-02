"""Verify the compact original-member packet and optionally compare it to the service archive."""
from pathlib import Path
import gzip
import argparse
import hashlib
import json
import runpy
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def main(archive):
    anchor = read(ROOT / "origin.json")
    subset = ROOT / "raw-members.zip"
    reader = ROOT / "verify-eight.py"
    assert sha(subset) == anchor["subset"]
    assert sha(reader) == read(ROOT / "reader-registration.json")["source"]
    assert sha(ROOT / "registration.json") == anchor["registration"]
    service = read(ROOT / "original-service.json")
    run = read(ROOT / "run.json")
    jobs = read(ROOT / "jobs.json")
    job, = jobs["jobs"]
    assert run["status"] == job["status"] == "completed"
    assert run["conclusion"] == job["conclusion"] == "success"
    assert run["run_attempt"] == job["run_attempt"] == 1
    assert run["id"] == job["run_id"] == service["workflow_run"]["id"] == anchor["run"]
    assert run["head_sha"] == job["head_sha"] == service["workflow_run"]["head_sha"] == anchor["head"]
    assert service["id"] == anchor["artifact"] and service["digest"] == "sha256:" + anchor["original"]
    assert service["size_in_bytes"] == anchor["size"] and job["id"] == anchor["job"]
    authority = read(ROOT / "replication-runner.json")
    registered = read(ROOT / "reader-registration.json")
    early = read(ROOT / "boot-service.json")
    assert sha(ROOT / "release-lock.json") == registered["release_lock"]
    assert sha(ROOT / "replication-plan.json") == registered["plan"]
    assert registered["registered"] == anchor["registration"]
    assert registered["head"] == authority["head"] == anchor["head"]
    assert registered["run"] == authority["run"] == anchor["run"]
    assert authority["worker"] == job["runner_id"] != authority["first_worker"]
    assert authority["job"] == job["id"] and early["id"] == authority["artifact_id"]
    assert early["workflow_run"] == service["workflow_run"]
    assert sha(ROOT / "boot.zip") == authority["artifact_sha"] == early["digest"][7:]
    with ZipFile(ROOT / "boot.zip") as boot_zip, ZipFile(subset) as raw:
        assert boot_zip.namelist() == ["boot-attestation.json"]
        boot = boot_zip.read("boot-attestation.json")
        assert hashlib.sha256(boot).hexdigest() == authority["entry_sha256"]
        assert raw.read("boot-attestation.json") == boot
        assert json.loads(boot)["boot"] == authority["boot"]
    with ZipFile(subset) as raw:
        assert set(raw.namelist()) == set(anchor["members"])
        assert len(raw.namelist()) == len(anchor["members"])
        for name, digest in anchor["members"].items():
            assert hashlib.sha256(raw.read(name)).hexdigest() == digest
        if archive:
            index=ROOT/"all-members.sha256.gz";assert sha(index)==anchor["complete_member_index"]
            with gzip.open(index,"rt")as stream:complete=json.load(stream)
            with ZipFile(archive)as original:
                assert len(original.namelist())==len(set(original.namelist()))
                assert set(complete)=={q.filename for q in original.infolist()if not q.is_dir()}
                for member,digest in complete.items():assert hashlib.sha256(original.read(member)).hexdigest()==digest
            assert sha(archive) == anchor["original"] and archive.stat().st_size == anchor["size"]
            with ZipFile(archive) as source:
                for name in raw.namelist():
                    assert raw.read(name) == source.read(name)
    verifier = runpy.run_path(str(reader))
    score = verifier["verify"](subset, anchor["subset"])
    score["original_sha256"] = anchor["original"]
    assert score == read(ROOT / "independent-eight.json")
    print(json.dumps(score, sort_keys=True, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--original", type=Path)
    main(cli.parse_args().original)
