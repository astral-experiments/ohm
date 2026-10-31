"""Install both reviewed 81-member native toolchains at one stable canonical path."""

import json
from pathlib import Path
import shutil
import sys
import os
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "branch-return-pmu")]
import bindings as b
import source_media

ORDERS = {"01": ("Eoff", "Kon", "Eon"), "02": ("Eon", "Kon", "Eoff")}
BASE_COMMIT = "0afbeff303d3658bff52582d8f1a996d59e6c8ce"
REF = "charlie/qa-branch-first-session-e-screen-20261031"
RUNTIME = HERE / "inputs/e-source.json"


def enrollment(binding=RUNTIME, certificate=HERE / "inputs/source-replay.json"):
    r = json.loads(binding.read_bytes())
    e = r.get("source")
    reviewer = r.get("reviewer")
    b.need(
        r.get("schema") == 1 and isinstance(e, dict) and isinstance(reviewer, dict),
        "needs exact independently qualified source and receipt",
    )
    b.need(
        e["attempt"] == 1
        and e["run"] > 0
        and e["job"] > 0
        and re.fullmatch("[0-9a-f]{40}", e["head"])
        and set(e["artifacts"])
        == {"first-session-linux-source-driver", "first-session-linux-source-observations"}
        and e["qualified"]["members"] == 81
        and re.fullmatch("[0-9a-f]{40}", e["qualified"]["source"])
        and re.fullmatch("[0-9a-f]{64}", e["qualified"]["manifest"])
        and reviewer["source"] == e["qualified"]["source"]
        and reviewer["manifest"] == e["qualified"]["manifest"]
        and re.fullmatch("[0-9a-f]{64}", reviewer["raw_sha256"]),
        "incomplete E source provenance",
    )
    b.need(
        (e["run"], e["head"], e["job"], e["qualified"]["source"])
        == (
            41227867294,
            "2c305c16f72e9797a724f42adee34e9adb717792",
            124615704444,
            "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2",
        ),
        "source did not match the reviewed corrected qualification",
    )
    b.need(b.sha(certificate) == reviewer["raw_sha256"], "different independent native receipt")
    proof = json.loads(certificate.read_bytes())
    b.need(
        proof["official"] == e
        and proof["trusted_member_count"] == proof["restored"]["members"] == 81
        and proof["restored"]["commit"] == e["qualified"]["source"]
        and proof["restored"]["manifest"] == e["qualified"]["manifest"]
        and set(proof["cross_readers"])
        == {"E-cold-A-to-K", "E-first-A-to-K", "K-first-A-to-E", "K-packed-A-to-E"}
        and len(proof["actual_native_test_logs_sha256"]) == 11
        and proof["whole_cargo_counts"] is None,
        "source closure or native acquisition does not match the reviewed independent E contact",
    )
    native = proof["native_replayed_here"]
    for state in proof["cross_readers"].values():
        for key, value in (("return_elf", 17), ("first_B", 29)):
            actual = native[state[key]]
            b.need(
                actual["value"] == value
                and actual["observed"] == {str(value): 0, str(value + 1): 19},
                "independent positive or deliberately contradictory ELF verdict not reopened",
            )
    return e


def activate(arm, rows, folder):
    m = b.spec()["manifest"] if arm == "Kon" else enrollment()["qualified"]["manifest"]
    return b.activate(arm, rows, folder, permitted=ORDERS["01"], source_manifest=m)


def capture(args, output, cwd=None):
    child = subprocess.run(args, cwd=cwd, capture_output=True)
    output.with_suffix(".stdout").write_bytes(child.stdout)
    output.with_suffix(".stderr").write_bytes(child.stderr)
    b.need(child.returncode == 0, (args, child.returncode, child.stderr[-1500:]))
    return child.stdout


