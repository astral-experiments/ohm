"""Run the merged coordinator's actual tests on the historical and rebased native tools."""

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from qualify import BIND, CHILD, PARENT, checksum, git, guard, need, save, verify_live

WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
RUSTUP = shutil.which("rustup")
OLD_CARGO = "4591cf45cc10abb19d2456c40b99606e08167f29"
DIRECT_PARENT = "7b643c384568b1598373dc209fcb7c05162e6547"
PARENT_TREE = "617bbc1608e5c456eae6b85997d399bdfb041f39"


def run(argv, env, **kw):
    return subprocess.check_output(list(map(str, argv)), env=env, text=True, **kw).strip()


def toolchain(root, sdk, cargo, host, wild):
    """Give rustup a private sysroot spelling and leave both captured SDKs untouched."""
    bin_dir = Path("lib/rustlib") / host / "bin"
    directories = [Path("."), Path("bin"), Path("lib"), Path("lib/rustlib"), bin_dir.parent, bin_dir]
    if wild is not None:
        directories.append(bin_dir / "wild-ld")
    for name in directories:
        (root / name).mkdir(parents=True, exist_ok=True)
    (driver,) = (sdk / "lib").glob("librustc_driver-*")
    reserved = {Path("bin/rustc"), Path("bin/cargo"), driver.relative_to(sdk), *directories}
    if wild is not None:
        reserved.add(bin_dir / "wild-ld/ld.bfd")
    for directory in directories:
        donor = sdk / directory
        if donor.is_dir():
            for source in donor.iterdir():
                item = directory / source.name
                if item not in reserved:
                    (root / item).symlink_to(source, target_is_directory=source.is_dir())
    # Rustup can resolve the selected frontend. Rust then finds its sysroot relative to
    # the canonical path of its mapped driver. Keep both files resident in this view.
    shutil.copy2(sdk / "bin/rustc", root / "bin/rustc")
    shutil.copy2(driver, root / driver.relative_to(sdk))
    (root / "bin/cargo").symlink_to(cargo)
    if wild is not None:
        need(checksum(wild) == WILD, "different bundled GNU Wild")
        (root / bin_dir / "wild-ld/ld.bfd").symlink_to(wild)


def identities(root, sdk, cargo, rust_revision, cargo_revision, host, env):
    versions = {}
    for tool, revision, source in [
        ("rustc", rust_revision, sdk / "bin/rustc"),
        ("cargo", cargo_revision, cargo),
    ]:
        selected = Path(run([RUSTUP, "which", "--toolchain", "ohm", tool], env))
        vv = run([tool, "+ohm", "-vV"], env)
        need(
            checksum(selected) == checksum(source)
            and "host: " + host in vv.splitlines()
            and "commit-hash: " + revision in vv.splitlines(),
            "wrong active " + tool,
        )
        versions[tool] = {"sha256": checksum(source), "path": str(selected), "version": vv}
    need(Path(run(["rustc", "+ohm", "--print", "sysroot"], env)).samefile(root), "wrong sysroot")
    lib = Path(run(["rustc", "+ohm", "--print", "target-libdir"], env))
    (std,) = lib.glob("libstd-*.rlib")
    need(std.samefile(sdk / "lib/rustlib" / host / "lib" / std.name), "wrong native std")
    (driver,) = (root / "lib").glob("librustc_driver-*")
    need(
        not driver.is_symlink() and checksum(driver) == checksum(sdk / "lib" / driver.name),
        "wrong native driver",
    )
    versions["driver"] = {"sha256": checksum(driver), "path": str(driver.resolve())}
    versions["std"] = checksum(std)
    return versions


