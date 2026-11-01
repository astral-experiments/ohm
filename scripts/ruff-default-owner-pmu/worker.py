"""Run one signed GNU baseline, two plain bounds, and one separately attributed first-A."""

from functools import partial
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as c
import acquire
import instrument
import ownership

HIST = HERE.parent / "ohm-packed-ruff"
sys.path[:0] = [str(HERE.parent / "branch-return-pmu"), str(HIST / "full-cli"), str(HIST), str(HIST / "harness")]
import bindings as b
import study as ruff
import native
import disk
import failed_session

ROOT, OUT, WORK, REPO = b.ROOT, b.OUT, b.WORK, ruff.TREE
BODIES = ROOT / "reference-bodies"
ENV = b.environment("signed22", permitted=("signed22",))


def inputs():
    c.need(
        ruff.REVS == c.EXPECTED and b.SDK == ROOT / "home/.rustup/toolchains/ohm",
        "unexpected registered paths or sources",
    )
    c.need(
        not any(
            k in ENV
            for k in (
                "RUSTFLAGS",
                "CARGO_ENCODED_RUSTFLAGS",
                "RUSTC_WRAPPER",
                "RUSTC_WORKSPACE_WRAPPER",
                "LD_PRELOAD",
            )
        )
        and not any("TRUST" in k or "BRANCH_CACHE" in k for k in ENV),
        "intervening compiler option",
    )
    c.need(acquire.verify_sdk(b.SDK) == c.read(OUT / "sdk.json"), "signed native SDK changed")
    versions = {}
    for name, commit in (("cargo", c.SDK["cargo"]), ("rustc", c.SDK["rust"]), ("rustdoc", c.SDK["rust"])):
        path = subprocess.check_output(
            [b.PROXIES / "rustup", "which", "--toolchain", "ohm", name], env=ENV, text=True
        ).strip()
        version = subprocess.check_output([name, "+ohm", "-vV"], env=ENV, text=True)
        c.need(
            Path(path).samefile(b.SDK / "bin" / name) and commit in version and "ohm-1.99.0-22" in version,
            "normal versioned alias",
        )
        versions[name] = version
    ldd = subprocess.check_output(["ldd", b.SDK / "bin/rustc"], env=ENV, text=True)
    drivers = [
        line.split(" => ")[1].split()[0]
        for line in ldd.splitlines()
        if "librustc_driver" in line and " => " in line
    ]
    (expected,) = [name for name in c.SDK["members"] if name.startswith("lib/librustc_driver")]
    c.need(len(drivers) == 1 and Path(drivers[0]).samefile(b.SDK / expected), "unregistered rustc driver load")
    c.save(
        OUT / "execution-environment.json",
        {"env": ENV, "versions": versions, "ldd": ldd, "driver": expected, "cpus": sorted(os.sched_getaffinity(0))},
    )
    b.prepare_inputs(ruff, ENV)


def source(branch, status):
    expected = c.EXPECTED[branch]
    c.need(
        c.git(REPO, "rev-parse", "HEAD").decode().strip() == expected
        and c.git(REPO, "rev-parse", "HEAD^{tree}").decode().strip() == ruff.TREES[branch]
        and c.git(REPO, "symbolic-ref", "--short", "HEAD").decode().strip() == ruff.NAMES[branch],
        "wrong live Git revision",
    )
    tracked = c.git(REPO, "status", "--porcelain=v1")
    c.need(
        tracked == (b" M " + c.PARSER.encode() + b"\n" if status == "invalid" else b""), "unexpected worktree edit"
    )
    actual = (REPO / c.PARSER).read_bytes()
    original = c.git(REPO, "show", expected + ":" + c.PARSER)
    c.need(actual == original + (c.INVALID if status == "invalid" else b""), "wrong exact error edit")
    watched = {}
    for key in (".git/HEAD", ".git/refs/heads/" + ruff.NAMES[branch]):
        path = REPO / key
        st = path.lstat()
        c.need(path.is_file() and not path.is_symlink(), "watched source input")
        watched[key] = [c.sha(path), st.st_ino, st.st_mtime_ns, st.st_ctime_ns]
    return {
        "branch": branch,
        "rev": expected,
        "tree": ruff.TREES[branch],
        "invalid": status == "invalid",
        "parser": hashlib.sha256(actual).hexdigest(),
        "watched": watched,
    }


