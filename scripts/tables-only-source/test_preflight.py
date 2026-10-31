"""Run offline against real source and original QA media. No compiler is built or benchmarked."""

import argparse
from copy import deepcopy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("tables_only", HERE / "qualify.py")
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
import read_cross
from native_trace import owner_reads
import test_adapter as first_session


def reject(fn, why):
    try:
        fn()
    except ValueError as e:
        assert str(e) == why, str(e)
    else:
        raise AssertionError("accepted " + why)


def trees(repo, work):
    new = work / "receiver.git"
    subprocess.run(["git", "init", "--quiet", "--bare", new], check=True)
    objects = t.reg.git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects").decode().strip()
    (new / "objects/info/alternates").write_text(objects + "\n")
    identity = t.source(new, install=True)
    installed = list((new / "objects/pack").glob("*.idx"))
    assert len(installed) == 2 and identity == t.source(repo)
    name, base, head, count, digest = t.PACKS[1]
    exact = t.reg.git(repo, "rev-list", "--objects", "--no-object-names", head, "^" + base).splitlines()
    other = t.reg.git(
        repo, "rev-parse", base + ":compiler/rustc_incremental/src/persist/fs/packed.rs"
    ).strip()
    assert other not in exact
    substitute = t.reg.git(
        repo,
        "pack-objects",
        "--stdout",
        "--window=0",
        "--no-reuse-delta",
        data=b"\n".join(exact[:-1] + [other]) + b"\n",
    )
    wrong = work / "foreign.pack"
    wrong.write_bytes(substitute)
    with patch.object(t, "PACKS", [(str(wrong), base, head, count, hashlib.sha256(substitute).hexdigest())]):
        reject(lambda: t.source(new), "wrong source object inventory")
    with patch.object(t, "PACKS", [(name, base, head, count, "0" * 64)]):
        reject(lambda: t.source(new), "unrecognized source pack " + name)
    with patch.object(t, "T", base):
        reject(lambda: t.source(new), "foreign candidate")
    return identity


def source_tests(repo, work, inbox, previous, build):
    # Materialize only files actually consumed by the original test selector. RMAKE sources
    # for T are checked independently; historical F logs supply results only for F.
    names = previous["run_make"]
    required = [
        "compiler/rustc_fs_util/src/lib.rs",
        "compiler/rustc_fs_util/src/tests.rs",
        "compiler/rustc_incremental/src/persist/fs/tests.rs",
        "compiler/rustc_incremental/src/persist/fs/packed/tests.rs",
    ]
    for role in (t.F, t.T):
        root = work / role
        for name in [*required, *("tests/run-make/" + x + "/rmake.rs" for x in names)]:
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(t.reg.git(repo, "show", role + ":" + name))
        units, _ = t.source_tests.unit_names(root, "F")
        assert units == previous["unit"]
        expected = dict(previous["original_sources"])
        if role == t.T:
            expected["ohm-packed-branch-cache"] = t.SOURCES["tests/run-make/ohm-packed-branch-cache/rmake.rs"]
        assert {n: t.sha(root / "tests/run-make" / n / "rmake.rs") for n in names} == expected
    with zipfile.ZipFile(inbox / "branch-return-source-observations.zip") as z:
        replay = work / "original-tests"
        replay.mkdir()

        def observed(args, root, log):
            assert root == work / t.F
            name = "receipts/F/" + log.stem
            cmd = json.loads(z.read(name + ".command.json"))
            raw = z.read(name + ".log")
            assert list(args) == cmd["argv"] and cmd["returncode"] == 0
            assert hashlib.sha256(raw).hexdigest() == cmd["output_sha256"]
            log.write_bytes(raw)

        with patch.object(build, "succeeded", observed):
            t.source_tests.product_tests(build, work / t.F, "F", replay)
        assert json.loads((replay / "checked-in-tests.json").read_bytes()) == previous
        changed = (
            (replay / "rustc-units.log")
            .read_text()
            .replace("test " + previous["unit"][0] + " ... ok", "test unrelated ... ok")
        )
        _, mac = t.source_tests.unit_names(work / t.F, "F")
        reject(
            lambda: t.source_tests.unit_verdict(changed, previous["unit"], mac),
            "missing checked-in Linux unit " + previous["unit"][0],
        )
        n = names[3]
        changed = (
            (replay / (n + ".log"))
            .read_text()
            .replace("tests/run-make/" + n + " ... ok", "tests/run-make/foreign ... ok")
        )
        reject(lambda: build.verdict(changed, n, True, 0), "missing named native pass for " + n)
    return {
        "linux_units": units,
        "run_make": names,
        "original_F_native_log_replay": True,
        "changed_T_fixture": "ohm-packed-branch-cache",
    }


