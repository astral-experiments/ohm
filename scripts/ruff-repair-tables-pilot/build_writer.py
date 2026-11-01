"""One source bootstrap, with the existing real compiletest and native provider/mixed-reader gates."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import source_binding as reg
import compat, overlay


def save(path, content):
    with path.open("x") as stream:
        json.dump(content, stream, sort_keys=True, indent=2)
        stream.write("\n")


def original_controls(archive):
    with zipfile.ZipFile(archive) as media:
        result = {}
        for label, member in (
            ("bootstrap", "E/bootstrap.command.json"),
            ("tests", "E/checked-in-tests.json"),
        ):
            raw = media.read(member)
            reg.need(
                raw == (HERE / "inputs" / ("original-" + label + ".json")).read_bytes(),
                "different original " + label,
            )
            result[label] = json.loads(raw)
        result["stage0"] = (
            json.loads(media.read("qualified.json")) if "qualified.json" in media.namelist() else None
        )
    return result


def main(source, trusted):
    reg.official_job()
    sys.path[:0] = [
        str(source / "scripts/branch-checked-packed-source"),
        str(HERE.parent / "branch-return-pmu"),
    ]
    import corrected
    import bindings as paths
    import qualify_e

    old = qualify_e.original
    helper = old.toolchain(trusted)
    root = helper.ROOT
    repo = root / "rust"
    rec = root / "receipts"
    log = rec / "R"
    log.mkdir()
    baseline = paths.PARK / "E"
    original_record = json.loads((paths.OUT / "sdk/E.json").read_bytes())
    old_files = {p: [x[0], x[4], x[3]] for p, x in original_record["files"].items()}
    reg.need(
        root == Path("/tmp/ohm-gnu-renderer-source-native")
        and root == Path(os.environ["QA_ROOT"])
        and paths.inventory(baseline) == original_record["files"]
        and len(old_files) == 81
        and shutil.disk_usage(root).free > 32 * 2**30,
        "canonical source, SDK or bootstrap capacity",
    )
    evidence = original_controls(paths.ROOT / "e-archives/first-session-linux-source-observations.zip")
    from source import live_base

    live_base(repo, helper.HERE / "packet")
    corrected.reg.source(repo, True, rec)
    corrected.verify(repo, corrected.load(), install=True)
    subject = reg.checked(repo, install=True)
    reg.need(
        corrected.old.verify_pack(repo, reg.P, reg.R, (HERE / "inputs/writer.pack").read_bytes()) == 31,
        "foreign child objects",
    )
    helper.git(repo, "checkout", "--detach", reg.R)
    helper.check_source(repo, reg.R)
    reg.need(not (repo / "build").exists(), "prior compiled source artifacts")
    for name, dst in (
        ("bin/cargo", root / "cargo/cargo-761"),
        (paths.WILD, root / "packages/sdk-21" / paths.WILD),
    ):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline / name, dst)
        reg.need(reg.sha(dst) == old_files[name][0], "foreign auxiliary native product")
    args = ["./x", *helper.OPTIONS, "build", *helper.HOST_FLAGS, *helper.SDK_COMPONENTS]
    reg.need(
        args == evidence["bootstrap"]["argv"] and str(repo) == evidence["bootstrap"]["cwd"],
        "bootstrap flags/path changed",
    )
    save(
        log / "source.json",
        {
            "product": subject,
            "previous": reg.P,
            "release_launcher": helper.launcher(repo),
            "llvm": helper.LLVM,
            "old_job": json.loads((paths.OUT / "sdk/authoritative-E.json").read_bytes()),
        },
    )
    helper.succeeded(args, repo, log / "bootstrap.log")
    stage = repo / "build" / helper.HOST / "stage1"
    stage0 = {
        "source": reg.sha(repo / "src/stage0"),
        **{n: reg.sha(stage.parent / "stage0/bin" / n) for n in ("rustc", "cargo")},
    }
    with zipfile.ZipFile(paths.ROOT / "e-archives/first-session-linux-source-driver.zip") as z:
        old_manifest = json.loads(z.read("manifest.json"))
    reg.need(
        stage0 == helper.STAGE0 == old_manifest["stage0"] and helper.LLVM == old_manifest["llvm"],
        "different bootstrap inputs",
    )
    selected = old.selected(helper, stage, root)
    before = helper.manifest(selected)
    different = {p for p, row in old_files.items() if row != before.get(p)}
    driver = original_record["driver"]
    reg.need(
        set(before) == set(old_files) and driver in different and different <= {driver, "bin/rustdoc"},
        ("unexpected SDK differences", sorted(different)),
    )
    originals = evidence["tests"]
    old_unit = "persist::fs::tests::pack_only_on_checkout_switch"
    new_units = [
        "persist::fs::tests::packing_follows_checkout_history",
        "persist::fs::packed::tests::restoring_a_check_alias_does_not_select_build_table_packing",
    ]
    need_units = originals["units"]["rustc_incremental"].copy()
    need_units.remove(old_unit)
    reg.need(
        len(need_units) == 9
        and len(originals["run_make"]) == 7
        and originals["units"]["rustc_fs_util"] == [],
        "incomplete inherited genuine suites",
    )
    expected = {
        "additional_linux_units": {"rustc_incremental": new_units, "rustc_fs_util": []},
        "additional_run_make": [],
        "delta": {"rows": [{"path": p} for p in subject["blobs"]]},
    }
    previous = {
        "unit": need_units,
        "run_make": originals["run_make"],
        "original_sources": originals["fixtures"],
    }
    qualify_e.tests(helper, repo, log, expected, previous)
    tests = json.loads((log / "checked-in-tests.json").read_bytes())
    reg.need(
        tests["fixtures"]["ohm-packed-branch-cache"]
        == subject["blobs"]["tests/run-make/ohm-packed-branch-cache/rmake.rs"][reg.R]["sha256"],
        "strengthened real run-make not executed",
    )
    reg.need(
        all(
            before[str(p)] == row
            for p, row in helper.manifest({k: p for k, p in selected.items() if p.is_file()}).items()
        ),
        "test rewrote a native member",
    )
    helper.succeeded(args, repo, log / "reassemble.log")
    selected = old.selected(helper, stage, root)
    reg.need(helper.manifest(selected) == before, "reassembled complete SDK changed")
    destination = paths.PARK / "R"
    destination.mkdir()
    for name, src in selected.items():
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src.resolve(), output)
    for rel in before:
        reg.need(not (baseline / rel).samefile(destination / rel), "SDK donor inode reused between arms")
    physical = paths.inventory(destination)
    reg.need({p: [x[0], x[4], x[3]] for p, x in physical.items()} == before, "R copied SDK closure")
    paths.save(paths.OUT / "sdk/R.json", {"role": "R", "source": reg.R, "driver": driver, "files": physical})
    # At a stable path the selected candidate links an ordinary rlib from the genuine parent.
    operational = root / "operational"
    alias = root / "rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(operational, target_is_directory=True)
    operational.symlink_to(baseline, target_is_directory=True)
    donor = log / "old-donor.rs"
    donor.write_text('pub fn value()->String{String::from("cross-stage1")}\n')
    helper.succeeded(
        [
            "rustc",
            "+ohm",
            donor,
            "--crate-name",
            "qa_donor",
            "--crate-type",
            "rlib",
            "-o",
            root / "libqa_donor.rlib",
        ],
        root,
        log / "old-donor.log",
        old.env_for(root),
    )
    operational.unlink()
    helper.operational(root, stage, selected, "C", log)
    reg.need(not operational.exists(), "unexpected active temporary SDK")
    operational.symlink_to(destination, target_is_directory=True)
    old.native(helper, root, destination, log, "R")
    # Its checked-in real native provider passes higher, equal-stat, damaged and repaired archives vs empty.
    paired = root / "mixed-real-cache"
    paired.mkdir()
    mixed = compat.fixture(
        paired,
        {
            "P": {"source": reg.P, "sdk": str(baseline), "members": {p: r[0] for p, r in old_files.items()}},
            "R": {"source": reg.R, "sdk": str(destination), "members": {p: r[0] for p, r in before.items()}},
        },
        False,
    )
    shutil.copytree(paired / "raw", log / "mixed-native")
    shutil.copy2(paired / "report.json", log / "mixed.json")
    reg.need(
        mixed["sdk_drivers"]["R"] == before[driver][0] and mixed["sdk_drivers"]["P"] == old_files[driver][0],
        "mixed native test did not consume the two enrolled drivers",
    )
    helper.check_source(repo, reg.R)
    reg.need(
        paths.inventory(baseline) == original_record["files"] and paths.inventory(destination) == physical,
        "SDK changed during source checks",
    )
    overlay_manifest = overlay.archive(log / "overlay", destination, old_files, before, driver)
    save(
        paths.OUT / "sdk/R-source-qualified.json",
        {
            "old": reg.P,
            "new": reg.R,
            "source": reg.sha(log / "source.json"),
            "old_driver": old_files[driver],
            "new_driver": before[driver],
            "stage0": stage0,
            "llvm": helper.LLVM,
            "members": len(before),
            "changed": sorted(different),
            "units": tests["units"],
            "run_make": tests["run_make"],
            "native": reg.sha(log / "native-shadow/complete.json"),
            "mixed": reg.sha(log / "mixed.json"),
            "overlay": overlay_manifest,
            "tests": reg.sha(log / "checked-in-tests.json"),
            "qa": os.environ["GITHUB_SHA"],
            "run": int(os.environ["GITHUB_RUN_ID"]),
        },
    )
    # Only the completed bootstrap's own checked and separate temporary build can be removed.
    build = repo / "build"
    reg.need(
        build.is_dir()
        and not build.is_symlink()
        and build.resolve() == repo.resolve() / "build"
        and not any(
            Path(i.split(" - ")[0].split()[4]).is_relative_to(build)
            for i in Path("/proc/self/mountinfo").read_text().splitlines()
        ),
        "unowned bootstrap output",
    )
    shutil.rmtree(build)
    reg.need(
        paths.inventory(destination) == physical and paths.inventory(baseline) == original_record["files"],
        "bootstrap cleanup changed an SDK",
    )


if __name__ == "__main__":
    main(*[Path(p).resolve() for p in sys.argv[1:]])
