"""Run both source compilers on one independently booted host at identical visible paths."""
from pathlib import Path
import os
import shutil
import subprocess as sp
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from records import calibrate_lifetime, dump, file_hash, from_counter, load, overflow, physical, roster, rows
import registry

PLAN = load(HERE / "registration.json")
LOCKED = load(HERE / "locked.json")
DONOR = HERE.parent / "ruff-static-array-cost"
for item, declared in PLAN["common_sources"].items():
    assert file_hash(DONOR / item) == declared
sys.path.insert(0, str(DONOR))
import transport
from factory import acquire

WORK = Path(os.environ["RUNNER_TEMP"]) / "width-parser"
PROOF = WORK / "proof"
SOURCE = Path(os.environ["GITHUB_WORKSPACE"]) / "ruff"
SDK, HOME, TARGET, SHARED = [WORK / p for p in ("sdk", "cargo-home", "target", "shared")]
ALIAS = WORK / "rustup/toolchains/ohm"
STATE = (HOME, TARGET, SHARED)
COHORT, SLOT = os.environ["WIDTH_COHORT"], os.environ["WIDTH_SLOT"]
ORDER = PLAN["schedule"][COHORT][SLOT]
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def git(*args):
    return sp.check_output(["git", *args], cwd=SOURCE, text=True).strip()

def head_record():
    path = Path(git("rev-parse", "--absolute-git-dir")) / "HEAD"
    stat = path.stat()
    return {"contents": path.read_text(), "inode": stat.st_ino, "mtime_ns": stat.st_mtime_ns}

def source_state(rev, invalid=False):
    paths = git("diff", "--name-only", "HEAD", "--").splitlines()
    expected = ["Cargo.lock"] if rev == PLAN["new"] else []
    if invalid:
        expected.append(PLAN["invalid"]["path"])
    assert paths == sorted(expected) and not git("ls-files", "--others", "--exclude-standard")
    assert git("rev-parse", "HEAD") == PLAN["old"]
    assert head_record() == load(PROOF / "fixed-head.json")
    assert file_hash(SOURCE / "Cargo.lock") == LOCKED["locks"][rev]
    return {"git_head": head_record(), "changed_paths": paths, "lock_sha256": LOCKED["locks"][rev]}

def switch(commit):
    assert commit in PLAN["trees"]
    assert git("rev-parse", "HEAD") == PLAN["old"]
    assert git("diff", "--name-only", "HEAD", "--").splitlines() in ([], ["Cargo.lock"])
    lock = SOURCE / "Cargo.lock"
    if file_hash(lock) != LOCKED["locks"][commit]:
        lock.write_bytes(sp.check_output(["git", "show", commit + ":Cargo.lock"], cwd=SOURCE))
    source_state(commit)

def environment():
    env = {k:os.environ[k] for k in ("HOME", "USER", "PATH", "LANG", "TZ", "TMPDIR") if k in os.environ}
    env.update(RUSTUP_HOME=str(ALIAS.parent.parent), CARGO_HOME=str(HOME), CARGO_TARGET_DIR=str(TARGET),
               CARGO_BUILD_BUILD_DIR=str(SHARED), CARGO_BUILD_JOBS="2", CARGO_NET_OFFLINE="true")
    return env

def preserve(path):
    sha = file_hash(path)
    dst = PROOF / "objects" / (sha + ".zst")
    dst.parent.mkdir(exist_ok=True)
    if not dst.exists():
        with dst.open("xb") as f:
            sp.run(["zstd", "-q", "-3", "-c", path], stdout=f, check=True)
        assert file_hash(path) == sha
    return {"sha256":sha, "bytes":path.stat().st_size}

def analyze_outputs(events, mode):
    bodies, sources = {}, {}
    for name in ("unicode_width", "ruff_formatter"):
        row, = [e for e in events if e["reason"] == "compiler-artifact" and e["target"]["name"] == name]
        assert row["target"]["kind"] == ["lib"] and not row["profile"]["test"]
        files = {Path(f).suffix:Path(f) for f in row["filenames"]}
        assert set(files) == ({".rmeta"} if mode == "check" else {".rmeta", ".rlib"})
        bodies[name] = {k:dict(preserve(p), path=str(p)) for k, p in files.items()}
        sources[name] = files
    return bodies, sources