def native_original(inbox):
    values = {
        "cold": 17,
        "repeat": 17,
        "higher": 29,
        "same-stat": 47,
        "malformed": None,
        "repeat-malformed": None,
        "repair": 29,
        "removed": 17,
    }
    with zipfile.ZipFile(inbox / "branch-return-source-observations.zip") as z:

        def read(rel):
            return z.read("receipts/F/" + rel)

        for phase, value in values.items():
            elfs = []
            for kind in ("warm", "empty"):
                loc = "native-shadow/" + phase + "-" + kind + "/"
                row = json.loads(read(loc + "terminal.json"))
                old = row["native"]
                entries = re.split(r"(?m)^== (\d+) ==\n", gzip.decompress(read(loc + "trace.gz")).decode())
                assert entries[0] == "" and len(entries) % 2 == 1
                raw = {int(pid): v.splitlines() for pid, v in zip(entries[1::2], entries[2::2], strict=True)}
                sdk = "/tmp/ohm-gnu-renderer-source-native/"

                def classify(p):
                    for layout in ("operational/", "rustup/toolchains/ohm/"):
                        if p == sdk + layout + "bin/cargo":
                            return "cargo"
                        if p == sdk + layout + t.reg.WILD:
                            return "wild"
                    return "other"

                observed = owner_reads(raw, old["resolved"], classify)
                assert observed == {k: old[k] for k in observed}
                marker = read(loc + "leaf-0.d")
                assert (
                    t.source_tests.native_guard.MARKER in marker
                    and hashlib.sha256(marker).hexdigest() in row["marker_sha256"]
                )
                assert row["value"] == value and row["exit"] == (101 if value is None else 0)
                if value is not None:
                    elf = gzip.decompress(read("native-shadow/elf/" + row["elf"] + ".gz"))
                    assert elf.startswith(b"\x7fELF") and hashlib.sha256(elf).hexdigest() == row["elf"]
                elfs.append(row["elf"])
            assert elfs[0] == elfs[1]
        provider = json.loads(read("provider-F/result.json"))
        assert len(provider) == 6
        for name, good in {
            "cold-A": "17 1",
            "first-B": "29 2",
            "returned-A": "29 1",
            "invalid": None,
            "repair": "29 1",
            "empty-repair": "29 1",
        }.items():
            pre = "provider-F/" + name + "/"
            command = json.loads(gzip.decompress(read(pre + "cargo.json.gz")))
            assert command["exit"] == provider[name]["exit"] == (101 if good is None else 0)
            if good is not None:
                assert (
                    gzip.decompress(read(pre + "witness.stdout.gz")).decode().strip()
                    == provider[name]["output"]
                    == good
                )
        assert (
            provider["returned-A"]["binary"]
            == provider["repair"]["binary"]
            == provider["empty-repair"]["binary"]
        )
    return {
        "ordinary": len(provider),
        "shadow": 2 * len(values),
        "owned_provider_reads": 2 * len(values),
        "malformed_warm_or_empty": 4,
        "cargo": t.reg.ELF,
        "wild": t.reg.WILD_SHA,
    }


def restore_guards(work, inbox, old, enrollment):
    # These are refusal fixtures; only the official run can provide a qualified T manifest.
    transfer, cap, dest = [work / n for n in ("F-transfer", "T-capsule", "new-sdk")]
    transfer.mkdir()
    cap.mkdir()
    with zipfile.ZipFile(inbox / "branch-return-source-sdk.zip") as z:
        (transfer / "manifest.json").write_bytes(z.read("manifest.json"))
    delta = cap / "T-delta.tar.zst"
    delta.write_bytes(b"invalid transport")
    path = cap / "manifest.json"
    fixture = {
        "qa": "test-only",
        "run": "1",
        "attempt": 1,
        "source": enrollment,
        "original": t.prior.s.K_ORIGIN,
        "driver": old["driver"],
        "stage0": old["stage0"],
        "files": old["files"]["F"],
        "changed": [],
    }
    t.write(path, fixture)

    def probe(**overrides):
        t.write(path, fixture | overrides)
        t.restore(transfer, cap, dest, "test-only", "1", "1", t.sha(path))

    reject(lambda: probe(), "compiler driver did not change")
    reject(lambda: probe(source=enrollment | {"source": t.F}), "different T source qualification")
    reject(lambda: probe(attempt=2), "different T source qualification")
    # Use real independently different K geometry to reach and reject a corrupted delta.
    changes = t.restore_e.differences(old, old["files"]["K"], base_role="F")
    reject(
        lambda: probe(
            files=old["files"]["K"], changed=sorted(changes), delta=["0" * 64, delta.stat().st_size]
        ),
        "corrupt T delta",
    )
    identities = deepcopy(old["files"]["K"])
    identities["bin/cargo"][0] = "0" * 64
    reject(lambda: probe(files=identities), "unexpected native member bin/cargo")
    assert not dest.exists()


