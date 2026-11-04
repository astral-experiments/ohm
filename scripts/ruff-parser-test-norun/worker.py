"""Run the preregistered Ruff parser libtest compile with the original matched SDKs and PMU."""
from pathlib import Path
import os
import shutil
import subprocess as sp
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from records import count, digest, dump, file_hash, load, native_checks, overflow, roster, rows, test_executable

PLAN = load(HERE / "registration.json")
COHORT = os.environ["PARSER_COHORT"]
SLOT = os.environ["PARSER_SLOT"]
ORDER = PLAN["schedule"][COHORT][SLOT]
DONOR = HERE.parent / "ruff-static-array-cost"
for name, sha in PLAN["donor_files"].items():
    assert file_hash(DONOR / name) == sha, name
os.environ["ARRAY_CASE"] = "rand"
os.environ["PRICE_BLOCK"] = "B2" if ORDER == ["P", "C"] else "B1"
sys.path.insert(0, str(DONOR))
import price as b

assert b.order == ORDER and (b.old, b.new) == (PLAN["old"], PLAN["new"])


def preserve(path):
    name = file_hash(path)
    dest = b.proof / "native" / (name + ".zst")
    if not dest.exists():
        dest.parent.mkdir(exist_ok=True)
        with dest.open("xb") as stream:
            sp.run(["zstd", "-q", "-3", "-c", path], stdout=stream, check=True)
        assert file_hash(path) == name
    return name


def run_argv(at, argv, label, stderr):
    with (at / label).open("xb") as out, (at / stderr).open("xb") as err:
        return sp.run(argv, cwd=b.gitroot, env=b.standard(), stdout=out, stderr=err).returncode


def visit(role, phase):
    at = b.proof / role / phase
    at.mkdir(parents=True)
    bad = phase.startswith("invalid")
    traced = phase == "observed-edit"
    oracle_phase = "edit" if traced else phase
    source = b.old if phase == "old" else b.new
    assert b.git("rev-parse", "HEAD") == source
    assert file_hash(b.gitroot / "Cargo.lock") == PLAN["locks"][source]
    if bad:
        assert file_hash(b.gitroot / PLAN["bad_input"]["file"]) == PLAN["bad_input"]["invalid_file"]
    else:
        assert not b.git("status", "--porcelain")
    argv = PLAN["command"]
    command = argv
    if phase in PLAN["priced"] or traced:
        command = [b.work / "whole_count", at / "hardware.json", shutil.which("cargo"), *argv]
    if traced:
        tasks = at / "tasks"
        tasks.mkdir()
        command = [b.work / "exec_count", "--lifetime", b.rustc, "--also", b.wild, tasks, *command]
    literal = b.gitroot / PLAN["bad_input"]["file"]
    dump(at / "invocation.json", {"argv": list(map(os.fspath, command)), "cargo": argv,
         "unicode_source": preserve(literal),
         "source": source, "cwd": str(b.gitroot), "env": b.standard(), "scored_counter": phase in PLAN["priced"]})
    status = run_argv(at, command, "cargo.jsonl", "stderr")
    (at / "status").write_text(str(status) + "\n")
    events = rows(at / "cargo.jsonl")
    assert events[-1] == {"reason": "build-finished", "success": not bad}, (role, phase, status)
    if bad:
        assert status == 101 and overflow(events) == PLAN["bad_input"]["range"]
        return
    assert status == 0, (role, phase, (at / "stderr").read_text()[-1200:])
    observed = roster(events, b.gitroot)
    assert observed == PLAN["rehearsal"][oracle_phase]["artifacts"], (role, phase, observed)
    if phase in PLAN["priced"] or traced:
        count(at / "hardware.json")
    elf = test_executable(events)
    with elf.open("rb") as stream:
        assert stream.read(6) == b"\x7fELF\x02\x01"
    assert run_argv(at, [elf, "--list", "--format", "terse"], "test-inventory.txt", "inventory.stderr") == 0
    assert run_argv(at, [elf, "--exact", PLAN["native_test"]], "one-test.stdout", "one-test.stderr") == 0
    native_checks((at / "test-inventory.txt").read_bytes(), (at / "one-test.stdout").read_bytes(), PLAN)
    build, = [Path(row["out_dir"]) for row in events if row["reason"] == "build-script-executed"
              and "/ruff_unicode_names2#" in row["package_id"]]
    files = {f.name: preserve(f) for f in sorted(build.glob("generated*.rs"))}
    assert files == PLAN["rehearsal"][oracle_phase]["generated"], (role, phase, files)
    report = {"elf": preserve(elf), "elf_bytes": elf.stat().st_size, "generated": files, "roster": observed}
    if traced:
        physical = b.lifetimes(tasks)
        selected = physical["actual"]
        parser, = [item for item in selected if item["crate"] == "ruff_python_parser" and item["tool"] == "rustc"]
        assert "--test" in parser["argv"] and "-Zlink-only" not in parser["argv"]
        assert any(item["tool"] == "Wild" for item in selected)
        dump(at / "physical.json", physical)
    dump(at / "native.json", report)
    return report["elf"]