def observer(at, events, sources, rev):
    exe = WORK / "observer"
    args = ["rustc", "+ohm", "--edition=2024", "-O", str(WORK / "observer.rs"), "-o", str(exe)]
    for name in ("unicode_width", "ruff_formatter"):
        for ext in (".rlib", ".rmeta"):
            args += ["--extern", name + "=" + str(sources[name][ext])]
    deps = {str(Path(f).parent) for e in events if e["reason"] == "compiler-artifact"
            for f in e["filenames"] if f.endswith((".rlib",".rmeta",".so"))}
    for directory in sorted(deps):
        args += ["-L", "dependency=" + directory]
    dump(at / "native-argv.json", args)
    with (at / "native-compile.stderr").open("xb") as err:
        sp.run(args, cwd=SOURCE, env=environment(), stderr=err, check=True)
    with (at / "widths-and-wraps.bin").open("xb") as out:
        sp.run([exe], cwd=SOURCE, env=environment(), stdout=out, check=True)
    expected = PLAN["oracle"]["old" if rev == PLAN["old"] else "new"]
    assert file_hash(at / "widths-and-wraps.bin") == expected
    return {"elf":preserve(exe), "output":expected}

def state_hash(role, mode, phase, version):
    git_sources = registry.git_roots(HOME, LOCKED["git"])
    dump(PROOF / role / mode / phase / "git-sources.json", git_sources)
    report = registry.materialized(HOME, LOCKED["archives"], required=["unicode-width-"+version])
    snap = WORK / "registry-audit.json"
    dump(snap, report)
    ref = file_hash(snap)
    store = PROOF / "registry" / (ref + ".json")
    store.parent.mkdir(exist_ok=True)
    if not store.exists():
        shutil.copyfile(snap, store)
    dump(PROOF / role / mode / phase / "registry.json", {"sha256":ref,"packages":len(report)})
    return ref

