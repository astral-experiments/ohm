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

WORK = Path(os.environ["RUNNER_TEMP"]) / "normalization-price"
PROOF = WORK / "proof"
SOURCE = Path(os.environ["GITHUB_WORKSPACE"]) / "ruff"
SDK, HOME, TARGET, SHARED = [WORK / p for p in ("sdk", "cargo-home", "target", "shared")]
ALIAS = WORK / "rustup/toolchains/ohm"
STATE = (HOME, TARGET, SHARED)
COHORT, SLOT = os.environ["NORM_COHORT"], os.environ["NORM_SLOT"]
ORDER = PLAN["schedule"][COHORT][SLOT]
BOOT = Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def git(*args):
    return sp.check_output(["git", *args], cwd=SOURCE, text=True).strip()

def switch(commit):
    assert not git("status", "--porcelain", "--untracked-files=all")
    if git("rev-parse", "HEAD") != commit:
        sp.run(["git", "switch", "--detach", commit], cwd=SOURCE, check=True)
    assert git("rev-parse", "HEAD") == commit and file_hash(SOURCE / "Cargo.lock") == LOCKED["locks"][commit]

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
    for name in ("unicode_normalization", "ruff_python_parser"):
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
    for name in ("unicode_normalization", "ruff_python_parser"):
        for ext in (".rlib", ".rmeta"):
            args += ["--extern", name + "=" + str(sources[name][ext])]
    deps = {str(Path(f).parent) for e in events if e["reason"] == "compiler-artifact"
            for f in e["filenames"] if f.endswith((".rlib",".rmeta",".so"))}
    for directory in sorted(deps):
        args += ["-L", "dependency=" + directory]
    dump(at / "native-argv.json", args)
    with (at / "native-compile.stderr").open("xb") as err:
        sp.run(args, cwd=SOURCE, env=environment(), stderr=err, check=True)
    with (at / "normalizations").open("xb") as out:
        sp.run([exe], cwd=SOURCE, env=environment(), stdout=out, check=True)
    expected = PLAN["oracle"]["old" if rev == PLAN["old"] else "new"]
    assert file_hash(at / "normalizations") == expected
    return {"elf":preserve(exe), "output":expected}

def state_hash(role, mode, phase, version):
    report = registry.materialized(HOME, LOCKED["archives"], required=["unicode-normalization-"+version])
    snap = WORK / "registry-audit.json"
    dump(snap, report)
    ref = file_hash(snap)
    store = PROOF / "registry" / (ref + ".json")
    store.parent.mkdir(exist_ok=True)
    if not store.exists():
        shutil.copyfile(snap, store)
    dump(PROOF / role / mode / phase / "registry.json", {"sha256":ref,"packages":len(report)})
    return ref

def visit(role, mode, phase, installed):
    rev = PLAN["old"] if phase == "cold-old" else PLAN["new"]
    assert git("rev-parse", "HEAD") == rev and file_hash(SOURCE / "Cargo.lock") == LOCKED["locks"][rev]
    at = PROOF / role / mode / phase
    at.mkdir(parents=True)
    traced = phase.startswith("observed-")
    invalid = phase.startswith("invalid")
    args = ["cargo", "+ohm", mode, "-p", "ruff_python_parser", "--lib", "--locked", "--offline", "--message-format=json"]
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
         "source":rev, "status":run.returncode, "wall_ns":elapsed})
    events = rows(at / "cargo.jsonl")
    assert events[-1] == {"reason":"build-finished", "success":not invalid}, (at, (at / "stderr").read_text()[-1200:])
    assert run.returncode == (101 if invalid else 0)
    version = "0.1.24" if rev == PLAN["old"] else "0.1.25"
    if invalid:
        result = {"error":overflow(events, PLAN["invalid"])}
    else:
        assert not any(e["reason"] == "compiler-message" and e["message"]["level"] == "error" for e in events)
        typed = roster(events, SOURCE)
        expected = PLAN["rosters"][mode]["old" if phase == "cold-old" else "edit"]
        assert typed["total"] == 96 and typed["all_sha256"] == expected["all_sha256"], (phase,typed)
        if phase in ("cold-old","empty-new","observed-empty-new"):
            assert typed["dirty"] == typed["total"]
        elif phase in ("ordinary-edit","observed-edit"):
            assert typed == expected
        elif phase == "unchanged":
            assert typed["dirty"] == 0
        elif phase == "repaired":
            assert typed["dirty_names"] == ["ruff_python_parser"]
        bodies, sources = analyze_outputs(events, mode)
        result = {"roster":typed, "products":bodies, "whole":from_counter(load(at / "hardware.json"))}
        if traced:
            detail = physical(lambda name:(tasks / name).read_bytes(), installed, version, phase == "observed-edit")
            result["owner"] = detail["owner"]
            dump(at / "physical.json", detail)
        if mode == "build":
            result["native"] = observer(at, events, sources, rev)
    result["registry"] = state_hash(role,mode,phase,version)
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
    for n in ("cache", "index"):
        shutil.copytree(WORK / "inputs" / n, HOME / "registry" / n, symlinks=True)

def trial(role, mode, installed):
    history = {}
    def phase(name):
        history[name] = visit(role, mode, name, installed)
    empty()
    switch(PLAN["old"])
    phase("cold-old")
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
    assert not git("status","--porcelain")
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
        if phase == "cold-old" or phase.startswith("invalid"):
            continue
        assert products(row, "unicode_normalization") == products(edit, "unicode_normalization"), (mode, phase)
        if phase in ("unchanged","observed-edit"):
            assert products(row, "ruff_python_parser") == products(edit, "ruff_python_parser"), (mode, phase)
        if mode == "build":
            assert row["native"] == edit["native"]
    if mode == "build":
        assert h["cold-old"]["native"]["elf"] != edit["native"]["elf"]

def main():
    assert not WORK.exists()
    PROOF.mkdir(parents=True)
    assert {PLAN["old"], PLAN["new"]} == set(PLAN["trees"])
    assert git("rev-parse", PLAN["new"] + "^") == PLAN["old"]
    for rev, tree in PLAN["trees"].items():
        assert git("rev-parse", rev + "^{tree}") == tree
    assert git("diff","--name-only",PLAN["old"],PLAN["new"]).splitlines() == PLAN["source_change"]
    for fname, expected in (("locked.json", PLAN["locked_sha"]), ("observer.rs", PLAN["oracle"]["source"]), ("private-invalid.rs", PLAN["invalid"]["suffix"])):
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
    cases = {role:acquire(PLAN["roles"][role],PLAN,WORK / "archives",PROOF / ("sdk-"+role)) for role in ORDER}
    assert (PROOF/"sdk-C5/bootstrap.json").read_bytes() == (PROOF/"sdk-C7/bootstrap.json").read_bytes()
    os.environ.pop("GH_TOKEN",None)
    for idx, role in enumerate(ORDER):
        tar, proof = cases[role]
        transport.install(tar, proof, SDK, ALIAS)
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
            for n in ("cache","index"):
                (HOME / "registry" / n).rename(WORK / "inputs" / n)
            dump(PROOF / "locked-archives.json", {p.name:file_hash(p) for p in (WORK/"inputs/cache").glob("*/*.crate")})
        for mode in ("check","build"):
            trial(role,mode,installed)
        ALIAS.unlink()
        SDK.rename(WORK / ("installed-sdk-"+role))
    dump(PROOF/"complete.json",binding)

if __name__ == "__main__":
    main()
