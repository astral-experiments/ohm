"""Build one authenticated native compiler and exercise the exact private codec/ABI boundaries."""

import json, os, re, shutil, subprocess, sys, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binding as reg
import overlay


def acquire(source):
    reg.job()
    sys.path.insert(0, str(HERE.parent / "branch-storage-e-confirmation"))
    import policy

    b = policy.b
    reg.need(
        b.git(source, "rev-parse", "HEAD") == reg.SOURCE_QA and not b.PARK.exists(),
        "source checkout or nonempty SDK",
    )
    original = policy.checked_source.enrollment()
    policy.checked_source.official(
        lambda p: json.loads(subprocess.check_output(["gh", "api", "repos/" + b.REPO + "/actions/" + p])),
        original,
    )
    rows = policy.acquire(source)["E"]
    reg.need(
        len(rows) == 81 and rows["bin/cargo"][0] == b.CARGO_ELF and rows[b.WILD][0] == b.WILD_ELF,
        "source SDK incomplete",
    )
    b.save(b.OUT / "sdk/authoritative-E.json", original)


def unit_log(body):
    names = ["aliases_preserve_allocation_identity", "only_the_original_ctfe_literal_id_is_restored"]
    clean = re.sub(r"\x1b\[[0-9;]*m", "", body)
    for n in names:
        reg.need(
            re.findall(r"^test mir::interpret::tests::" + n + r" \.\.\. ok$", clean, re.M)
            == ["test mir::interpret::tests::" + n + " ... ok"],
            "missing native compiler unit " + n,
        )
    reg.need(
        "test result: ok." in clean
        and "test result: FAILED" not in clean
        and "internal compiler error" not in clean,
        "failed native compiler units",
    )
    return names


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
    log = rec / "C"
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
    with zipfile.ZipFile(paths.ROOT / "e-archives/first-session-linux-source-observations.zip") as original:
        evidence = json.loads(original.read("E/bootstrap.command.json"))
    original = json.loads((HERE / "inputs/bootstrap.json").read_bytes())
    reg.need(all(evidence[k] == v for k, v in original.items()), "foreign original bootstrap receipt")
    from source import live_base

    live_base(repo, helper.HERE / "packet")
    corrected.reg.source(repo, True, rec)
    corrected.verify(repo, corrected.load(), install=True)
    subject = reg.validate(repo, install=True)
    reg.need(
        corrected.old.verify_pack(repo, reg.OLD, reg.NEW, (HERE / "inputs/child.pack").read_bytes()) == 20,
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
    # Preserve reconstructible native bytes before any named gate can refuse the build.
    destination = paths.PARK / "C"
    destination.mkdir()
    for name, src in selected.items():
        output = destination / name
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src.resolve(), output)
    for rel in before:
        reg.need(not (baseline / rel).samefile(destination / rel), "SDK donor inode reused between arms")
    physical = paths.inventory(destination)
    reg.need({p: [x[0], x[4], x[3]] for p, x in physical.items()} == before, "C copied SDK closure")
    paths.save(
        paths.OUT / "sdk/C.json", {"role": "C", "source": reg.NEW, "driver": driver, "files": physical}
    )
    capsule = overlay.archive(log / "overlay", destination, old_files, before, driver)
    args_test = ["./x", *helper.OPTIONS, "--set", "rust.verbose-tests=true", "test", *helper.HOST_FLAGS]
    helper.succeeded([*args_test, "--tests", "compiler/rustc_middle"], repo, log / "middle.log")
    units = unit_log((log / "middle.log").read_text(errors="replace"))
    cases = [reg.TEST, "incremental-missing-query-cache"]
    for case in cases:
        logfile = log / (case + ".log")
        helper.succeeded([*args_test, "tests/run-make/" + case], repo, logfile)
        helper.verdict(logfile.read_text(errors="replace"), case, True, 0)
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
    for role, sdk in (("E", baseline), ("C", destination)):
        helper.succeeded(
            [
                sys.executable,
                "-IB",
                HERE / "collision.py",
                "--sdk",
                sdk,
                "--out",
                log / ("collision-" + role),
            ],
            root,
            log / ("collision-" + role + ".log"),
        )
        accepted = json.loads((log / ("collision-" + role) / "result.json").read_bytes())
        reg.need(
            accepted["driver"] == (old_files if role == "E" else before)[driver][0],
            "wrong collision compiler",
        )
    helper.succeeded(
        [
            sys.executable,
            "-IB",
            HERE / "generations.py",
            "--old",
            baseline,
            "--candidate",
            destination,
            "--out",
            log / "generations",
        ],
        root,
        log / "generations.log",
    )
    report = json.loads((log / "generations/result.json").read_bytes())
    reg.need(
        not report["emulated_new_header"]
        and {n: v["driver"] for n, v in report["sdk"].items()}
        == {"E": old_files[driver][0], "C": before[driver][0]},
        "wrong migration compilers",
    )
    reg.need(
        paths.inventory(baseline) == original_record["files"] and paths.inventory(destination) == physical,
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
            "migration": reg.sha(log / "generations/result.json"),
            "collisions": {
                role: reg.sha(log / ("collision-" + role) / "result.json") for role in ("E", "C")
            },
            "qa": os.environ["GITHUB_SHA"],
            "run": os.environ["GITHUB_RUN_ID"],
        },
    )
    # All inputs and both active physical SDKs are outside this ephemeral, validated build.
    build = repo / "build"
    reg.need(
        build.resolve() == build and build.parent == repo and not build.is_mount(),
        "unexpected bootstrap directory",
    )
    shutil.rmtree(build)


if __name__ == "__main__":
    if sys.argv[1] == "restore":
        acquire(Path(sys.argv[2]).resolve())
    elif sys.argv[1] == "build":
        main(Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve())
    else:
        raise SystemExit("restore SOURCE | build SOURCE TRUSTED")
