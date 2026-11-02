"""One fresh Linux screen. Clock only Cargo (or the explicitly named observer)."""

from collections import Counter
import gzip
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study as p
import setup
from setup import acquire, c

sys.path[:0] = [str(setup.CGU), str(setup.BASE)]
import physical
import instrument
import ownership

sys.path.insert(0, str(HERE.parent / "branch-return-pmu"))
sys.path.insert(0, str(HERE))
import bindings as b
import native

physical.CRATES = (p.OWNER,)
ROOT, WORK, OUT, SDK = b.ROOT, b.WORK, b.OUT, b.SDK
ENV = b.environment("signed22", permitted=("signed22",))
TRACE = {"observe": "observe", "capture": "capture", "capture-empty": "capture"}


def gz(path, raw):
    with path.open("xb") as f:
        f.write(gzip.compress(raw, compresslevel=2, mtime=0))


def load_modules():
    # Retain the exact timed-GC and unlocked-session proof, changing only the crate-name predicate.
    old = HERE.parent / "ohm-packed-ruff/full-cli/failed_session.py"
    original = old.read_bytes()
    p.need(original.count(b"ruff_python_parser-") == 1, "changed failed-session probe")
    dest = ROOT / "workspace_failed_session.py"
    dest.write_bytes(original.replace(b"ruff_python_parser-", b"ruff_workspace-"))
    sys.path[:0] = [str(old.parent), str(old.parent.parent / "harness")]
    spec = importlib.util.spec_from_file_location("workspace_failed_session", dest)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def graph_key(package, target, features):
    return json.dumps(
        [
            package,
            target["name"],
            target["kind"],
            target["crate_types"],
            target["src_path"],
            sorted(features),
        ],
        separators=(",", ":"),
    )


def graph_units(raw):
    p.need(raw["version"] == 1 and len(raw["roots"]) == 1, "wrong unit graph or root count")
    us = raw["units"]
    root = us[raw["roots"][0]]
    p.need(
        root["target"]["name"] == p.OWNER and root["target"]["kind"] == ["lib"] and root["mode"] == "build",
        "wrong Cargo root",
    )
    visited = set()
    remaining = list(raw["roots"])
    while remaining:
        i = remaining.pop()
        if i not in visited:
            visited.add(i)
            remaining.extend(d["index"] for d in us[i]["dependencies"])
    p.need(
        len(visited) == len(us) and all(u["mode"] in ("build", "run-custom-build") for u in us),
        "extra or unrecognized graph unit",
    )
    return Counter(graph_key(u["pkg_id"], u["target"], u["features"]) for u in us if u["mode"] == "build")


def command_output(cmd, cwd, env):
    return subprocess.run(
        list(map(str, cmd)), cwd=cwd, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=1800
    )