def smoke(script, label, project, folder, env, historical=False):
    log = folder / (label + ".log")
    argv = ["bash", "-x", str(script), "ohm", str(project)]
    with log.open("xb") as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, env=env)
    # Preserve whichever programs the coordinator really produced, including a failure
    # between its assertions. The raw script runs each program before checking its tag.
    indexed = {}
    bodies = folder / "bodies"
    bodies.mkdir(exist_ok=True)
    for variant in ("target", "marked-declared-target", "marked-target"):
        for name in ("first", "second"):
            image = project / "declared" / variant / "debug" / name
            if image.is_file():
                need(0 < image.stat().st_size <= 16 << 20, "unexpected native fixture size")
                digest = checksum(image)
                dest = bodies / (digest + ".native")
                if not dest.exists():
                    shutil.copyfile(image, dest)
                need(checksum(dest) == digest, "stored fixture executable differs")
                indexed[f"{variant}/{name}"] = digest
    save(
        folder / (label + "-observed.json"),
        dict(code=result.returncode, programs=indexed, log_sha256=checksum(log)),
    )
    text = log.read_text(errors="replace")
    reason = "Expected 0 linker calls for two executables returning 17, observed 2"
    old_refusal = historical and result.returncode == 1 and reason in text.splitlines()
    need(result.returncode == 0 or old_refusal, f"unexpected {label} outcome; see {log}")
    expected = [("target", "29")]
    if script.name == "smoke-test-relink.sh" and script.parent.name == "release-22":
        expected.append(("marked-declared-target", "17" if old_refusal else "29"))
    if not old_refusal:
        expected.append(("marked-target", "37"))
        bad = project / "declared/bad-archive.log"
        need(
            bad.is_file() and "libanswer.a" in bad.read_text(errors="replace"),
            "no authentic malformed-archive diagnostic",
        )
        shutil.copyfile(bad, folder / (label + "-bad-archive.log"))
    outputs = {}
    for target, tag in expected:
        for name in ("first", "second"):
            exe = project / "declared" / target / "debug" / name
            need(run([exe], env) == tag, "different underlying native output")
            outputs[f"{target}/{name}"] = dict(sha256=checksum(exe), tag=tag, bytes=exe.stat().st_size)
    receipt = dict(
        argv=argv,
        code=result.returncode,
        old_refusal=old_refusal,
        smoke_sha256=checksum(script),
        log_sha256=checksum(log),
        final_native=outputs,
    )
    save(folder / (label + ".json"), receipt)
    return receipt


