"""Build the direct table-only child of #274 and retain the GNU compiler that passed."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "branch-first-session-e-source"), str(HERE.parent / "branch-return-source")]
import cross_reader
import prior
import restore_e
import qualify as source_tests
import registration as reg
import restore as sdk_tools
from registration import need, sha, write

F = "c6fe8ecda65452c105f85367a009af80cbb5efbc"
BASE = "f70612039692c9ec6abf67d8921f4b5085c0f101"
T = "a653d40da8cd7e13a6e6c10ac6ebfeb224945c73"
REF = "refs/heads/charlie/qa-tables-only-source-20261031"
TREE = "8fb5c75a2cd5fa542fbaf7d301db8bb3a88caa84"
COMPILER = "1de34fdeff4d471dda56dd91121f30693a59406c"
GUIDE = "e2ee8c786ba63b807e101bec2517ef9ab59db572"
PACKS = [
    (
        "current-base-history.pack",
        F,
        BASE,
        387,
        "dfda7ab9e1113e3874e706bcbb483affb3ec7abd707d35599a7aa9f90f77e54f",
    ),
    (
        "tables-only-history.pack",
        BASE,
        T,
        14,
        "f5ff90a37a115be2bacacb69bbb7b512ac60c2b5dfb69f3bade3e32ca8be6227",
    ),
]
SOURCES = {
    "compiler/rustc_incremental/src/persist/fs.rs": "aababc7bbe795beedb86704634bb4aec86e3b59d8b730c074860f35112e5e13b",
    "compiler/rustc_session/src/session.rs": "9c8396058bd9c95e26ec071063024a08ddb267f9aad92d97cbee4704c1ec21cc",
    "tests/run-make/ohm-packed-branch-cache/rmake.rs": "a590807281ea7e3f844ad11a1b766b1010e86efcca21c3276624cea78087da54",
}

MIXED = [
    ("T", "F", "packed", False, True),
    ("T", "F", "packed", False, False),
    ("F", "T", "raw", False, False),
    ("F", "T", "packed", True, False),
]


def source(repo=None, *, install=False):
    prior.s.inherited()
    result = []
    for filename, base, head, count, digest in PACKS:
        path = HERE / filename
        payload = path.read_bytes()
        need(
            sha(path) == digest
            and payload[:8] == b"PACK\x00\x00\x00\x02"
            and struct.unpack(">I", payload[8:12])[0] == count,
            "unrecognized source pack " + filename,
        )
        if repo:
            if install:
                reg.git(repo, "index-pack", "--stdin", data=payload)
            objects = reg.git(
                repo, "rev-list", "--objects", "--no-object-names", head, "^" + base
            ).splitlines()
            with tempfile.TemporaryDirectory() as tmp:
                idx = Path(tmp) / "source.idx"
                reg.git(repo, "index-pack", "--no-rev-index", "-o", str(idx), str(path))
                packed = [
                    row.split()[1] for row in reg.git(repo, "show-index", data=idx.read_bytes()).splitlines()
                ]
            need(
                len(objects) == len(packed) == count
                and set(objects) == set(packed)
                and len(set(packed)) == count,
                "wrong source object inventory",
            )
        result.append([filename, base, head, count, digest])
    if repo:

        def changed(a, b):
            return set(
                reg.git(repo, "diff-tree", "--no-commit-id", "--no-renames", "-r", "--name-only", a, b)
                .decode()
                .splitlines()
            )

        need(
            reg.rev(repo, T + "^") == BASE
            and reg.rev(repo, T + "^{tree}") == TREE
            and reg.rev(repo, T + ":compiler") == COMPILER
            and reg.rev(repo, T + ":AGENTS.md") == GUIDE,
            "foreign candidate",
        )
        need(
            changed(F, BASE) == {".github/workflows/ci.yml"} and changed(BASE, T) == set(SOURCES),
            "foreign product delta",
        )
        for path, digest in SOURCES.items():
            need(hashlib.sha256(reg.git(repo, "show", T + ":" + path)).hexdigest() == digest, path)
        code = "compiler/rustc_incremental/src/persist/fs/packed.rs"
        need(
            all(reg.rev(repo, v + ":" + code) == reg.rev(repo, T + ":" + code) for v in (F, BASE)),
            "different table encoder",
        )
    return {
        "source": T,
        "base": BASE,
        "original": F,
        "tree": TREE,
        "compiler": COMPILER,
        "files": SOURCES,
        "packs": result,
    }


def original_f(inbox, transfer, log, build=None):
    old, _, command, _ = prior.reopen(inbox, transfer)
    with zipfile.ZipFile(inbox / "branch-return-source-observations.zip") as z:
        tests = z.read("receipts/F/checked-in-tests.json")
        check = json.loads(tests)
        before = json.loads(z.read("receipts/F/before-tests.json"))
        need(
            old["roles"]["F"]["commit"] == F
            and old["files"]["F"] == before == json.loads(z.read("receipts/F/inventory.json"))
            and len(before) == 81,
            "wrong original F",
        )
        need(
            hashlib.sha256(tests).hexdigest() == old["tests"]["F"]
            and len(check["unit"]) == 8
            and check["run_make"] == source_tests.NATIVE_TESTS,
            "wrong original GNU tests",
        )
        other = json.loads(z.read("receipts/F/bootstrap.command.json"))
        need(
            other["argv"] == command["argv"]
            and other["cwd"] == command["cwd"]
            and other["returncode"] == command["returncode"] == 0,
            "different original SDK builds",
        )

        def positive(stem):
            raw = z.read("receipts/F/" + stem + ".log")
            cmd = json.loads(z.read("receipts/F/" + stem + ".command.json"))
            need(
                cmd["returncode"] == 0
                and cmd["cwd"] == other["cwd"]
                and hashlib.sha256(raw).hexdigest() == cmd["output_sha256"],
                "wrong original " + stem,
            )
            return raw.decode(), cmd

        platforms = json.loads(z.read("receipts/F/unit-platforms.json"))
        need(
            platforms["host"] == reg.HOST
            and platforms["linux_fs_util"] == 0
            and platforms["linux_incremental_names"] == check["unit"],
            "wrong original unit scope",
        )
        unit_log, unit_cmd = positive("rustc-units")
        source_tests.unit_verdict(unit_log, check["unit"], platforms["mac_only_source_names"])
        prefix = unit_cmd["argv"][:-2]
        need(
            unit_cmd["argv"][-2:] == ["compiler/rustc_fs_util", "compiler/rustc_incremental"],
            "wrong original unit command",
        )
        for test in check["run_make"]:
            raw, cmd = positive(test)
            need(cmd["argv"] == [*prefix, "tests/run-make/" + test], "wrong original run-make command")
            if build:
                build.verdict(raw, test, True, 0)
        native = json.loads(z.read("receipts/F/native-runtime/qualified.json"))
        shadow = json.loads(z.read("receipts/F/native-shadow/complete.json"))
        need(
            (
                native["role"],
                native["cargo"],
                native["wild"],
                native["normal_native"],
                native["shadow_native"],
            )
            == ("F", reg.ELF, reg.WILD_SHA, 6, 16)
            and (shadow["physical_cargo"], shadow["physical_wild"], shadow["visits"], shadow["branches"])
            == (reg.ELF, reg.WILD_SHA, 16, [17, 29, 47]),
            "wrong original native providers",
        )
    write(
        log / "F-original.json",
        {
            "source": F,
            "inventory": before,
            "tests": check,
            "bootstrap": other,
            "native": native,
            "shadow": shadow,
        },
    )
    return old, check, command


def install_f(root, transfer, log, b):
    info = prior.s.K_ORIGIN
    sdk = root / "operational"
    receipt = sdk_tools.restore(transfer, sdk, "F", info["head"], str(info["run"]), "1", info["manifest"])
    alias = root / "rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk, target_is_directory=True)
    env = source_tests.env_for(root)
    need(
        Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", "rustc"], env=env, text=True
            ).strip()
        ).samefile(sdk / "bin/rustc"),
        "foreign F",
    )
    src = log / "donor.rs"
    src.write_text('pub fn value()->String { String::from("cross-stage1") }\n')
    b.succeeded(
        [
            "rustc",
            "+ohm",
            src,
            "--crate-name",
            "qa_donor",
            "--crate-type",
            "rlib",
            "-o",
            root / "libqa_donor.rlib",
        ],
        root,
        log / "F-donor.log",
        env,
    )
    held = root / "genuine-F"
    sdk.rename(held)
    for name, dest in [
        ("bin/cargo", root / "cargo/cargo-761"),
        (reg.WILD, root / "packages/sdk-21" / reg.WILD),
    ]:
        dest.parent.mkdir(parents=True)
        os.link(held / name, dest)
    return receipt


def check_history(record, writer, reader, mode, direct, cold, driver, identities):
    need(
        (
            record["producer"],
            record["consumer"],
            record["representation"],
            record["cold_representation"],
            record["immediate_cold_read"],
        )
        == (writer, reader, mode, cold, direct),
        "wrong cross-reader history",
    )
    need(
        record["first_B_compiler"] == (reader if direct else writer)
        and record["first_B"] != record["return_elf"] == record["own_empty_elf"]
        and record["marker"] == record["returned_marker_identity"],
        "wrong cross-reader native return",
    )
    for role in (writer, reader):
        need(
            set(record["images"][role]) == {driver, "bin/rustdoc"}
            and all(row[0] == identities[role][name][0] for name, row in record["images"][role].items()),
            "wrong cross-reader compiler or rustdoc",
        )


def mixed(root, log, sdk, files, old, inventory):
    directory = log / "mixed"
    directory.mkdir()
    cross_reader.fixture(root / "cross-reader-work")
    path_names = [old["driver"], "bin/rustdoc"]
    actual = {
        "F": {name: root / "genuine-F" / name for name in path_names},
        "T": {name: files[Path(name)] for name in path_names},
    }
    rows = []
    for writer, reader, mode, aged, direct in MIXED:
        case = writer + "-to-" + reader + ("-immediate" if direct else "-aged" if aged else "-return")
        cold = "packed" if writer == "T" else "raw"
        record = cross_reader.history(
            root,
            directory,
            sdk,
            old["driver"],
            actual,
            source_tests.env_for(root),
            case=case,
            producer=writer,
            consumer=reader,
            mode=mode,
            aged=aged,
            direct=direct,
            producer_cold_mode=cold,
        )
        check_history(
            record,
            writer,
            reader,
            mode,
            direct,
            cold,
            old["driver"],
            {"F": old["files"]["F"], "T": inventory},
        )
        rows.append([case, sha(directory / case / "qualified.json")])
    need(all((sdk / n).samefile(actual["T"][n]) for n in path_names), "T not restored after mixed histories")
    write(directory / "complete.json", rows)


def restore(transfer, capsule, dest, qa, run_id, attempt, digest):
    origin = prior.s.K_ORIGIN
    path = capsule / "manifest.json"
    delta = capsule / "T-delta.tar.zst"
    need(
        set(capsule.iterdir()) == {path, delta}
        and all(p.is_file() and not p.is_symlink() for p in (path, delta))
        and path.stat().st_size <= 256 * 1024
        and sha(path) == digest
        and sha(transfer / "manifest.json") == origin["manifest"],
        "unauthenticated T capsule or original F",
    )
    record = json.loads(path.read_bytes())
    old = json.loads((transfer / "manifest.json").read_bytes())
    need(
        (record["qa"], record["run"], record["attempt"]) == (qa, str(run_id), 1)
        and str(attempt) == "1"
        and record["source"] == source()
        and record["original"] == origin
        and record["stage0"] == old["stage0"]
        and record["driver"] == old["driver"],
        "different T source qualification",
    )
    changed = restore_e.differences(old, record["files"], base_role="F")
    need(
        record["changed"] == sorted(changed)
        and 0 < delta.stat().st_size < 256 * 2**20
        and record["delta"] == [sha(delta), delta.stat().st_size],
        "corrupt T delta",
    )
    need(not dest.exists() and not dest.is_symlink(), "new unrelated output directory required")
    with tempfile.TemporaryDirectory(prefix=".restore-T-", dir=dest.parent) as tmp:
        staged = Path(tmp) / "sdk"
        sdk_tools.restore(transfer, staged, "F", origin["head"], str(origin["run"]), "1", origin["manifest"])
        sdk_tools.extract(delta, staged, changed, True)
        files = {}
        for p in staged.rglob("*"):
            need(not p.is_symlink() and (p.is_dir() or p.is_file()), "unexpected installed member")
            if p.is_file():
                files[str(p.relative_to(staged))] = [sha(p), p.stat().st_size, p.stat().st_mode & 0o7777]
        need(files == record["files"], "restored full SDK differs")
        staged.rename(dest)
    return {
        "source": T,
        "manifest": digest,
        "members": len(files),
        "changed": sorted(changed),
        "driver": files[old["driver"]],
        "rustdoc": files["bin/rustdoc"],
        "cargo": files["bin/cargo"],
        "wild": files[reg.WILD],
    }


def run(trusted):
    b = source_tests.toolchain(trusted)
    root, repo = b.ROOT, b.ROOT / "rust"
    need(
        root == Path(os.environ["QA_ROOT"])
        and os.environ["GITHUB_REF"] == REF
        and reg.rev(HERE.parents[1], "HEAD") == os.environ["GITHUB_SHA"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["GITHUB_REPOSITORY"] == reg.REPO
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and platform.machine() == "x86_64"
        and platform.system() == "Linux"
        and not root.is_symlink()
        and shutil.disk_usage(root).free > 32 * 2**30,
        "foreign enrollment or space",
    )
    rec = root / "receipts"
    log = rec / "T"
    log.mkdir()
    cap = root / "T-transfer"
    cap.mkdir()
    transfer = root / "F-transfer"
    old, expected, previous = original_f(root / "k-origin", transfer, log, b)
    from source import live_base

    live_base(repo, b.HERE / "packet")
    reg.source(repo, True, rec)
    registered = source(repo, install=True)
    reg.git(repo, "checkout", "--detach", T)
    b.check_source(repo, T)
    need(not (repo / "build").exists(), "checkout already has bootstrap products")
    write(log / "source.json", registered)
    write(log / "restored-F.json", install_f(root, transfer, log, b))
    args = ["./x", *b.OPTIONS, "build", *b.HOST_FLAGS, *b.SDK_COMPONENTS]
    need(args == previous["argv"] and str(repo) == previous["cwd"], "different bootstrap command")
    b.succeeded(args, repo, log / "bootstrap.log")
    stage = repo / "build" / b.HOST / "stage1"
    stage0 = {
        "source": sha(repo / "src/stage0"),
        **{n: sha(stage.parent / "stage0/bin" / n) for n in ("cargo", "rustc")},
    }
    need(stage0 == b.STAGE0 == old["stage0"] and old["llvm"] == b.LLVM, "different bootstrap or LLVM")
    files = source_tests.selected(b, stage, root)
    inventory = b.manifest(files)
    driver = old["driver"]
    changed = sorted(restore_e.differences(old, inventory, base_role="F"))
    write(log / "before-tests.json", inventory)
    source_tests.product_tests(b, repo, "F", log)
    result = json.loads((log / "checked-in-tests.json").read_bytes())
    fixtures = dict(expected["original_sources"])
    fixtures["ohm-packed-branch-cache"] = SOURCES["tests/run-make/ohm-packed-branch-cache/rmake.rs"]
    need(
        set(result["unit"]) == set(expected["unit"])
        and result["run_make"] == expected["run_make"]
        and result["original_sources"] == fixtures,
        "wrong current or original suite",
    )
    retained = b.manifest({k: p for k, p in files.items() if p.is_file()})
    need(all(inventory[n] == v for n, v in retained.items()), "tests changed an installed file")
    b.succeeded(args, repo, log / "reassemble.log")
    files = source_tests.selected(b, stage, root)
    need(b.manifest(files) == inventory, "reassembled compiler differs")
    b.operational(root, stage, files, "C", log)
    need((log / "rustc.log").read_text() == old["compiler_verbose"], "different rustc version stamp")
    write(
        rec / "lineage-calibration.json", source_tests.lineage_calibration.check(rec / "lineage-calibration")
    )
    sdk = root / "operational"
    sdk.mkdir()
    for name, path in files.items():
        dest = sdk / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.link(path.resolve(), dest)
    source_tests.native(b, root, sdk, log, "T")
    mixed(root, log, sdk, files, old, inventory)
    need(b.manifest(files) == inventory, "SDK changed during native execution")
    b.check_source(repo, T)
    delta = cap / "T-delta.tar.zst"
    b.archive({Path(n): files[Path(n)] for n in changed}, delta)
    o = prior.s.K_ORIGIN
    write(
        cap / "manifest.json",
        {
            "qa": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
            "attempt": 1,
            "source": registered,
            "original": o,
            "files": inventory,
            "driver": driver,
            "changed": changed,
            "delta": [sha(delta), delta.stat().st_size],
            "stage0": stage0,
            "tests": sha(log / "checked-in-tests.json"),
            "mixed": sha(log / "mixed/complete.json"),
            "native": sha(log / "native-shadow/complete.json"),
        },
    )
    result = restore(
        transfer,
        cap,
        root / "restored-T",
        os.environ["GITHUB_SHA"],
        os.environ["GITHUB_RUN_ID"],
        1,
        sha(cap / "manifest.json"),
    )
    write(log / "qualified.json", result)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preflight":
        print(json.dumps(source(Path(sys.argv[2]) if len(sys.argv) == 3 else None), sort_keys=True))
    elif len(sys.argv) > 1 and sys.argv[1] == "restore":
        parser = argparse.ArgumentParser(
            description="Restore and independently rehash T over its authenticated F."
        )
        for name in ("transfer", "capsule", "destination"):
            parser.add_argument(name, type=Path)
        for name in ("qa", "run", "attempt", "manifest"):
            parser.add_argument("--" + name, required=True)
        args = parser.parse_args(sys.argv[2:])
        print(
            json.dumps(
                restore(
                    args.transfer,
                    args.capsule,
                    args.destination,
                    args.qa,
                    args.run,
                    args.attempt,
                    args.manifest,
                ),
                sort_keys=True,
            )
        )
    else:
        run(Path(sys.argv[1]).resolve())