def new_history():
    assert all(not p.exists() for p in (b.home, b.target, b.shared))
    shutil.copytree(b.work / "enrolled-cargo-home", b.home)


def trial(role):
    new_history()
    b.switch(b.old)
    old_elf = visit(role, "old")
    donor = b.stash(role + "-parser-old-copy", copy=True)
    b.switch(b.new)
    new_elf = visit(role, "edit")
    assert old_elf != new_elf and visit(role, "unchanged") == new_elf
    path = b.gitroot / PLAN["bad_input"]["file"]
    good = path.read_bytes()
    assert digest(good) == PLAN["bad_input"]["new_file"]
    try:
        path.write_bytes(good + PLAN["bad_input"]["suffix"].encode())
        visit(role, "invalid")
        visit(role, "invalid-again")
    finally:
        path.write_bytes(good)
    assert visit(role, "repaired") == new_elf
    b.stash(role + "-parser-repaired")
    new_history()
    assert visit(role, "empty") == new_elf
    b.stash(role + "-parser-empty")
    for path in (b.home, b.target, b.shared):
        (donor / path.name).rename(path)
    assert visit(role, "observed-edit") == new_elf
    b.stash(role + "-parser-observed")


def main():
    if COHORT == "confirmation":
        pilot = load(HERE / "evidence" / "pilot" / "qualified.json")
        assert pilot["cohort"] == "pilot" and pilot["qualified"] and len(pilot["blocks"]) == 2
        assert pilot["registration"] == file_hash(HERE / "registration.json")
        assert b.boot not in {r["boot"] for r in pilot["blocks"]}
    for rev, tree in PLAN["ruff_trees"].items():
        assert b.git("rev-parse", rev + "^{tree}") == tree
    cases = b.enroll()
    binding = {"cohort": COHORT, "slot": SLOT, "order": ORDER, "boot": b.boot,
               "run": os.environ["GITHUB_RUN_ID"], "attempt": os.environ["GITHUB_RUN_ATTEMPT"],
               "qa": os.environ["GITHUB_SHA"], "registration": file_hash(HERE / "registration.json"),
               "worker": file_hash(__file__), "reader": file_hash(HERE / "review.py"),
               "records": file_hash(HERE / "records.py"), "source_root": str(b.gitroot)}
    dump(b.proof / "binding.json", binding)
    for i, role in enumerate(ORDER):
        b.transport.install(*cases[role], b.sdk, b.alias)
        versions = {}
        for name in ("rustc", "cargo"):
            versions[name] = sp.check_output([name, "+ohm", "-vV" if name == "rustc" else "-Vv"],
                                            env=b.standard(), cwd=b.gitroot, text=True)
        assert PLAN["parent" if role == "P" else "candidate"] in versions["rustc"]
        assert PLAN["cargo"] in versions["cargo"]
        def identity(path):
            st = path.stat()
            return {"path": str(path), "device": st.st_dev, "inode": st.st_ino, "sha256": file_hash(path)}
        driver, = (b.sdk / "lib").glob("librustc_driver-*.so")
        dump(b.proof / ("installed-" + role + ".json"), {"versions": versions, "driver": identity(driver),
             "rustc": identity(b.rustc), "cargo": identity(b.sdk / "bin/cargo"), "Wild": identity(b.wild)})
        if i == 0:
            b.seed()
        trial(role)
        b.alias.unlink()
        b.sdk.rename(b.work / ("installed-sdk-" + role))
    dump(b.proof / "completed.json", binding)


if __name__ == "__main__":
    main()
