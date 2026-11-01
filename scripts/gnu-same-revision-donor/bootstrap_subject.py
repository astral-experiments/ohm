"""Build the registered selector compiler from the original stage inputs on the authenticated D SDK and check the SDK delta."""

import json, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding as reg
import overlay
import transplant


def acquire(source, donor):
    """Use the immutable, previously qualified E-to-D Actions intake with its own module identities."""
    import importlib.util
    reg.job()
    reg.need(reg.rev(donor, "HEAD") == reg.DONOR_QA, "wrong immutable D intake")
    reader = donor / "scripts/ctfe-crossover-pilot/subjects.py"
    spec = importlib.util.spec_from_file_location("prior_donor_subjects", reader)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    rows = original.acquire(source)
    reg.need(set(rows) == {"E", "D"} and len(rows["D"]) == 81
             and rows["D"][original.DRIVER][0] == "f724a33d4d865ac4f3fc235b322a638d6f6534f669e5b1659adabcd04a2221d7",
             "missing genuine original D compiler")
    owner = original.policy().b
    with zipfile.ZipFile(owner.ROOT / "donor-originals" / (original.SOURCE_ARTIFACT + ".zip")) as archive:
        log = archive.read("D/incremental.log")
    transplant.prior_suite(log)
    (owner.OUT / "sdk/donor-incremental.log").write_bytes(log)


def unit_log(body):
    """Require a successfully executed test function for each frozen behavior."""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", body)
    names = reg.UNITS
    for name in names:
        full = "persist::fs::tests::" + name
        reg.need(
            len(re.findall(r"^test " + re.escape(full) + r" \.\.\. ok$", clean, re.M)) == 1,
            "missing or duplicated native compiler test: " + full,
        )
    reg.need(
        re.search(r"^test result: ok\. [1-9][0-9]* passed; 0 failed;", clean, re.M)
        and "test result: FAILED" not in clean
        and "internal compiler error" not in clean,
        "compiler unit tests failed",
    )
    return sorted(names)