def retained(at):
    seen = set()
    files = {}
    unique_bytes = 0
    for base in (TARGET, SHARED):
        for path in sorted(base.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
            identity = (stat.st_dev, stat.st_ino)
            relative = str(path.relative_to(WORK))
            files[relative] = [stat.st_size, stat.st_blocks, stat.st_dev, stat.st_ino]
            if identity not in seen:
                seen.add(identity)
                unique_bytes += stat.st_blocks * 512
    assert files and unique_bytes > 0
    dump(at / "retained-files.json", files)
    return {"bytes":unique_bytes, "paths":len(files), "inodes":len(seen)}

def visit(role, mode, phase, installed):
    old = phase in ("cold-old", "old-unchanged")
    rev = PLAN["old"] if old else PLAN["new"]
    source = source_state(rev, phase.startswith("invalid"))
    at = PROOF / role / mode / phase
    at.mkdir(parents=True)
    traced = phase.startswith("observed-")
    invalid = phase.startswith("invalid")
    args = ["cargo", "+ohm", mode, "-p", "ruff_formatter", "--lib", "--locked", "--offline", "--message-format=json"]
    argv = [WORK / "whole_count", at / "hardware.json", shutil.which("cargo"), *args]
    if traced:
        tasks = at / "tasks"
        tasks.mkdir()
        argv = [WORK / "exec_count", "--lifetime", installed["rustc"]["path"], "--also", installed["Wild"]["path"], tasks, *argv]
    if invalid:
        argv = args
    start = time.monotonic_ns()
    with (at / "cargo.jsonl").open("xb") as out, (at / "stderr").open("xb") as err:
        run = sp.run(argv, cwd=SOURCE, env=environment(), stdout=out, stderr=err)
    elapsed = time.monotonic_ns() - start
    dump(at / "entry.json", {"argv":args, "environment":{k:v for k,v in environment().items() if k.startswith(("CARGO","RUST"))},
         "source":rev, **source, "status":run.returncode, "wall_ns":elapsed})
    events = rows(at / "cargo.jsonl")
    assert events[-1] == {"reason":"build-finished", "success":not invalid}, (at, (at / "stderr").read_text()[-1200:])
    assert run.returncode == (101 if invalid else 0)
    version = "0.2.1" if rev == PLAN["old"] else "0.2.2"
    if invalid:
        result = {"error":overflow(events, PLAN["invalid"])}
    else:
        assert not any(e["reason"] == "compiler-message" and e["message"]["level"] == "error" for e in events)
        typed = roster(events, SOURCE)
        expected = PLAN["rosters"][mode]["old" if old else "edit"]
        assert typed["total"] == expected["total"] and typed["all_sha256"] == expected["all_sha256"], (phase,typed)
        if phase in ("cold-old","empty-new","observed-empty-new"):
            assert typed["dirty"] == typed["total"]
        elif phase in ("ordinary-edit","observed-edit"):
            assert typed == expected
        elif phase in ("old-unchanged", "unchanged"):
            assert typed["dirty"] == 0
        elif phase == "repaired":
            assert typed["dirty_names"] == ["ruff_formatter"]
        bodies, sources = analyze_outputs(events, mode)
        result = {"roster":typed, "products":bodies, "whole":from_counter(load(at / "hardware.json"))}
        if traced:
            detail = physical(lambda name:(tasks / name).read_bytes(), installed, version, phase == "observed-edit")
            result["owner"] = detail["owner"]
            dump(at / "physical.json", detail)
        if phase in ("ordinary-edit", "empty-new"):
            result["retained"] = retained(at)
        if mode == "build":
            result["native"] = observer(at, events, sources, rev)
    result["registry"] = state_hash(role,mode,phase,version)
    assert source_state(rev, invalid) == source
    dump(at / "result.json", result)
    print(role, mode, phase, result.get("whole"), result.get("owner"), flush=True)
    return result

def discard_live():
    for p in STATE:
        assert p.parent == WORK and p.name in ("cargo-home","target","shared") and not p.is_symlink()
        if p.exists():
            shutil.rmtree(p)

def empty():
    discard_live()
    (HOME / "registry").mkdir(parents=True)
    shutil.copytree(WORK / "inputs/git-db", HOME / "git/db")
    for n in ("cache", "index"):
        shutil.copytree(WORK / "inputs" / n, HOME / "registry" / n, symlinks=True)

def trial(role, mode, installed):
    history = {}
    def phase(name):
        history[name] = visit(role, mode, name, installed)
    empty()
    switch(PLAN["old"])
    phase("cold-old")
    phase("old-unchanged")
    snapshot = WORK / ("old-" + role)
    if mode == "check":
        snapshot.mkdir()
        for p in STATE:
            if p.exists():
                shutil.copytree(p, snapshot / p.name, symlinks=True)
    switch(PLAN["new"])
    phase("ordinary-edit")
    phase("unchanged")
    rust = SOURCE / PLAN["invalid"]["path"]
    clean = rust.read_bytes()
    assert file_hash(rust) == PLAN["invalid"]["clean"]
    try:
        rust.write_bytes(clean + (HERE / "private-invalid.rs").read_bytes())
        phase("invalid")
        phase("invalid-again")
    finally:
        rust.write_bytes(clean)
    source_state(PLAN["new"])
    phase("repaired")
    if mode == "check":
        discard_live()
        for p in STATE:
            old = snapshot / p.name
            if old.exists():
                old.rename(p)
        phase("observed-edit")
    empty()
    phase("empty-new")
    if mode == "check":
        empty()
        phase("observed-empty-new")
    discard_live()
    check_history(history, mode)
    dump(PROOF / role / mode / "terminal.json", {"phases": list(history)})

def products(row, name):
    return {ext: f["sha256"] for ext, f in row["products"][name].items()}

def check_history(h, mode):
    assert list(h) == PLAN["phase_plan"][mode]
    assert h["invalid"]["error"] == h["invalid-again"]["error"]
    edit = h["ordinary-edit"]
    for phase, row in h.items():
        if phase in ("cold-old", "old-unchanged") or phase.startswith("invalid"):
            continue
        assert products(row, "unicode_width") == products(edit, "unicode_width"), (mode, phase)
        if phase in ("unchanged","observed-edit"):
            assert products(row, "ruff_formatter") == products(edit, "ruff_formatter"), (mode, phase)
        if mode == "build":
            assert row["native"] == edit["native"]
    if mode == "build":
        assert h["cold-old"]["native"]["elf"] != edit["native"]["elf"]


def runtime_inventory():
    members = {}
    for directory, children, files in os.walk(SDK):
        base = Path(directory)
        if base == SDK / "lib/rustlib":
            children[:] = [c for c in children if c not in ("src", "rustc-src")]
        for name in files:
            path = base / name
            assert path.is_file() and not path.is_symlink()
            stat = path.stat()
            members[str(path.relative_to(SDK))] = {"sha256":file_hash(path), "bytes":stat.st_size, "mode":stat.st_mode & 0o777}
    return members

def main():
    assert not WORK.exists()
    PROOF.mkdir(parents=True)
    assert git("rev-parse", "HEAD") == PLAN["new"] and not git("status", "--porcelain")
    sp.run(["git", "switch", "--detach", PLAN["old"]], cwd=SOURCE, check=True)
    dump(PROOF / "fixed-head.json", head_record())
    assert head_record()["contents"] == PLAN["old"] + "\n"
    assert {PLAN["old"], PLAN["new"]} == set(PLAN["trees"])
    assert git("rev-parse", PLAN["new"] + "^") == PLAN["old"]
    for rev, tree in PLAN["trees"].items():
        assert git("rev-parse", rev + "^{tree}") == tree
    assert git("diff","--name-only",PLAN["old"],PLAN["new"]).splitlines() == PLAN["source_change"]
    for fname, expected in (("PROTOCOL.md", PLAN["protocol_sha"]), ("locked.json", PLAN["locked_sha"]), ("observer.rs", PLAN["oracle"]["source"]), ("private-invalid.rs", PLAN["invalid"]["suffix"])):
        assert file_hash(HERE / fname) == expected
    shutil.copyfile(HERE / "observer.rs", WORK / "observer.rs")
    binding = {"boot":BOOT,"order":ORDER,"cohort":COHORT,"slot":SLOT,"head":os.environ["GITHUB_SHA"],
               "run":os.environ["GITHUB_RUN_ID"],"attempt":os.environ["GITHUB_RUN_ATTEMPT"],"source":str(SOURCE),
               "scripts":{p.name:file_hash(p) for p in HERE.iterdir() if p.suffix in (".py",".rs",".json")},
               "cpu":Path("/proc/cpuinfo").read_text().split("\n\n")[0], "affinity":sorted(os.sched_getaffinity(0))}
    dump(PROOF / "binding.json", binding)
    if COHORT == "confirmation":
        pilot = load(HERE / "evidence/pilot/qualified.json")
        assert pilot["qualified"] and pilot["cohort"] == "pilot" and pilot["plan"] == file_hash(HERE / "registration.json")
        assert BOOT not in {b["boot"] for b in pilot["blocks"]}
    for name in ("whole_count","exec_count","calibrate"):
        sp.run(["cc","-O2","-pthread","-Wall","-Wextra","-Werror",DONOR/(name+".c"),"-o",WORK/name], check=True)
    readings = {}
    for action in ("single","fork"):
        log = PROOF / ("calibrate-" + action + ".json")
        sp.run([WORK / "whole_count", log, WORK / "calibrate", WORK / "calibrate", action], check=True)
        readings[action] = from_counter(load(log))
    assert 1.99 < readings["fork"] / readings["single"] < 2.01
    path = WORK / "calibrate"
    ident = [path.stat().st_dev, path.stat().st_ino]
    dump(PROOF / "calibration-image.json", {"ident":ident, "sha256":file_hash(path)})
    lifetime = {}
    for action in ("single","fork"):
        tasks = PROOF / ("lifetime-"+action)
        tasks.mkdir()
        sp.run([WORK/"exec_count","--lifetime",path,tasks,WORK/"whole_count",PROOF/("lifetime-whole-"+action+".json"),path,path,action], check=True)
        lifetime[action] = calibrate_lifetime(lambda p:(tasks/p).read_bytes(),ident,action)
    assert 0.99 < lifetime["fork"] / lifetime["single"] < 1.01
    assert file_hash(HERE / "sdk-files.json") == PLAN["sdk_files_sha"]
    assert file_hash(HERE / "software-admission.json") == PLAN["software_admission_sha"]
    cases = {role:acquire(PLAN["roles"][role],PLAN,WORK / "archives",PROOF / ("sdk-"+role)) for role in ORDER}
    assert (PROOF/"sdk-C7/bootstrap.json").read_bytes() == (PROOF/"sdk-C8/bootstrap.json").read_bytes()
    os.environ.pop("GH_TOKEN",None)
    for idx, role in enumerate(ORDER):
        tar, proof = cases[role]
        transport.install(tar, proof, SDK, ALIAS)
        inventory = runtime_inventory()
        assert inventory == load(HERE / "sdk-files.json")[role]
        dump(PROOF / ("sdk-runtime-"+role+".json"), inventory)
        def ident(path):
            stat = path.stat()
            return {"path":str(path), "device":stat.st_dev,"inode":stat.st_ino,"sha256":file_hash(path)}
        driver, = (SDK/"lib").glob("librustc_driver-*.so")
        installed = {"driver":ident(driver),"rustc":ident(SDK/"bin/rustc"),"cargo":ident(SDK/"bin/cargo"),
                     "Wild":ident(SDK/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd")}
        for n, opt in (("rustc","-vV"),("cargo","-Vv")):
            actual = sp.check_output([n,"+ohm",opt],cwd=SOURCE,env=environment(),text=True)
            assert actual == proof["versions"][n]
        dump(PROOF/("installed-"+role+".json"),installed)
        if idx == 0:
            registry.seed(SOURCE, HOME, LOCKED, environment(), switch)
            (WORK / "inputs").mkdir()
            (HOME / "git/db").rename(WORK / "inputs/git-db")
            for n in ("cache","index"):
                (HOME / "registry" / n).rename(WORK / "inputs" / n)
            dump(PROOF / "locked-archives.json", {p.name:file_hash(p) for p in (WORK/"inputs/cache").glob("*/*.crate")})
        for mode in ("check","build"):
            trial(role,mode,installed)
        ALIAS.unlink()
        SDK.rename(WORK / ("installed-sdk-"+role))
    assert head_record() == load(PROOF / "fixed-head.json")
    dump(PROOF/"complete.json",binding)

if __name__ == "__main__":
    main()
