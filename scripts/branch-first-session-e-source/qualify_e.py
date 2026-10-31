"""Bootstrap only E, beside the original K. No Ruff performance measurements run here."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subject as s
import prior
import restore_e
import cross_reader
import qualify as original
from registration import need, sha, write


def unit_record(text, crate, expected):
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    need(not re.search(r"(?m)^\s*Doc-tests ", text), "mixed unit/rustdoc stream " + crate)
    suites = re.findall(
        r"(?m)^\s*Running unittests src/lib\.rs \(.*?/build/(rustc_fs_util|rustc_incremental)/.*?/out/(?:rustc_fs_util|rustc_incremental)-[a-z0-9]+\)$",
        text,
    )
    passed = re.findall(r"(?m)^test (\S+) \.\.\. ok$", text)
    totals = re.findall(
        r"(?m)^test result: ok\. (\d+) passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
        text,
    )
    need(
        suites == [crate]
        and sorted(passed) == sorted(expected)
        and totals == [str(len(expected))]
        and len(re.findall(r"(?m)^test result:", text)) == 1
        and "test result: FAILED" not in text
        and re.findall(r"(?m)^running (\d+) tests?$", text) == [str(len(expected))],
        "incomplete native unit suite " + crate,
    )
    return sorted(passed)


DOC_TEST = "compiler/rustc_incremental/src/assert_dep_graph.rs - assert_dep_graph (line 25)"


def doc_record(text, crate):
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    ignored = [DOC_TEST] if crate == "rustc_incremental" else []
    need(
        re.findall(r"(?m)^\s*Doc-tests (\w+)$", text) == [crate]
        and not re.search(r"(?m)^\s*Running unittests ", text)
        and re.findall(r"(?m)^running (\d+) tests?$", text) == [str(len(ignored))]
        and re.findall(r"(?m)^test (.+) \.\.\. (\w+)$", text) == [(n, "ignored") for n in ignored]
        and re.findall(r"(?m)^test result: (.+?); finished in ", text)
        == [f"ok. 0 passed; 0 failed; {len(ignored)} ignored; 0 measured; 0 filtered out"]
        and len(re.findall(r"(?m)^test result:", text)) == 1
        and "test result: FAILED" not in text,
        "incomplete independent rustdoc suite " + crate,
    )
    return ignored


def individual(command, text, crate, switch):
    need(
        command["returncode"] == 0
        and command["output_sha256"] == hashlib.sha256(text).hexdigest()
        and command["argv"][-2:] == [switch, "compiler/" + crate]
        and command["argv"].count(switch) == 1
        and ({"--doc", "--tests"} & set(command["argv"])) == {switch}
        and command["cwd"] == "/tmp/ohm-gnu-renderer-source-native/rust",
        "different process status, target or raw test stream",
    )
    return text.decode()


def tests(b, repo, log, candidate, previous):
    args = ["./x", *b.OPTIONS, "--set", "rust.verbose-tests=true", "test", *b.HOST_FLAGS]
    completed = {}
    docs = {}
    for crate, new in candidate["additional_linux_units"].items():
        required = (previous["unit"] if crate == "rustc_incremental" else []) + new
        need(len(set(required)) == len(required), "duplicate required test")
        for switch, label in (("--tests", crate), ("--doc", crate + "-doc")):
            path = log / (label + ".log")
            b.succeeded([*args, switch, "compiler/" + crate], repo, path)
            command = json.loads((log / (label + ".command.json")).read_bytes())
            text = individual(command, path.read_bytes(), crate, switch)
            if switch == "--tests":
                completed[crate] = unit_record(text, crate, required)
            else:
                docs[crate] = doc_record(text, crate)
    names = previous["run_make"] + candidate["additional_run_make"]
    need(len(names) == len(set(names)), "duplicate native test")
    fixtures = {}
    touched = {r["path"] for r in candidate["delta"]["rows"]}
    for name in names:
        rel = "tests/run-make/" + name
        src = rel + "/rmake.rs"
        fixtures[name] = sha(repo / src)
        need(
            src in touched or previous["original_sources"].get(name) == fixtures[name],
            "run-make recipe differs from admitted source",
        )
        path = log / (name + ".log")
        b.succeeded([*args, rel], repo, path)
        b.verdict(path.read_text(errors="replace"), name, True, 0)
    write(log / "checked-in-tests.json", {"units": completed, "docs": docs, "run_make": names, "fixtures": fixtures})


def anchor_k(b, root, transfer, log):
    o = s.K_ORIGIN
    sdk = root / "operational"
    record = prior.old.restore(transfer, sdk, "K", o["head"], str(o["run"]), "1", o["manifest"])
    alias = root / "rustup/toolchains/ohm"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(sdk, target_is_directory=True)
    env = original.env_for(root)
    need(
        Path(
            subprocess.check_output(
                ["rustup", "which", "--toolchain", "ohm", "rustc"], env=env, text=True
            ).strip()
        ).samefile(sdk / "bin/rustc"),
        "wrong K compiler",
    )
    src = log / "donor.rs"
    src.write_text('pub fn value()->String { String::from("cross-stage1") }\n')
    donor = root / "libqa_donor.rlib"
    b.succeeded(
        ["rustc", "+ohm", src, "--crate-name", "qa_donor", "--crate-type", "rlib", "-o", donor],
        root,
        log / "donor.log",
        env,
    )
    write(log / "original-K.json", {"sdk": record, "donor": sha(donor)})
    held = root / "genuine-K"
    sdk.rename(held)
    for source, destination in [
        ("bin/cargo", root / "cargo/cargo-761"),
        (s.reg.WILD, root / "packages/sdk-21" / s.reg.WILD),
    ]:
        destination.parent.mkdir(parents=True)
        os.link(held / source, destination)


def main(trusted):
    candidate = s.load()
    b = original.toolchain(trusted)
    root, repo = b.ROOT, b.ROOT / "rust"
    env = os.environ
    need(
        platform.system() == "Linux"
        and platform.machine() == "x86_64"
        and root == Path(env["QA_ROOT"])
        and env["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and env["GITHUB_REPOSITORY"] == s.reg.REPO
        and env["GITHUB_REF"] == s.REF
        and env["GITHUB_RUN_ATTEMPT"] == "1"
        and s.reg.rev(s.HERE.parents[1], "HEAD") == env["GITHUB_SHA"]
        and not root.is_symlink()
        and shutil.disk_usage(root).free > 32 * 2**30,
        "wrong E enrollment or disk",
    )
    bound = dict(qa=env["GITHUB_SHA"], run=env["GITHUB_RUN_ID"], attempt="1")
    rec = root / "receipts"
    log = rec / "E"
    log.mkdir()
    transfer, capsule = root / "k-transfer", root / "E-transfer"
    k, previous_tests, previous_command, _ = prior.reopen(root / "k-origin", transfer)
    capsule.mkdir()
    from source import live_base

    live_base(repo, b.HERE / "packet")
    s.reg.source(repo, True, rec)
    s.verify(repo, candidate, install=True)
    commit = candidate["role"]["commit"]
    b.git(repo, "checkout", "--detach", commit)
    b.check_source(repo, commit)
    need(not (repo / "build").exists(), "native output already exists")
    write(log / "source.json", {**candidate, **bound, "launcher": b.launcher(repo), "llvm": b.LLVM})
    anchor_k(b, root, transfer, log)
    b.succeeded(
        [sys.executable, "-IB", s.HERE / "selector.py", repo, root / "genuine-K", log / "selector"],
        root, log / "selector.log",
    )
    args = ["./x", *b.OPTIONS, "build", *b.HOST_FLAGS, *b.SDK_COMPONENTS]
    need(
        args == previous_command["argv"] and str(repo) == previous_command["cwd"], "different bootstrap"
    )
    b.succeeded(args, repo, log / "bootstrap.log")
    stage = repo / "build" / b.HOST / "stage1"
    stage0 = {
        "source": sha(repo / "src/stage0"),
        **{x: sha(stage.parent / "stage0/bin" / x) for x in ("rustc", "cargo")},
    }
    need(stage0 == b.STAGE0 == k["stage0"] and b.LLVM == k["llvm"], "foreign stage0 or LLVM")
    files = original.selected(b, stage, root)
    before = b.manifest(files)
    write(log / "before-tests.json", before)
    changed = restore_e.differences(k, before)
    tests(b, repo, log, candidate, previous_tests)
    remaining = b.manifest({n: p for n, p in files.items() if p.is_file()})
    need(all(before[n] == v for n, v in remaining.items()), "tests changed native objects")
    b.succeeded(args, repo, log / "reassemble.log")
    files = original.selected(b, stage, root)
    need(b.manifest(files) == before, "reassembled E differs")
    b.operational(root, stage, files, "C", log)
    need((log / "rustc.log").read_text() == k["compiler_verbose"], "changed bootstrap compiler version")
    write(
        rec / "lineage-calibration.json",
        original.lineage_calibration.check(rec / "lineage-calibration"),
    )
    sdk = root / "operational"
    sdk.mkdir()
    for rel, file in files.items():
        target = sdk / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(file.resolve(), target)
    original.native(b, root, sdk, log, "E")
    cross_reader.checked(root, log, sdk, files, k, original.env_for(root))
    need(b.manifest(files) == before, "source-built E changed under native checks")
    b.check_source(repo, commit)
    shutil.rmtree(sdk)
    delta = capsule / "E-delta.tar.zst"
    b.archive({Path(n): files[Path(n)] for n in changed}, delta)
    m = {
        **bound,
        "qualified": True,
        "source": candidate,
        "base": s.K_ORIGIN,
        "selector": sha(log / "selector/result.json"),
        "host": b.HOST,
        "driver": k["driver"],
        "llvm": b.LLVM,
        "stage0": stage0,
        "files": before,
        "delta": sorted(changed),
        "products": {delta.name: [sha(delta), delta.stat().st_size]},
        "tests": sha(log / "checked-in-tests.json"),
        "native": sha(log / "native-shadow/complete.json"),
        "cross_readers": sha(log / "cross-readers/complete.json"),
    }
    manifest = capsule / "manifest.json"
    write(manifest, m)
    restored = restore_e.restore(transfer, capsule, sdk, bound["qa"], bound["run"], "1", sha(manifest))
    need(
        subprocess.check_output(["rustc", "+ohm", "-vV"], env=original.env_for(root)).decode()
        == k["compiler_verbose"],
        "restored Rust mismatch",
    )
    need(
        "commit-hash: " + s.reg.CARGO
        in subprocess.check_output(["cargo", "+ohm", "-Vv"], env=original.env_for(root)).decode(),
        "restored Cargo mismatch",
    )
    write(
        rec / "qualified.json",
        {
            **bound,
            **restored,
            "selector": m["selector"],
            "tests": m["tests"],
            "native": m["native"],
            "cross_readers": m["cross_readers"],
            "base": s.K_ORIGIN,
        },
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