def main(source, trusted):
    reg.job()
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
    log = rec / "P"
    log.mkdir()
    baseline = paths.PARK / "D"
    original_record = json.loads((paths.OUT / "sdk/D.json").read_bytes())
    old_files = {p: [x[0], x[4], x[3]] for p, x in original_record["files"].items()}
    reg.need(
        root == Path("/tmp/ohm-gnu-renderer-source-native")
        and root == Path(os.environ["QA_ROOT"])
        and paths.inventory(baseline) == original_record["files"]
        and len(old_files) == 81
        and shutil.disk_usage(root).free > 32 * 2**30,
        "canonical source, SDK or bootstrap capacity",
    )
    with zipfile.ZipFile(
        paths.ROOT / "e-archives/first-session-linux-source-observations.zip"
    ) as original:
        evidence = json.loads(original.read("E/bootstrap.command.json"))
    original = json.loads((HERE / "inputs/bootstrap.json").read_bytes())
    reg.need(
        all(evidence[k] == v for k, v in original.items()), "foreign original bootstrap receipt"
    )
    from source import live_base

    live_base(repo, helper.HERE / "packet")
    corrected.reg.source(repo, True, rec)
    corrected.verify(repo, corrected.load(), install=True)
    parent_pack = HERE / "inputs/parent-D.pack"
    parent = HERE / "inputs/parent-D.json"
    reg.need(reg.sha(parent) == "329fd87fb40040c9d37afdeeb2586df756e7bbe33ca1d0d6493e7d4a99646623"
             and reg.sha(parent_pack) == json.loads(parent.read_bytes())["pack"]["sha256"], "wrong original D source")
    reg.git(repo, "index-pack", "--stdin", body=parent_pack.read_bytes())
    reg.need(corrected.old.verify_pack(repo, reg.ORIGINAL, reg.OLD, parent_pack.read_bytes()) == 9
             and reg.rev(repo, reg.OLD + "^{tree}") == json.loads(parent.read_bytes())["source"]["tree"],
             "incomplete preceding D source")
    subject = reg.validate(repo, install=True)
    reg.need(
        corrected.old.verify_pack(repo, reg.OLD, reg.NEW, (HERE / "inputs/child.pack").read_bytes())
        == subject["pack"]["count"],
        "foreign child objects",
    )
    helper.git(repo, "checkout", "--detach", reg.NEW)
    helper.check_source(repo, reg.NEW)
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
        args == evidence["argv"] and str(repo) == evidence["cwd"],
        "bootstrap flags/path changed",
    )
    reg.save(
        log / "source.json",
        {
            "product": subject,
            "previous": reg.OLD,
            "release_launcher": helper.launcher(repo),
            "llvm": helper.LLVM,
            "old_job": json.loads((paths.OUT / "sdk/donor-official.json").read_bytes()),
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
        set(before) == set(old_files)
        and driver in different
        and different <= {driver, "bin/rustdoc"},
        ("unexpected SDK differences", sorted(different)),
    )
    # Preserve reconstructible native bytes before any named gate can refuse the build.
    destination = paths.PARK / "P"
    destination.mkdir()
    for name, src in selected.items():
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src.resolve(), output)
    for rel in before:
        reg.need(
            not (baseline / rel).samefile(destination / rel), "SDK donor inode reused between arms"
        )
    physical = paths.inventory(destination)
    reg.need(
        {p: [x[0], x[4], x[3]] for p, x in physical.items()} == before,
        "candidate copied SDK closure",
    )
    paths.save(
        paths.OUT / "sdk/P.json",
        {"role": "P", "source": reg.NEW, "driver": driver, "files": physical},
    )
    capsule = overlay.archive(log / "overlay", destination, old_files, before, driver)
    args_test = [
        "./x",
        *helper.OPTIONS,
        "--set",
        "rust.verbose-tests=true",
        "test",
        *helper.HOST_FLAGS,
    ]
    helper.succeeded(
        [*args_test, "--tests", "compiler/rustc_incremental"], repo, log / "incremental.log"
    )
    actual = (log / "incremental.log").read_text(errors="replace")
    units = unit_log(actual)
    transplant.outcomes(actual, False)
    transplant.run(helper, repo, log, [*args_test, "--tests", "compiler/rustc_incremental"], subject)
    cases = reg.RUN_MAKE
    for case in cases:
        logfile = log / (case + ".log")
        helper.succeeded([*args_test, "tests/run-make/" + case], repo, logfile)
        helper.verdict(logfile.read_text(errors="replace"), case, True, 0)
    reg.need(
        all(
            before[str(p)] == row
            for p, row in helper.manifest(
                {k: p for k, p in selected.items() if p.is_file()}
            ).items()
        ),
        "test rewrote a native member",
    )
    helper.succeeded(args, repo, log / "reassemble.log")
    selected = old.selected(helper, stage, root)
    reg.need(helper.manifest(selected) == before, "reassembled complete SDK changed")
    reg.need(
        paths.inventory(baseline) == original_record["files"]
        and paths.inventory(destination) == physical,
        "SDK mutated by control",
    )
    reg.save(
        log / "native-qualified.json",
        {
            "old": reg.OLD,
            "new": reg.NEW,
            "tree": reg.TREE,
            "stage0": stage0,
            "llvm": helper.LLVM,
            "bootstrap": args,
            "driver": driver,
            "old_driver": old_files[driver],
            "new_driver": before[driver],
            "units": units,
            "run_make": cases,
            "overlay": capsule,
            "qa": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
        },
    )
    # Both source products and their complete manifests are outside this ephemeral, validated build.
    build = repo / "build"
    reg.need(
        build.resolve() == build and build.parent == repo and not build.is_mount(),
        "unexpected bootstrap directory",
    )
    shutil.rmtree(build)


if __name__ == "__main__":
    if sys.argv[1] == "restore":
        acquire(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    elif sys.argv[1] == "build":
        main(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    else:
        raise SystemExit("restore SOURCE PRIOR_D_INTAKE | build SOURCE TRUSTED")