def setup_inputs(repo):
    p.need(
        p.git(repo, "rev-parse", "HEAD").decode().strip() == p.NEW
        and not p.git(repo, "status", "--porcelain"),
        "checkout must be the clean historical change",
    )
    gold = p.source_pair(repo)
    if not (OUT / "source").exists():
        (OUT / "source").mkdir()
    for label, rev in p.REVISIONS.items():
        for name in (p.OPTIONS, p.SCHEMA, "Cargo.lock", "Cargo.toml", "crates/ruff_workspace/Cargo.toml"):
            gz(
                OUT / "source" / (label + "-" + name.replace("/", "_") + ".gz"),
                p.git(repo, "show", rev + ":" + name),
            )
    p.git(repo, "switch", "--quiet", "--detach", p.OLD)
    p.source_state(repo, p.OLD, False)
    for name, body in (
        ("option-client.rs", (HERE / "client.rs").read_bytes()),
        ("bad-option-client.rs", p.BAD_CLIENT),
    ):
        (ROOT / name).write_bytes(body)
        (OUT / "source" / name).write_bytes(body)
    for name, commit in (("cargo", c.SDK["cargo"]), ("rustc", c.SDK["rust"]), ("rustdoc", c.SDK["rust"])):
        actual = subprocess.check_output(
            [b.PROXIES / "rustup", "which", "--toolchain", "ohm", name], env=ENV, text=True
        ).strip()
        version = subprocess.check_output([name, "+ohm", "-vV"], env=ENV)
        p.need(
            Path(actual).samefile(SDK / "bin" / name)
            and commit.encode() in version
            and b"ohm-1.99.0-22" in version,
            "incorrect named tool",
        )
        (OUT / (name + ".version")).write_bytes(version)
    ldd = subprocess.check_output(["ldd", SDK / "bin/rustc"], env=ENV)
    (OUT / "rustc.ldd").write_bytes(ldd)
    (driver,) = [name for name in c.SDK["members"] if name.startswith("lib/librustc_driver")]
    mapped = [
        row.split(" => ")[1].split()[0]
        for row in ldd.decode().splitlines()
        if "librustc_driver" in row and " => " in row
    ]
    p.need(len(mapped) == 1 and Path(mapped[0]).samefile(SDK / driver), "wrong mapped signed driver")
    p.save(OUT / "environment.json", ENV)
    fetch = command_output(
        ["cargo", "+ohm", "fetch", "--locked"], repo, {**ENV, "CARGO_NET_OFFLINE": "false"}
    )
    gz(OUT / "fetch.stderr.gz", fetch.stderr)
    p.need(fetch.returncode == 0, "Cargo.fetch")
    lock = tomllib.loads((repo / "Cargo.lock").read_text())
    packages = {
        q["name"] + "-" + q["version"] + ".crate": q["checksum"] for q in lock["package"] if "checksum" in q
    }
    registry = Path(ENV["CARGO_HOME"]) / "registry/cache"

    def ledger():
        found = {}
        for f in registry.glob("*/*.crate"):
            p.need(
                f.is_file() and not f.is_symlink() and f.name not in found and f.name in packages,
                ("foreign registry input", f),
            )
            h = c.sha(f)
            p.need(h == packages[f.name], ("Cargo.lock checksum mismatch", f))
            found[f.name] = h
        p.need(found, "empty registry")
        return found

    registry_before = ledger()
    p.save(OUT / "registry.json", registry_before)
    plans = {}
    for label, rev in p.REVISIONS.items():
        p.write_source(repo, rev, False)
        cmd = p.CMD[:3] + ["-Zunstable-options", "--unit-graph"] + p.CMD[3:]
        result = command_output(cmd, repo, ENV)
        gz(OUT / (label + "-plan.json.gz"), result.stdout)
        gz(OUT / (label + "-plan.stderr.gz"), result.stderr)
        p.need(result.returncode == 0, "separate unit graph")
        decoded = json.loads(result.stdout)
        plans[label] = graph_units(decoded)
        for u in decoded["units"]:
            ident = u["pkg_id"]
            if ident.startswith("registry+"):
                package, version = ident.rsplit("#", 1)[1].rsplit("@", 1)
                p.need(
                    package + "-" + version + ".crate" in registry_before,
                    ("unverified graph registry crate", ident),
                )
        for key, body in gold[rev].items():
            (OUT / (label + "-" + key + ".txt")).write_bytes(body)
    p.need(
        plans["old"] == plans["new"]
        and gzip.decompress((OUT / "old-plan.json.gz").read_bytes())
        == gzip.decompress((OUT / "new-plan.json.gz").read_bytes()),
        "different old/new unit graph",
    )
    return gold, plans["old"], ledger


def roots_for(row, call, work):
    """Resolve the hashed compiler output as well as Cargo's potentially promoted root library."""
    promoted = p.artifact([row], p.OWNER)
    p.need(
        promoted.resolve(strict=True) == promoted and promoted.is_relative_to(work),
        "root rlib outside targets",
    )
    actual = promoted
    if call is not None:
        args = physical.nul(call / "original.nul")
        out = Path(ownership.option(args, "--out-dir"))
        (suffix,) = [a.removeprefix("extra-filename=") for a in args if a.startswith("extra-filename=")]
        actual = out / ("lib" + p.OWNER + suffix + ".rlib")
        p.need(
            actual.resolve(strict=True) == actual and actual.is_relative_to(work),
            "untrusted compiler output",
        )
        p.need(
            actual.samefile(promoted)
            or (actual.stat().st_size == promoted.stat().st_size and c.sha(actual) == c.sha(promoted)),
            "promoted root differs from actual workspace rlib",
        )
    return promoted, actual