def mixed_original(directory):
    transfer = directory / "first-session-linux-source-driver.zip"
    observed = directory / "first-session-linux-source-observations.zip"
    assert t.sha(transfer) == "b4372e9d8d51decdd0d68ddb620ddfc8807368d1de76f5f607bc745bb7a2115c"
    assert t.sha(observed) == "dedb5a559ec6d0ecfd0a1e9b9f93ca439b068856ea2cde6b71742eb44d00b5b0"
    with zipfile.ZipFile(transfer) as held:
        m = json.loads(held.read("manifest.json"))
    result = {}
    with zipfile.ZipFile(observed) as z:
        old = json.loads(z.read("E/original-K.json"))["sdk"]
        assert (
            old["commit"] == t.prior.s.K
            and m["source"]["role"]["commit"] == "c9a6a212d38d778ed0e9d2c7057a9dedb179fff2"
        )
        driver = m["driver"]
        ids = {"K": {driver: old["driver"], "bin/rustdoc": old["rustdoc"]}, "E": m["files"]}
        rows = json.loads(z.read("E/cross-readers/complete.json"))
        assert len(rows) == len(t.MIXED)
        for (case, digest, elf), (new_writer, new_reader, mode, aged, direct) in zip(
            rows, t.MIXED, strict=True
        ):
            # Bind the actual old names. Never label a historical E/K image as prospective T/F.
            (writer, reader) = tuple({"T": "E", "F": "K"}[v] for v in (new_writer, new_reader))
            cold = "packed" if writer == "E" else "raw"
            raw = z.read("E/cross-readers/" + case + "/qualified.json")
            row = json.loads(raw)
            assert hashlib.sha256(raw).hexdigest() == digest and row["return_elf"] == elf
            assert aged == (case == "K-packed-A-to-E")
            read_cross.replay(z, z.read, case, row, m, old)
            t.check_history(row, writer, reader, mode, direct, cold, driver, ids)
            wrong = deepcopy(row)
            wrong["images"][writer][driver][0] = "0" * 64
            reject(
                lambda: t.check_history(wrong, writer, reader, mode, direct, cold, driver, ids),
                "wrong cross-reader compiler or rustdoc",
            )
            reject(
                lambda: t.check_history(row, writer, reader, mode, not direct, cold, driver, ids),
                "wrong cross-reader history",
            )
            result[case] = digest
    return {"original_run": 41227867294, "histories": result}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("rust_git", "trusted", "f_media"):
        p.add_argument(name, type=Path)
    p.add_argument("--historical-mixed", type=Path)
    a = p.parse_args()
    root = HERE.parents[1]
    trusted = a.trusted.resolve()
    from_repo = t.reg.rev(root, "a4afd181ae07107de6174a17a4ec189061fd18aa:scripts/gnu-renderer-cgu-source")
    assert t.reg.rev(trusted, "HEAD:scripts/gnu-renderer-cgu-source") == from_repo
    assert not t.reg.git(trusted, "status", "--porcelain", "--", "scripts/gnu-renderer-cgu-source")
    build = t.source_tests.toolchain(trusted)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        enrolled = trees(a.rust_git.resolve(), work)
        old, expected, _ = t.original_f(a.f_media.resolve(), None, work, build)
        members = first_session.original_members(a.f_media.resolve(), old)
        assert members == 81
        checks = source_tests(a.rust_git.resolve(), work, a.f_media.resolve(), expected, build)
        restore_guards(work, a.f_media.resolve(), old, enrolled)
    result = {
        "source": enrolled,
        "original_role": t.F,
        "original_run": t.prior.s.K_ORIGIN["run"],
        "original_sdk_members": members,
        "source_tests": checks,
        "F_native": native_original(a.f_media.resolve()),
        "pack_refusals": [
            "changed transport hash",
            "one of fourteen object IDs replaced",
            "wrong T parent/head",
        ],
        "source_test_refusals": ["missing original named unit", "wrong original run-make"],
        "restore_refusals": [
            "unchanged driver",
            "foreign source",
            "wrong attempt",
            "corrupt delta",
            "changed Cargo",
        ],
    }
    if a.historical_mixed:
        result["historical_mixed"] = mixed_original(a.historical_mixed)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    assert not sys.flags.optimize
    main()