def acquire(source):
    e = enrollment()
    b.prepare_checkout(source, e["head"], "scripts")
    code = source / "scripts/branch-first-session-e-source"
    sys.path.insert(0, str(code))
    import prior

    b.need(
        Path(prior.__file__).resolve() == code / "prior.py"
        and prior.s.K_ORIGIN["manifest"] == b.spec()["manifest"],
        "incorrect source or K reader",
    )
    dir_ = b.OUT / "sdk"
    dir_.mkdir()
    inbox = b.ROOT / "prior-archives"
    prior.fetch(inbox)
    ktransfer = b.ROOT / "original-transfer"
    k, _, _, _ = prior.reopen(inbox, ktransfer)
    b.need(k["roles"]["K"]["commit"] == BASE_COMMIT, "different physical K")
    e_archive = b.ROOT / "e-archives"
    e_archive.mkdir()
    driver_name = "first-session-linux-source-driver"
    for name, row in e["artifacts"].items():
        target = e_archive / (name + ".zip")
        with target.open("xb") as f:
            subprocess.run(
                ["gh", "api", f"repos/{b.REPO}/actions/artifacts/{row['id']}/zip"],
                stdout=f,
                check=True,
            )
        b.need(
            target.stat().st_size == row["size_in_bytes"]
            and "sha256:" + b.sha(target) == row["digest"],
            ("different official E media", name),
        )
    actual = json.loads(
        capture(
            [
                sys.executable,
                "-IB",
                code / "locate_e.py",
                str(e["run"]),
                e["head"],
                "--gh",
                "gh",
                "--media",
                e_archive,
            ],
            dir_ / "official-E",
        )
    )
    actual, identities = source_media.corrected(actual, e_archive)
    b.save(dir_ / "native-media-identities.json", identities)
    b.need(actual == e, "different source job or original qualification evidence")
    capsule = b.ROOT / "E-transfer"
    capsule.mkdir()
    with zipfile.ZipFile(e_archive / (driver_name + ".zip")) as z:
        b.need(
            len(z.infolist()) == 2 and set(z.namelist()) == {"manifest.json", "E-delta.tar.zst"},
            "different E capsule",
        )
        for rec in z.infolist():
            b.need(0 < rec.file_size < 256 * 2**20, "unbounded E member")
            with z.open(rec) as src, (capsule / rec.filename).open("xb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    m = json.loads((capsule / "manifest.json").read_bytes())
    b.need(b.sha(capsule / "manifest.json") == e["qualified"]["manifest"], "foreign E manifest")
    b.PARK.mkdir()
    b.SDK.parent.mkdir(parents=True)
    kargs = [
        "--qa",
        k["qa"],
        "--run",
        k["run"],
        "--attempt",
        "1",
        "--manifest",
        b.spec()["manifest"],
    ]
    eargs = [
        "--qa",
        e["head"],
        "--run",
        str(e["run"]),
        "--attempt",
        "1",
        "--manifest",
        e["qualified"]["manifest"],
    ]
    capture(
        [
            sys.executable,
            "-IB",
            source / "scripts/branch-return-source/restore.py",
            ktransfer,
            b.PARK / "K",
            "K",
            *kargs,
        ],
        dir_ / "reopen-K",
    )
    capture(
        [sys.executable, "-IB", code / "restore_e.py", ktransfer, capsule, b.PARK / "E", *eargs],
        dir_ / "reopen-E",
    )
    roles = {"K": (k["roles"]["K"], k["files"]["K"]), "E": (m["source"], m["files"])}
    rows = {}
    for role, (source_id, manifest) in roles.items():
        files = b.inventory(b.PARK / role)
        b.need(
            {p: [r[0], r[4], r[3]] for p, r in files.items()} == manifest
            and len(files) == 81
            and files["bin/cargo"][0] == b.CARGO_ELF
            and files[b.WILD][0] == b.WILD_ELF
            and len(
                [p for p in files if p.startswith("lib/librustc_driver-") and p.endswith(".so")]
            )
            == 1,
            ("physical SDK admission", role),
        )
        rows[role] = files
        b.save(
            dir_ / (role + ".json"),
            {"role": role, "source": source_id, "driver": k["driver"], "files": files},
        )
    changed = sorted(name for name in rows["K"] if m["files"][name] != k["files"]["K"][name])
    b.need(
        k["driver"] in changed and set(changed) <= {k["driver"], "bin/rustdoc"},
        "incompatible SDKs",
    )
    b.PROXIES.mkdir(parents=True)
    shutil.copy2(shutil.which("rustup"), b.PROXIES / "rustup")
    for name in ("cargo", "rustc", "rustdoc"):
        os.link(b.PROXIES / "rustup", b.PROXIES / name)
    b.save(
        dir_ / "proxy.json",
        {
            "sha256": b.sha(b.PROXIES / "rustup"),
            "changed_sdk_members": changed,
            "paths": {str(p): b.numbers(p) for p in b.PROXIES.iterdir()},
        },
    )
    return rows


if __name__ == "__main__":
    print("source_head=" + enrollment()["head"])