def build_cargo(src, sdk, work, folder, env, revision):
    reservation = 5 if revision == DIRECT_PARENT else 12
    need(shutil.disk_usage(work).free > reservation << 30, "insufficient room for the Cargo build")
    tree = {BIND["trees"]["src/tools/cargo"]: BIND["cargo_tree"], DIRECT_PARENT: PARENT_TREE}[revision]
    need(git(src, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [revision, tree], "unbound Cargo")
    # The original #382 GNU qualification used this source/feature combination.
    # Hold both build paths fixed for the optional immediate-parent comparison.
    target = work / "cargo-build"
    stage = dict(
        env,
        RUSTC=str(sdk / "bin/rustc"),
        RUSTDOC=str(sdk / "bin/rustdoc"),
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_INCREMENTAL="0",
        CFG_RELEASE="1.99.0-dev",
        CFG_RELEASE_CHANNEL="dev",
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_BUILD_DIR=str(work / "build-intermediates"),
    )
    argv = [
        sdk / "bin/cargo",
        "-Zohm-defaults=no",
        "build",
        "--locked",
        "-p",
        "cargo",
        "--bin",
        "cargo",
        "--features",
        "all-static,ohm-defaults",
        "-j8",
    ]
    save(folder / "build-argv.json", list(map(str, argv)))
    with (folder / "build.log").open("xb") as stream:
        subprocess.run(argv, cwd=src, env=stage, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = target / "debug/cargo"
    need("commit-hash: " + revision in run([result, "-vV"], env).splitlines(), "wrong built Cargo commit")
    return result


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith(("CARGO_", "RUST", "OHM_", "LLVM_"))}


def qualify(w, repo, r, tmp, host):
    verify_live(repo)
    need(RUSTUP and shutil.disk_usage(tmp).free > 4 << 30, "rustup or free space unavailable")
    work = tmp / "release-link-smoke"
    work.mkdir()
    folder = r / "slot-link-smoke"
    folder.mkdir()
    darwin = platform.system() == "Darwin"
    old = tmp / ("slot-old-apple/sdk" if darwin else "packaged-linux-50/sdk-22")
    candidate = repo / "build" / host / ("stage2" if darwin else "stage1")
    new_cargo = repo / "build" / host / "stage2-tools-bin/cargo"
    env = clean_env()
    env["CARGO_HOME"] = str(work / "registry")
    if not darwin:
        new_cargo = build_cargo(
            repo / "src/tools/cargo", old, work, folder, env, BIND["trees"]["src/tools/cargo"]
        )
    proxies = work / "proxies"
    proxies.mkdir()
    for name in ("rustc", "cargo"):
        (proxies / name).symlink_to(Path(RUSTUP).resolve(strict=True))
    env["PATH"] = str(proxies) + os.pathsep + env["PATH"]
    env["RUSTUP_HOME"] = str(work / "rustup")
    wild = None if darwin else old / "lib/rustlib" / host / "bin/wild-ld/ld.bfd"
    smoke_script = HERE / "release-22/smoke-test-relink.sh"
    need(checksum(smoke_script) == BIND["release_files"][smoke_script.name][1], "changed release smoke")
    # The program exercises declared 0/2/0, then undeclared same-stat replacement, malformed input and repair.
    results = {}
    for role, sdk, rust_revision, cargo, cargo_revision in (
        ("historical", old, PARENT, old / "bin/cargo", OLD_CARGO),
        ("cargo-only", old, PARENT, new_cargo, BIND["trees"]["src/tools/cargo"]),
        ("rebased", candidate, CHILD, new_cargo, BIND["trees"]["src/tools/cargo"]),
    ):
        need(shutil.disk_usage(work).free > 4 << 30, "less than 4 GiB before linked smoke")
        parked = work / role
        parked.mkdir()
        view = work / "sdk"
        toolchain(view, sdk, cargo, host, wild)
        if role == "historical":
            run([RUSTUP, "toolchain", "link", "ohm", view], env)
        if darwin:
            env["LLVM_PROFILE_FILE"] = str(work / "identity-and-smoke-%m.profraw")
        versions = identities(view, sdk, cargo, rust_revision, cargo_revision, host, env)
        save(folder / (role + "-tools.json"), versions)
        project = work / "project"
        got = smoke(smoke_script, role, project, folder, env, role == "historical")
        project.rename(parked / "project")
        if got["old_refusal"]:
            # The old reader exits at the known 2-vs-0 assertion. The predecessor script
            # independently reaches and checks the entire genuinely undeclared tail.
            prior = w / "scripts/smoke-test-relink.sh"
            need(
                git(w, "hash-object", prior) == "3743c253445a2b796445a90fe31c08db53304ba8",
                "foreign historical control",
            )
            smoke(prior, "historical-undeclared", project, folder, env)
            project.rename(parked / "undeclared-project")
        results[role] = {"versions": versions, "smoke": got}
        if role != "rebased":
            view.rename(parked / "sdk")
    need(
        results["cargo-only"]["versions"]["cargo"]["sha256"]
        == results["rebased"]["versions"]["cargo"]["sha256"]
        and results["historical"]["versions"]["driver"]["sha256"]
        == results["cargo-only"]["versions"]["driver"]["sha256"],
        "physical role crossover failed",
    )
    save(
        folder / "complete.json",
        dict(qualified=True, host=host, coordinator=BIND["release_coordinator"], results=results),
    )


def capture_transitive(work, folder, revision, host, env):
    probe = HERE / "gnu_transitive.py"
    need(
        checksum(probe) == "ed5166df83e6b6230e134e33b30be5bf398f0992312d3777d5c63fb64ae218d4",
        "different transitive probe",
    )
    project = work / "transitive"
    view = work / "sdk"
    wild = view / "lib/rustlib" / host / "bin/wild-ld/ld.bfd"
    need(checksum(wild) == WILD, "different GNU Wild")
    argv = [sys.executable, "-IB", probe, project, "--wild-dir", wild.parent, "--cargo", "--toolchain", "ohm"]
    save(folder / "argv.json", list(map(str, argv)))
    with (folder / "log").open("xb") as log:
        proc = subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
    # An incorrect warm verdict is an observable result. Escrow the raw commands,
    # link reports, provider bytes and final native programs before checking parity.
    if (project / "results").is_dir():
        shutil.copytree(project / "results", folder / "raw")
    if (project / "native").is_dir():
        shutil.copytree(project / "native", folder / "native")
    products = {}
    for lane in ("warm", "new-clean", "bad-clean", "old-clean"):
        p = project / lane / "target/debug/reader"
        if p.is_file():
            key = checksum(p)
            need(p.stat().st_size <= 16 << 20, "unexpected fixture executable size")
            if key not in products.values():
                shutil.copyfile(p, folder / (key + ".native"))
            products[lane] = key
    save(folder / "products.json", products)
    need(proc.returncode == 0, "supplementary probe did not complete; original output retained")
    observed = json.loads((folder / "raw/evidence.json").read_bytes())
    for tool, commit in [("rustc", CHILD), ("cargo", revision)]:
        need(
            "commit-hash: " + commit in observed[tool + "_version"].splitlines(),
            "foreign supplementary " + tool,
        )
    outcome = assess_transitive(observed)
    for phase, row in observed["cargo"].items():
        if row["status"] == 0:
            need(
                (folder / "raw" / ("exec-" + phase + ".stdout")).read_bytes().strip()
                == str(row["value"]).encode(),
                "actual native stdout differs from the recorded tag",
            )
    for phase in ("bad-clean", "bad"):
        if observed["cargo"][phase]["status"] == 101:
            raw = b"".join(
                (folder / "raw" / ("cargo-" + phase + "." + stream)).read_bytes()
                for stream in ("stdout", "stderr")
            )
            need(
                b"missing-real-ohm-transitive-provider" in raw or b"libohm_private.so" in raw,
                "unrelated failure on malformed native input",
            )
    for lane, phase in [("warm", "restored"), ("new-clean", "new-clean"), ("old-clean", "old-clean")]:
        need(products[lane] == observed["cargo"][phase]["elf"], "registered final bodies do not match")
    save(folder / "verdict.json", outcome)
    return outcome


def preserve_cargo(binary, folder, revision, env):
    vv = run([binary, "-vV"], env)
    need(
        "commit-hash: " + revision in vv.splitlines() and 0 < binary.stat().st_size <= 256 << 20,
        "foreign or oversized Cargo witness",
    )
    dest = folder / "cargo.native"
    shutil.copy2(binary, dest)
    need(checksum(dest) == checksum(binary), "different copied Cargo")
    save(
        folder / "cargo-image.json",
        dict(source=revision, sha256=checksum(dest), bytes=dest.stat().st_size, version=vv),
    )


def transitive(w, repo, r, tmp, host):
    verify_live(repo)
    need(host == "x86_64-unknown-linux-gnu", "GNU-only supplementary control")
    work = tmp / "release-link-smoke"
    prior = json.loads((r / "slot-link-smoke/complete.json").read_bytes())
    need(prior["qualified"] and prior["host"] == host, "missing original native link tests")
    folder = r / "slot-transitive-provider"
    folder.mkdir()
    env = clean_env()
    env["CARGO_HOME"] = str(work / "registry")
    env.update(RUSTUP_HOME=str(work / "rustup"), PATH=str(work / "proxies") + os.pathsep + env["PATH"])
    for tool in ("rustc", "cargo"):
        selected = Path(run([RUSTUP, "which", "--toolchain", "ohm", tool], env))
        need(
            checksum(selected) == prior["results"]["rebased"]["versions"][tool]["sha256"],
            "supplementary tool changed",
        )
    new = BIND["trees"]["src/tools/cargo"]
    fixed = folder / "candidate"
    fixed.mkdir()
    outcome = capture_transitive(work, fixed, new, host, env)
    if outcome["qualified"]:
        return

    # Rebuild at the identical Cargo source and target paths only on a genuine
    # new-vs-empty disagreement. Preserve the original binary before reusing its target.
    need(shutil.disk_usage(work).free > 5 << 30, "insufficient space for both parent comparison images")
    sub = repo / "src/tools/cargo"
    need(
        git(sub, "rev-parse", new + "^", DIRECT_PARENT + "^{tree}").splitlines()
        == [DIRECT_PARENT, PARENT_TREE],
        "different immediate native-link parent",
    )
    reusable = work / "cargo-build/debug/cargo"
    need((work / "sdk/bin/cargo").samefile(reusable), "would replace a different Cargo")
    preserve_cargo(reusable, fixed, new, env)
    (work / "transitive").rename(work / "transitive-candidate")
    parent = folder / "direct-parent"
    parent.mkdir()
    try:
        git(sub, "checkout", "--detach", "--quiet", DIRECT_PARENT)
        old = tmp / "packaged-linux-50/sdk-22"
        built = build_cargo(sub, old, work, parent, env, DIRECT_PARENT)
        need(built.samefile(reusable), "immediate-parent executable path changed")
        preserve_cargo(built, parent, DIRECT_PARENT, env)
        capture_transitive(work, parent, DIRECT_PARENT, host, env)
    finally:
        git(sub, "checkout", "--detach", "--quiet", new)
        restored = work / "sdk/bin/cargo.original"
        restored.symlink_to(fixed / "cargo.native")
        os.replace(restored, work / "sdk/bin/cargo")
        need(
            checksum(work / "sdk/bin/cargo") == prior["results"]["rebased"]["versions"]["cargo"]["sha256"],
            "original candidate Cargo was not restored",
        )
        verify_live(repo)
    raise ValueError(
        "pinned Cargo warm and independently empty provider outcomes differ; both actual roles escrowed"
    )


def assess_transitive(observed):
    need(observed["wild"]["sha256"] == WILD, "different direct Wild")
    direct = [("old", 17), ("new", 29), ("bad", None), ("restored", 17)]
    for linker in ("gnu", "wild"):
        for phase, value in direct:
            row = observed["direct"][linker][phase]
            need(
                row["exit"] == value and ((row["link"] == 0) == (value is not None)),
                "incorrect real linker control",
            )
        old, new = [observed["direct"][linker][k]["depfile"] for k in ("old", "new")]
        need(
            "libohm_private.a" in old and "libohm_private.so" not in old and "libohm_private.so" in new,
            "direct linker report does not establish the newly preferred name",
        )
    expected = {
        "seed": (0, 17),
        "unchanged": (0, 17),
        "new": (0, 29),
        "new-clean": (0, 29),
        "bad": (101, None),
        "bad-clean": (101, None),
        "restored": (0, 17),
        "old-clean": (0, 17),
    }
    rows = observed["cargo"]
    need(set(rows) == set(expected), "incomplete ordinary Cargo matrix")
    for stage, row in rows.items():
        cmd = observed["commands"]["cargo-" + stage]
        need(
            cmd["status"] == row["status"]
            and cmd["argv"][1:] == ["+ohm", "build", "--offline", "--message-format=json"],
            "different raw Cargo command",
        )
        need(
            isinstance(row["closures"], dict)
            and all(Path(p).parts[-2:] == ("declared-native", "inputs.json") for p in row["closures"]),
            "unrecognized closure source",
        )
    real = {k: (v["status"], v.get("value")) for k, v in rows.items()}
    need(
        all(real[k] == expected[k] for k in ("seed", "new-clean", "bad-clean", "old-clean")),
        "independent references failed",
    )
    matched = {
        k: rows[k].get("elf") == rows[epoch]["elf"]
        for k, epoch in [
            ("seed", "old-clean"),
            ("unchanged", "old-clean"),
            ("new", "new-clean"),
            ("restored", "old-clean"),
        ]
    }
    return {
        "qualified": real == expected and all(matched.values()),
        "outcomes": real,
        "warm_empty_elf_equal": matched,
        "links": {k: v["links"] for k, v in rows.items()},
        "declared_manifests": {k: len(v["closures"]) for k, v in rows.items()},
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["transitive"]:
        transitive(*guard())
    elif not sys.argv[1:]:
        qualify(*guard())
    else:
        raise SystemExit("expected release_smoke.py [transitive]")