def switch(revision):
    c.need(not c.git(REPO, "status", "--porcelain"), "unexpected edit before switch")
    if c.git(REPO, "symbolic-ref", "--short", "HEAD").decode().strip() != ruff.NAMES[revision]:
        c.git(REPO, "switch", "--quiet", ruff.NAMES[revision])


def invoke(where, cmd, want):
    proc = subprocess.run([str(v) for v in cmd], cwd=REPO, env=ENV, capture_output=True, timeout=1200)
    for k, data in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        (where / ("cargo." + k + ".gz")).write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
    c.save(
        where / "invocation.json",
        {"argv": list(map(str, cmd)), "cargo": c.CMD, "cwd": str(REPO), "expected": want, "exit": proc.returncode},
    )
    c.need(proc.returncode == want, ("Cargo exit", proc.returncode, proc.stderr[-550:]))
    return [json.loads(line) for line in proc.stdout.splitlines()]


def run_visit(lane, phase, refs, tools, topo):
    branch = "B" if phase == "B" else "A"
    if phase in ("A", "B"):
        switch(branch)
    if phase == "invalid":
        p = REPO / c.PARSER
        c.need(not c.git(REPO, "status", "--porcelain"), "clean before parser fault")
        p.write_bytes(p.read_bytes() + c.INVALID)
    elif phase == "repair":
        c.need(
            (REPO / c.PARSER).read_bytes() == c.git(REPO, "show", "HEAD:" + c.PARSER) + c.INVALID,
            "lost genuine parser fault",
        )
        c.git(REPO, "restore", "--worktree", "--", c.PARSER)
    where = OUT / lane / phase
    where.mkdir()
    if phase == "B" or lane == "reference" or (lane == "empty-invalid" and phase == "invalid"):
        roots = {}
        for name in ("target", "build"):
            path = WORK / name
            st = path.stat()
            c.need(
                path.is_dir() and path.resolve(strict=True) == path and not any(path.iterdir()),
                "nonempty enrolled root",
            )
            roots[str(path)] = [st.st_dev, st.st_ino, []]
        c.save(where / "empty-roots.json", roots)
    before = source(branch, phase)
    c.save(where / "source-before.json", before)
    if phase == "repair":
        failed_session.before_repair(WORK, c.read(where.parent / "invalid/failed.json"), where / "grace.json")
    if phase == "unchanged":
        c.need(c.read(where.parent / "A/source-after.json") == before, "unchanged Git event")
    bad = phase == "invalid"
    mode = "ordinary"
    command = list(c.CMD)
    if phase == "A" and lane.startswith("plain-"):
        mode = "plain"
        command = [tools / "plain", where / "clock.json", *command]
    elif phase == "A" and lane == "attributed":
        mode = "tree"
        trace = where / "trace"
        trace.mkdir()
        selectors = c.read(OUT / "selectors.json")
        command = [tools / "tree", trace, mode, *[selectors[n][2] for n in topo.ROLES], *command]
    rows = invoke(where, command, 101 if bad else 0)
    c.need(before == source(branch, phase), "source changed during compile")
    c.save(where / "source-after.json", before)
    diag = ownership.typed(rows, bad)
    c.save(where / "diagnostic.json", diag)
    abandoned = failed_session.observed(WORK)
    c.need(bad or not abandoned, "unexplained working session")
    if bad:
        c.save(where / "failed.json", abandoned)
    disk.allocated(WORK / "target", WORK / "build", where, failed_sessions=abandoned)
    ownership.check_roots(rows, WORK)
    summary = {"phase": phase, "branch": branch, "mode": mode, "source": before["rev"], "diagnostic": diag}
    if bad:
        c.save(where / "visit.json", summary)
        return
    graph, products = ownership.graph(rows)
    if lane == "reference" or phase == "B":
        c.need(all(not r["fresh"] for r in products), "nominal empty build reused an artifact")
    c.save(where / "roster.json.gz", graph)
    desc, files = native.observed(rows, branch, c.EXPECTED[branch], ENV, ROOT, REPO, WORK, where)
    if lane == "reference":
        refs[branch] = (graph, desc)
        for key, path in files.items():
            native.preserve(path, desc[key], BODIES, OUT / "native-bodies")
    else:
        expected_graph, expected = refs[branch]
        c.need(expected_graph == graph, "complete same-revision Cargo graph or paths changed")
        for key, path in files.items():
            native.same_file(path, desc[key], expected[key], BODIES, where)
        c.need(desc == expected, "different typed consumer, runtime, diagnostic, or ELF")
    if mode == "plain":
        summary["whole"] = instrument.strict_clock(where / "clock.json")
    elif mode == "tree":
        inodes = c.read(where / "path-inodes.json.gz")
        ownership.signed_cargo_images(
            where / "trace", b.SDK / "bin/cargo", c.read(OUT / "sdk.json")["bin/cargo"][1:3]
        )
        classified = topo.read(
            where / "trace", selectors, mode, component=partial(ownership.classify, REPO, WORK, products, inodes)
        )
        ownership.early_children(where / "trace", classified)
        c.save(where / "owner-raw.json", classified)
        summary["whole"] = classified["whole"]
    summary.update(
        cli=desc["cli"]["whole"], reader=desc["reader"]["whole"], dirty=sum(not r["fresh"] for r in products)
    )
    c.save(where / "visit.json", summary)


