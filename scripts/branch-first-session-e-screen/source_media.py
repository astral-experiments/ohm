"""Recover the already authenticated capsule identifier from the frozen native run's two original archives."""

import hashlib
import json
from pathlib import Path
import zipfile


HEAD = "2c305c16f72e9797a724f42adee34e9adb717792"
RUN = 41227867294
JOB = 124615704444
SOURCE = "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2"
NAMES = ("first-session-linux-source-driver", "first-session-linux-source-observations")


def need(value, reason):
    if not value:
        raise ValueError(reason)


def small(z, name):
    member = z.getinfo(name)
    need(0 < member.file_size <= 256 * 1024, "unbounded source receipt")
    return z.read(member)


def corrected(legacy, media):
    need(
        (legacy["head"], legacy["run"], legacy["attempt"], legacy["job"]) == (HEAD, RUN, 1, JOB)
        and set(legacy["artifacts"]) == set(NAMES),
        "wrong original source job",
    )
    archives = []
    for name in NAMES:
        path = Path(media) / (name + ".zip")
        meta = legacy["artifacts"][name]
        with path.open("rb") as f:
            need(
                path.stat().st_size == meta["size_in_bytes"]
                and "sha256:" + hashlib.file_digest(f, "sha256").hexdigest() == meta["digest"],
                "official source archive changed",
            )
        archives.append(path)
    with zipfile.ZipFile(archives[0]) as z:
        manifest_raw = small(z, "manifest.json")
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()
    manifest = json.loads(manifest_raw)
    with zipfile.ZipFile(archives[1]) as z:
        terminal = json.loads(small(z, "qualified.json"))
        label, reported_case, program = json.loads(small(z, "E/cross-readers/complete.json"))[-1]
        need(label == "K-packed-A-to-E", "wrong final source-reader control")
        raw_case = small(z, "E/cross-readers/" + label + "/qualified.json")
    case_sha = hashlib.sha256(raw_case).hexdigest()
    q = legacy["qualified"]
    need(
        case_sha == reported_case == q["manifest"]
        and case_sha != manifest_sha
        and json.loads(raw_case)["return_elf"] == program,
        "original source reader did not return its exact final case digest",
    )
    need(
        terminal["manifest"] == manifest_sha
        and terminal["commit"] == q["source"] == SOURCE
        and manifest["source"]["role"]["commit"] == SOURCE
        and (manifest["qa"], manifest["run"], manifest["attempt"]) == (HEAD, str(RUN), "1")
        and terminal["driver"] == q["driver"] == manifest["files"][manifest["driver"]]
        and terminal["members"] == q["members"] == len(manifest["files"]) == 81
        and terminal["changed"] == q["delta"] == manifest["delta"]
        and manifest["qualified"] is True,
        "native job terminal is not the authenticated source/SDK manifest",
    )
    return legacy | {"qualified": q | {"manifest": manifest_sha}}, {
        "legacy_final_case": label,
        "legacy_returned_case_sha256": case_sha,
        "capsule_manifest_sha256": manifest_sha,
        "terminal_manifest_sha256": terminal["manifest"],
    }