def captured(where, rows, mode, work, store, bad):
    stage = where / "stage"
    actor = stage / p.OWNER
    if bad:
        p.need(
            not [r for r in rows if r["reason"] == "compiler-artifact" and r["target"]["name"] == p.OWNER],
            "failed build advertised a successful product",
        )
        if mode:
            p.need(actor.is_dir() and not (stage / "ruff_linter").exists(), "wrong failed owner")
            args = physical.nul(actor / "original.nul")
            out = Path(ownership.option(args, "--out-dir"))
            files = physical.stage(p.OWNER, out, actor / "emitted")
            p.save(actor / "emitted.json", files)
            p.need(not files, "E0308 unexpectedly generated LLVM inputs")
        physical.assert_empty(work)
        p.save(where / "cgus.json", {})
        return
    prods = [r for r in rows if r["reason"] == "compiler-artifact"]
    (row,) = [r for r in prods if r["target"]["name"] == p.OWNER and r["target"]["kind"] == ["lib"]]
    promoted, actual = roots_for(row, actor if actor.exists() else None, work)
    p.save(
        where / "root-archive.json",
        {
            "promoted": str(promoted),
            "compiler": str(actual),
            "same_inode": actual.samefile(promoted),
            "sha256": c.sha(actual),
            "stats": [physical.stat_key(f.stat()) for f in (promoted, actual)],
        },
    )
    replaced = {**row, "filenames": [str(actual) if n == str(promoted) else n for n in row["filenames"]]}
    physical.snapshot(where, [replaced, rows[-1]], stage, store, work, mode == "capture")


def counter_sources(collector, contract):
    topo, pmu = instrument.compile_sources(collector, contract, ROOT / "counter-source")
    folder = ROOT / "counter-kit"
    folder.mkdir()
    tools = pmu.compilers(folder)
    pmu.calibration(tools, OUT)
    shutil.copytree(tools, OUT / "counter-programs")
    cc = Path(shutil.which("cc", path=ENV["PATH"])).resolve(strict=True)
    collect2 = Path(
        subprocess.check_output([cc, "-print-prog-name=collect2"], env=ENV, text=True).strip()
    ).resolve(strict=True)
    paths = [SDK / "bin/rustc", cc, collect2, SDK / b.WILD]
    selectors = {role: topo.location(path) for role, path in zip(topo.ROLES, paths, strict=True)}
    p.save(OUT / "selectors.json", selectors)
    p.save(OUT / "selector-sha.json", {k: c.sha(v[2]) for k, v in selectors.items()})
    return tools, selectors


def measured_cmd(lane, phase, where, tools, selectors):
    cmd = list(p.CMD)
    clock = lane == "plain" or (lane in ("observe", "capture") and phase == "new")
    mode = TRACE.get(lane)
    if mode:
        stage = where / "stage"
        stage.mkdir()
        cmd = [ROOT / "workspace-cgu", stage, SDK / "bin/rustc", mode, *cmd]
    if lane == "owner" and phase == "new":
        trace = where / "owner-trace"
        trace.mkdir()
        cmd = [tools / "tree", trace, "tree", *[s[2] for s in selectors.values()], *cmd]
    if clock:
        cmd = [tools / "plain", where / "clock.json", *cmd]
    return cmd, mode


def visit(repo, lane, phase, tools, selectors, graph, gold, store, failed):
    where = OUT / lane / phase
    where.mkdir()
    if p.fresh(lane, phase):
        b.fresh_outputs()
        p.save(
            where / "empty-roots.json",
            {
                str(x): physical.stat_key(x.stat())
                for x in (WORK / "target", WORK / "build")
                if not any(x.iterdir())
            },
        )
    rev, bad = p.revision(phase), phase == "invalid"
    before = p.write_source(repo, rev, bad)
    p.save(where / "source-before.json", before)
    if phase == "unchanged":
        p.need(before == c.read(where.parent / "new/source-after.json"), "unexpected source edit on repeat")
    if phase == "repair":
        failed.before_repair(WORK, c.read(where.parent / "invalid/failed.json"), where / "grace.json")
    cmd, mode = measured_cmd(lane, phase, where, tools, selectors)
    env = {**ENV, **({"OHM_CGU_REQUEST": p.FLAG} if mode else {})}
    p.save(
        where / "invocation.json",
        {"cmd": list(map(str, cmd)), "cargo": p.CMD, "cwd": str(repo), "env": env},
    )
    physical.assert_empty(WORK)
    result = command_output(cmd, repo, env)
    gz(where / "cargo.stdout.gz", result.stdout)
    gz(where / "cargo.stderr.gz", result.stderr)
    p.save(where / "exit.json", result.returncode)
    p.need(
        result.returncode == (101 if bad else 0), (lane, phase, result.returncode, result.stderr[-2000:])
    )
    after = p.source_state(repo, rev, bad)
    p.need(after == before, "source changed while Cargo ran")
    p.save(where / "source-after.json", after)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    products = p.results(rows, not bad)
    ownership.check_roots(rows, WORK)
    if not bad:
        actual = Counter(graph_key(r["package_id"], r["target"], r["features"]) for r in products)
        p.need(actual == graph, ("Cargo JSON/unit graph mismatch", actual - graph, graph - actual))
        if p.fresh(lane, phase):
            p.need(all(not r["fresh"] for r in products), "false empty reference")
        if phase == "unchanged":
            p.need(all(r["fresh"] for r in products), "unchanged Cargo performed real build work")
    sessions = failed.observed(WORK)
    p.need(bad or not sessions, "unexpected unlocked partially written session")
    if bad:
        p.save(where / "failed.json", sessions)
    captured(where, rows, mode, WORK, store, bad)
    if not bad:
        native.client(where, rows, products, ROOT, WORK, ENV, gold[rev], OUT / "client-bodies")


