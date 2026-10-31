"""Offline mechanical qualification. The sole optional input is the original official F/K ZIP directory."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from threading import Thread
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subject as s
import prior
import qualify_e
import restore_e
import locate_e


def reject(fn):
    try:
        fn()
    except (ValueError, TypeError, KeyError):
        return
    raise AssertionError("invalid admission was accepted")


def original_members(inbox, manifest):
    zpath = inbox / "branch-return-source-sdk.zip"
    held = {}
    with zipfile.ZipFile(zpath) as z:
        for name in ("F-sdk.tar.zst", "K-delta.tar.zst"):
            found = {}
            with z.open(name) as src, subprocess.Popen(
                ["zstd", "-dcq"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
            ) as proc:
                errors = []

                def feed():
                    try:
                        with proc.stdin:
                            shutil.copyfileobj(src, proc.stdin, 1 << 20)
                    except Exception as e:
                        errors.append(e)

                feeder = Thread(target=feed)
                feeder.start()
                with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                    for m in tar:
                        assert m.name not in found and m.isreg() and prior.old.valid(m.name)
                        with tar.extractfile(m) as body:
                            found[m.name] = [
                                hashlib.file_digest(body, "sha256").hexdigest(),
                                m.size,
                                m.mode,
                            ]
                assert not proc.stdout.read().strip(b"\0")
                feeder.join()
                assert proc.wait() == 0 and not errors
            expected = (
                manifest["files"]["F"]
                if name.startswith("F-")
                else {n: manifest["files"]["K"][n] for n in manifest["delta"]}
            )
            assert found == expected
            held.update(found)
    assert held == manifest["files"]["K"]
    return len(held)


def run(inbox, rustrepo=None):
    s.inherited()
    reject(lambda: s.validate(None))
    enrolled = s.load()
    for key, replacement in (("policy", "swapped-displaced-session"), ("parent", "0" * 40),
                             ("additional_run_make", ["unrelated"])):
        reject(lambda: s.validate(enrolled | {key: replacement}))
    for row in enrolled["delta"]["rows"]:
        changed = deepcopy(enrolled)
        next(r for r in changed["delta"]["rows"] if r["path"] == row["path"])["new"]["sha256"] = "0" * 64
        reject(lambda: s.validate(changed))
    m, t, boot, _ = prior.reopen(inbox)
    physical = original_members(inbox, m)
    driver = m["driver"]
    k = m["files"]["K"]
    sample = deepcopy(k)
    sample[driver][0] = m["files"]["F"][driver][0]
    assert set(restore_e.differences(m, sample)) == {driver}
    sample["bin/rustdoc"] = m["files"]["F"]["bin/rustdoc"]
    assert set(restore_e.differences(m, sample)) == {driver, "bin/rustdoc"}
    reject(lambda: restore_e.differences(m, k))
    for n in ("bin/rustc", "bin/cargo", s.reg.WILD, next(k for k in k if k.endswith(".rlib"))):
        v = deepcopy(sample)
        v[n][0] = "f" * 64
        reject(lambda: restore_e.differences(m, v))
    for v in (
        {**sample, "lib/extra": sample[driver]},
        {n: v for n, v in sample.items() if n != "bin/rustc"},
    ):
        reject(lambda: restore_e.differences(m, v))
    for row in (
        [sample[driver][0], sample[driver][1], 0o4755],
        ["INVALID", 20, 0o755],
        [sample[driver][0], 1 << 32, 0o755],
    ):
        v = {**sample, driver: row}
        reject(lambda: restore_e.differences(m, v))
    # Original -j8 emitted both suites' headers asynchronously. Split exactly the witnessed
    # command, named tests and native result lines to exercise the new one-suite-at-a-time projection.
    with zipfile.ZipFile(inbox / "branch-return-source-observations.zip") as z:
        raw = z.read("receipts/K/rustc-units.log").decode()
    unit = raw.split("   Doc-tests ")[0].splitlines()
    for crate, names in (("rustc_incremental", t["unit"]), ("rustc_fs_util", [])):
        (hdr,) = [l for l in unit if "Running unittests " in l and "/" + crate + "/" in l]
        count = len(names)
        (n,) = [l for l in unit if l == f"running {count} tests"]
        (result,) = [l for l in unit if l.startswith(f"test result: ok. {count} passed;")]
        selected = [l for l in unit if l.startswith("test persist::")] if count else []
        text = "\n".join([hdr, n, *selected, result])
        assert qualify_e.unit_record(text, crate, names) == sorted(names)
        reject(lambda: qualify_e.unit_record(text, crate, ["not::present"]))
        reject(lambda: qualify_e.unit_record(text + "\n" + result, crate, names))
        reject(
            lambda: qualify_e.unit_record(
                text.replace("0 filtered out;", "1 filtered out;"), crate, names
            )
        )
    pack_proof = None
    candidate_pack = None
    if rustrepo is not None:
        parent = s.reg.SOURCE()["roles"]["F"]["commit"]
        payload = s.reg.git(
            rustrepo,
            "-c",
            "pack.threads=1",
            "pack-objects",
            "--stdout",
            "--revs",
            "--no-reuse-object",
            "--no-reuse-delta",
            data=f"{s.K}\n^{parent}\n".encode(),
        )
        count = s.verify_pack(rustrepo, parent, s.K, payload)
        assert count > 0
        reject(lambda: s.verify_pack(rustrepo, s.K, s.K, payload))
        pack_proof = dict(
            parent=parent,
            child=s.K,
            objects=count,
            bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            wrong_parent_refused=True,
        )
        s.verify(rustrepo, enrolled)
        product_pack = (s.HERE / "inputs/E.pack").read_bytes()
        candidate_pack = s.verify_pack(rustrepo, s.K, enrolled["role"]["commit"], product_pack)
        assert candidate_pack > 0
        reject(lambda: s.verify_pack(rustrepo, s.K, enrolled["role"]["commit"], payload))
    # Official identity and verdict predicates work without relaxing the original K enrollment.
    qa = "a" * 40
    run = 11
    entry = dict(
        id=run,
        head_sha=qa,
        head_branch=s.REF.removeprefix("refs/heads/"),
        run_attempt=1,
        event="workflow_dispatch",
        path=".github/workflows/ci.yml",
        conclusion="success",
    )
    j = dict(
        id=2,
        head_sha=qa,
        run_attempt=1,
        name=locate_e.NAME,
        conclusion="success",
        status="completed",
        steps=[dict(name=n, conclusion="success") for n in locate_e.STEPS],
    )
    arts = [
        dict(
            name=n,
            id=i,
            size_in_bytes=2048,
            digest="sha256:" + "b" * 64,
            expired=False,
            workflow_run=dict(id=run, head_sha=qa),
        )
        for i, n in enumerate(("first-session-linux-source-driver", "first-session-linux-source-observations"))
    ]
    assert locate_e.check(run, qa, entry, [j], arts)["attempt"] == 1
    reject(lambda: locate_e.check(run, qa, {**entry, "run_attempt": 2}, [j], arts))
    reject(lambda: locate_e.check(run, qa, entry, [{**j, "steps": j["steps"][:-1]}], arts))
    reject(lambda: locate_e.check(run, qa, entry, [j], [{**arts[0], "expired": True}, arts[1]]))
    return {
        "source_native": False,
        "genuine_K_source_transport_control": pack_proof,
        "original_K": s.K,
        "installed_members_streamed": physical,
        "source_zip": s.K_ORIGIN["artifacts"],
        "driver": k[driver],
        "strict_cargo": k["bin/cargo"],
        "stock_wild": k[s.reg.WILD],
        "prior_named_linux_units": len(t["unit"]),
        "prior_named_run_make": len(t["run_make"]),
        "original_bootstrap": boot["argv"],
        "capsule_refusals": 10,
        "suite_refusals": 6,
        "official_refusals": 3,
        "unregistered_product_refused": True,
        "subject": enrolled["role"],
        "candidate_pack_objects": candidate_pack,
        "subject_tampers_refused": 3 + len(enrolled["delta"]["rows"]),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original_official_zip_directory", type=Path)
    p.add_argument("--rust-repo", type=Path)
    a = p.parse_args()
    print(json.dumps(run(a.original_official_zip_directory, a.rust_repo), indent=2, sort_keys=True))