def main(collector, contract):
    c.need(
        not any(os.environ.get(k) for k in ("GH_TOKEN", "GITHUB_TOKEN", "RUSTC_WRAPPER", "LD_PRELOAD")),
        "ambient credentials or interposition in hardware step",
    )
    c.need(
        c.read(OUT / "enrollment.json")["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "changed host",
    )
    cpus = sorted(os.sched_getaffinity(0))
    c.need(len(cpus) >= 4 and shutil.disk_usage(WORK).free >= 24 * 2**30, "insufficient four CPUs or 24 GiB free")
    physical = {}
    for cpu in cpus:
        d = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        key = tuple(int((d / k).read_text()) for k in ("physical_package_id", "core_id"))
        physical.setdefault(key, cpu)
    c.need(len(physical) >= 4, "four distinct physical cores are required")
    chosen = list(physical.items())[:4]
    os.sched_setaffinity(0, [cpu for _, cpu in chosen])
    c.save(OUT / "cpu-selection.json", chosen)
    sys.path.insert(0, str(HERE.parent / "ruff-repair-tables-pilot"))
    import guards

    guards.admit(guards.resources(WORK, OUT), entry=True)
    inputs()
    topo, pmu = instrument.compile_sources(collector, contract, ROOT / "calibrator-source")
    (ROOT / "counter-kit").mkdir()
    tools = pmu.compilers(ROOT / "counter-kit")
    pmu.calibration(tools, OUT)
    shutil.copytree(tools, OUT / "counter-programs")
    gcc = Path(shutil.which("cc", path=ENV["PATH"])).resolve(strict=True)
    collect2 = Path(
        subprocess.check_output([gcc, "-print-prog-name=collect2"], env=ENV, text=True).strip()
    ).resolve(strict=True)
    paths = [b.SDK / "bin/rustc", gcc, collect2, b.SDK / b.WILD]
    selectors = {n: topo.location(p) for n, p in zip(topo.ROLES, paths, strict=True)}
    c.save(OUT / "selectors.json", selectors)
    c.save(OUT / "selector-sha.json", {n: c.sha(v[2]) for n, v in selectors.items()})
    refs = {}
    for lane, phases in c.PHASES.items():
        (OUT / lane).mkdir()
        b.fresh_outputs()
        switch("A" if lane == "empty-invalid" else "B")
        try:
            for phase in phases:
                if lane == "reference" and phase == "A":
                    b.fresh_outputs()
                run_visit(lane, phase, refs, tools, topo)
        except Exception:
            if lane != "attributed":
                raise
            (OUT / "attribution-refusal.txt").write_text(traceback.format_exc())
            if c.git(REPO, "status", "--porcelain"):
                source("A", "invalid")
                c.git(REPO, "restore", "--worktree", "--", c.PARSER)
            # Still collect the second ordinary window. A refused native/PMU
            # census can never pass the terminal gate, even if it was last.
    after = acquire.verify_sdk(b.SDK)
    c.save(OUT / "sdk-after.json", after)
    c.need(
        after == c.read(OUT / "sdk.json")
        and all(c.sha(v[2]) == c.read(OUT / "selector-sha.json")[n] for n, v in selectors.items()),
        "physical compiler or native tools mutated",
    )
    c.need(not (OUT / "attribution-refusal.txt").exists(), "attribution refused; ordinary clocks retained")
    c.save(
        OUT / "collection.json",
        {"histories": c.PHASES, "known_unrelated_native_bug": True, "hardware_scope": "first-A only"},
    )


if __name__ == "__main__":
    try:
        main(*map(Path, sys.argv[1:]))
    except BaseException:
        if OUT.is_dir() and not (OUT / "refusal.txt").exists():
            (OUT / "refusal.txt").write_text(traceback.format_exc())
        raise