def run(repo, collector, contract):
    setup.inherited()
    sys.path.insert(0, str(HERE.parent / "ruff-repair-tables-pilot"))
    import guards

    guards.admit(guards.resources(WORK, OUT), entry=True)
    p.need(
        not any(
            v in os.environ
            for v in (
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "RUSTC",
                "RUSTFLAGS",
                "RUSTC_WRAPPER",
                "CARGO_ENCODED_RUSTFLAGS",
                "RUSTC_WORKSPACE_WRAPPER",
                "LD_PRELOAD",
                "OHM_CGU_REQUEST",
            )
        ),
        "ambient overrides/credentials",
    )
    p.need(
        c.read(OUT / "enrollment.json")["boot"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "changed enrolled boot",
    )
    cores = {}
    for n in sorted(os.sched_getaffinity(0)):
        t = Path(f"/sys/devices/system/cpu/cpu{n}/topology")
        cores.setdefault(tuple(int((t / k).read_text()) for k in ("physical_package_id", "core_id")), n)
    p.need(
        len(cores) >= 4 and shutil.disk_usage(WORK).free >= 24 << 30, "need four physical cores and 24 GiB"
    )
    chosen = list(cores.items())[:4]
    os.sched_setaffinity(0, [v for _, v in chosen])
    p.save(OUT / "cpus.json", chosen)
    gold, graph, registry = setup_inputs(repo)
    tools, selectors = counter_sources(collector, contract)
    program = ROOT / "workspace-cgu"
    p.need(
        program.is_file() and (ROOT / "workspace-cgu.c").read_bytes() == setup.capture_source(),
        "missing qualified recorder",
    )
    shutil.copyfile(program, OUT / "recorder")
    p.save(
        OUT / "recorder.json",
        {"source": p.sha(setup.capture_source()), "elf": c.sha(program), "parent": setup.CAPTURE},
    )
    store = OUT / "cgu-originals"
    store.mkdir()
    (OUT / "client-bodies").mkdir()
    failed = load_modules()
    for lane, phases in p.HISTORIES.items():
        (OUT / lane).mkdir()
        for phase in phases:
            visit(repo, lane, phase, tools, selectors, graph, gold, store, failed)
            p.need(
                sum(x.stat().st_size for x in (OUT / "client-bodies").iterdir()) < 300 << 20,
                "typed clients exceeded 300 MiB compressed",
            )
    p.need(
        registry() == c.read(OUT / "registry.json") and acquire.verify_sdk(SDK) == c.read(OUT / "sdk.json"),
        "toolchain or registry changed",
    )
    p.need(
        {k: c.sha(v[2]) for k, v in selectors.items()} == c.read(OUT / "selector-sha.json")
        and c.sha(program) == c.read(OUT / "recorder.json")["elf"],
        "observer or selected native executable changed",
    )
    p.save(
        OUT / "complete.json",
        {"histories": p.HISTORIES, "ordinary": p.CMD, "graph": sum(graph.values()), "source": p.REVISIONS},
    )


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("worker.py RUFF COLLECTOR CONTRACT")
    run(*(Path(x).resolve(strict=True) for x in sys.argv[1:]))
