"""Run and independently reopen the signed Ruff histories and their original compiler arguments."""

import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
if sys.argv[1:2] == ["reopen"]:
    # Archived paths in the standalone reader come from the authenticated worker records.
    os.environ.setdefault("RUNNER_TEMP", tempfile.gettempdir())
import green_inputs
import green_probe
import read_products
import acquire_cgu as a
import worker as w
from acquire_cgu import c

c.need(Path(w.__file__).resolve() == a.BASE / "worker.py", "foreign first-A worker")

HISTORIES = {
    "reference": ("B", "A"),
    "plain-1": ("B", "A"),
    "ordinary-observed": ("B", "A"),
    "diagnostic-empty": ("B", "A"),
    "diagnostic": ("B", "A", "unchanged", "invalid", "repair"),
    "green-reasons": ("B", "A"),
}
TRACED = {"ordinary-observed": "observe", "diagnostic-empty": "capture", "diagnostic": "capture"}
OWNERS = ("ruff_linter", "ruff_workspace")
REQUEST = "OHM_CGU_REQUEST"
FLAG = "-Csave-temps=yes"
FORBIDDEN = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "RUSTC",
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "LD_PRELOAD",
)


def module(name, path):
    # Legacy Git checkouts contain unrelated files named worker, reopen, and physical.
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
    result = sys.modules[name]
    c.need(Path(result.__file__).resolve() == path, ("unrelated helper imported", name))
    return result


def ordinary_env(env):
    c.need(
        not any(k in env for k in (*FORBIDDEN, REQUEST))
        and not any("TRUST" in k or "BRANCH_CACHE" in k or k.startswith("OHM_CGUR_") or k=="VALGRIND_LIB" for k in env),
        "unexpected compiler, trust or credential environment",
    )


def trace_mode(lane, phase):
    if lane == "green-reasons":
        return "cgured" if phase == "A" else "observe"
    return TRACED.get(lane)


def is_empty(lane, phase):
    return phase == "B" or (phase == "A" and lane in ("reference", "diagnostic-empty"))


def prove_empty(work):
    result = {}
    for name in ("target", "build"):
        path = work / name
        c.need(
            path.resolve(strict=True) == path and path.is_dir() and not any(path.iterdir()),
            "nonempty independent target",
        )
        st = path.stat()
        result[str(path)] = [st.st_dev, st.st_ino, []]
    c.need(len({tuple(v[:2]) for v in result.values()}) == 2, "aliased independent targets")
    return result


def visit(lane, phase, refs, tools, topo, capture, store, physical):
    where = w.OUT / lane / phase
    stage = where / "stage"
    original, env = w.invoke, w.ENV
    ordinary_env(env)
    mode = trace_mode(lane, phase)
    called = False

    def run_cargo(folder, cmd, want, sampler=None):
        nonlocal called
        c.need(not called and folder == where and sampler is None, "unexpected nested Cargo or profiler")
        called = True
        if lane == "diagnostic-empty" and phase == "A":
            c.save(where / "empty-roots.json", prove_empty(w.WORK))
        expected = list(c.CMD)
        if (lane, phase) == ("plain-1", "A"):
            expected = [tools / "plain", where / "clock.json", *expected]
        c.need(list(cmd) == expected, "ordinary Cargo command was altered")
        cmd = list(cmd)
        if mode:
            stage.mkdir(mode=0o700)
            tracer = w.ROOT/"green-kit/capture" if mode == "cgured" else capture
            cmd = [tracer, stage, w.b.SDK / "bin/rustc", mode, *cmd]
        c.save(where / "cargo-environment.json", w.ENV)
        physical.assert_empty(w.WORK)
        green_lane = lane in ("ordinary-observed", "diagnostic", "green-reasons") and phase in ("A","B")
        if green_lane and phase == "A":
            green_inputs.capture(where,where.parent/"B/stage/ruff_workspace/original.nul",
                                 w.WORK,w.OUT/"green-originals","before")
        try:
            rows = original(folder, cmd, want, sampler=None)
        finally:
            # The independent native clients, programs and the following visit get the original environment.
            w.ENV = env
        w.ownership.check_roots(rows, w.WORK)
        physical.snapshot(where, rows, stage, store, w.WORK, mode == "capture")
        if green_lane:
            green_inputs.capture(where,stage/"ruff_workspace/original.nul",w.WORK,w.OUT/"green-originals","after")
        return rows

    w.invoke = run_cargo
    if mode:
        w.ENV = {**env, REQUEST: FLAG}
        if mode == "cgured":
            w.ENV.update(green_probe.environment(w.ROOT, stage, w.WORK, w.b.SDK/"bin/rustc"))
    try:
        w.run_visit(lane, phase, refs, tools, topo, None)
        c.need(called, "missing actual Cargo invocation")
    finally:
        w.invoke, w.ENV = original, env


def histories(tools, topo, capture, store, physical):
    refs = {}
    for lane, phases in HISTORIES.items():
        (w.OUT / lane).mkdir()
        for phase in phases:
            if is_empty(lane, phase):
                w.b.fresh_outputs()
            visit(lane, phase, refs, tools, topo, capture, store, physical)


def compile_capture():
    capture = w.ROOT / "cgu-capture"
    c.need(not capture.exists() and not capture.is_symlink(), "preexisting recorder")
    cc = Path(shutil.which("cc", path=w.ENV["PATH"])).resolve(strict=True)
    command = [
        "cc",
        "-std=c11",
        "-O2",
        "-Wall",
        "-Wextra",
        "-Werror",
        str(HERE / "capture.c"),
        "-o",
        str(capture),
    ]
    subprocess.run(command, check=True, env=w.ENV)
    shutil.copyfile(capture, w.OUT / "capture-program")
    c.save(
        w.OUT / "capture-build.json",
        {"argv": command, "source": c.sha(HERE / "capture.c"), "cc": c.sha(cc), "elf": c.sha(capture)},
    )


def prepare(collector, contract):
    c.need(
        not any(os.environ.get(k) for k in (*FORBIDDEN, REQUEST))
        and not any("CARGO_UNSTABLE_OHM_" in k and "TRUST" in k for k in os.environ),
        "ambient credentials or compiler override",
    )
    c.need(
        c.read(w.OUT / "enrollment.json")["boot"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "changed boot",
    )
    cpus = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        d = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
        cpus.setdefault(tuple(int((d / k).read_text()) for k in ("physical_package_id", "core_id")), cpu)
    c.need(
        len(cpus) >= 4 and shutil.disk_usage(w.WORK).free >= 24 << 30,
        "four physical cores and 24 GiB of work space required",
    )
    chosen = list(cpus.items())[:4]
    os.sched_setaffinity(0, [v for _, v in chosen])
    c.save(w.OUT / "cpu-selection.json", chosen)
    guards = module("cgu_resource_guard", HERE.parent / "ruff-repair-tables-pilot/guards.py")
    guards.admit(guards.resources(w.WORK, w.OUT), entry=True)
    ordinary_env(w.ENV)
    w.inputs()
    topo, pmu = w.instrument.compile_sources(collector, contract, w.ROOT / "calibrator-source")
    counter_dir = w.ROOT / "counter-kit"
    counter_dir.mkdir()
    tools = pmu.compilers(counter_dir)
    pmu.calibration(tools, w.OUT)
    shutil.copytree(tools, w.OUT / "counter-programs")
    cc = Path(shutil.which("cc", path=w.ENV["PATH"])).resolve(strict=True)
    collect2 = Path(
        subprocess.check_output([cc, "-print-prog-name=collect2"], env=w.ENV, text=True).strip()
    ).resolve(strict=True)
    paths = (w.b.SDK / "bin/rustc", cc, collect2, w.b.SDK / w.b.WILD)
    selectors = {n: topo.location(p) for n, p in zip(topo.ROLES, paths, strict=True)}
    c.save(w.OUT / "selectors.json", selectors)
    c.save(w.OUT / "selector-sha.json", {n: c.sha(v[2]) for n, v in selectors.items()})
    capture = w.ROOT / "cgu-capture"
    proof = c.read(w.OUT / "capture-build.json")
    c.need(
        proof["cc"] == c.sha(cc)
        and proof["source"] == c.sha(HERE / "capture.c")
        and proof["elf"] == c.sha(capture) == c.sha(w.OUT / "capture-program"),
        "changed recorder since fixture",
    )
    return tools, topo, capture


def worker(collector, contract):
    a.verify_inherited_sources()
    tools, topo, capture = prepare(collector, contract)
    (w.OUT / "green-originals").mkdir()
    store = w.OUT / "cgu-originals"
    store.mkdir()
    physical = module("physical", HERE / "physical.py")
    c.save(w.OUT/"green-probe-build.json", green_probe.build(w.ROOT, w.b.SDK, w.ENV))
    histories(tools, topo, capture, store, physical)
    c.save(w.OUT/"green-probe-trace.json", green_probe.records(w.OUT/"green-reasons/A/stage/ruff_workspace"))
    c.save(w.OUT/"green-probe-reasons.json",green_probe.classify(w.OUT, w.b.SDK))
    c.save(w.OUT / "green-inputs-verified.json",green_inputs.verify(w.OUT, ("ordinary-observed", "diagnostic", "green-reasons")))
    c.save(w.OUT / "green-work-products.json", read_products.read_history(w.OUT, ("ordinary-observed", "diagnostic", "green-reasons")))
    after = w.acquire.verify_sdk(w.b.SDK)
    c.save(w.OUT / "sdk-after.json", after)
    c.need(after == c.read(w.OUT / "sdk.json"), "signed SDK changed")
    selectors = c.read(w.OUT / "selectors.json")
    c.need(
        c.read(w.OUT / "selector-sha.json") == {n: c.sha(v[2]) for n, v in selectors.items()}
        and c.sha(capture) == c.read(w.OUT / "capture-build.json")["elf"],
        "native tool changed",
    )
    c.save(w.OUT / "cgu-history.json", {"histories": HISTORIES, "pmu": ["plain-1/A"], "trace": TRACED})


def decoded(raw):
    c.need(0 < len(raw) <= 1 << 20 and raw.endswith(b"\0"), "incomplete original rustc NUL vector")
    return [v.decode() for v in raw[:-1].split(b"\0")]


def recorded_roster(z, prefix, products, repo, work, rustc, inodes, mode, first_a):
    """Bind every original stopped rustc argv to its row and each selected effective argv to that same PID."""
    selected = {
        r["target"]["name"]
        for r in products
        if r["target"]["name"] in OWNERS and r["target"]["kind"] == ["lib"] and not r["fresh"]
    }
    roster = [json.loads(line) for line in z.read(prefix + "/rustc.jsonl").splitlines()]
    c.need(len(roster) <= 1024 and (not first_a or roster), "incomplete original rustc roster")
    names = set(z.namelist())
    files = set()
    owner_pids = {}
    all_vectors = Counter()
    full = []
    for seq, record in enumerate(roster, 1):
        name = f"rustc-{seq:05d}.nul"
        c.need(
            set(record) == {"seq", "pid", "crate", "entry"}
            and record["seq"] == seq
            and type(record["pid"]) is int
            and record["pid"] > 0
            and record["entry"] == name,
            "rustc roster binding",
        )
        path = prefix + "/" + name
        raw = z.read(path)
        args = decoded(raw)
        files.add(path)
        all_vectors[raw] += 1
        c.need(
            args[0] == rustc[2] and not any(v in (FLAG, "save-temps=yes") for v in args),
            "interposed original compiler",
        )
        name = w.ownership.option(args, "--crate-name") if "--crate-name" in args else ""
        c.need(name == record["crate"], "different registered rustc owner")
        if w.ownership.rustc_query(args):
            continue
        if first_a:
            product, compile_mode, _ = w.ownership.event_product(products, {"argv": args}, repo, work, inodes)
            c.need(not product["fresh"], "physical rustc matched a Cargo-fresh first-A unit")
            o = {
                "mode": compile_mode,
                "target": product["target"]["name"],
                "kind": product["target"]["kind"],
                "profile": product["profile"],
                "features": product["features"],
                "src": product["target"]["src_path"],
                "package": product["package_id"],
            }
            _, descriptor = w.leaf_profile.expected_owner(o, repo.parent, args)
            full.append(descriptor)
        if (
            name in OWNERS
            and "--crate-type" in args
            and w.ownership.option(args, "--crate-type") == "lib"
            and "--out-dir" in args
        ):
            c.need(
                name in selected and name not in owner_pids and "--emit=dep-info,metadata,link" in args,
                "unexpected selected library rustc",
            )
            base = prefix + "/" + name + "/"
            original, observed = (z.read(base + item + ".nul") for item in ("original", "observed"))
            data = json.loads(z.read(base + "process.json"))
            changed = mode == "capture"
            c.need(
                original == raw and observed == original + ((FLAG.encode() + b"\0") if changed else b""),
                "effective argv differs beyond the one registered argument",
            )
            c.need(
                data["pid"] == record["pid"]
                and [data["compiler_dev"], data["compiler_ino"]] == rustc[:2]
                and data["capture"] is changed
                and data["argc"] == [len(args), len(args) + changed]
                and len(data["envc"]) == 2
                and data["envc"][0] > 0
                and data["envc"][1] == data["envc"][0] - changed
                and 0 < data["aux_pairs"] <= 128,
                "incorrect physical selected-process witness",
            )
            owner_pids[name] = record["pid"]
    c.need(
        files == {p for p in names if p.startswith(prefix + "/rustc-") and p.endswith(".nul")},
        "unaccounted compiler argv file",
    )
    c.need(
        set(owner_pids) == selected
        and len(set(owner_pids.values())) == len(selected)
        and all(any(p.startswith(prefix + "/" + n + "/") for p in names) == (n in selected) for n in OWNERS),
        "missing or additional instrumented library process",
    )
    if first_a:
        by = lambda row: (row["name"], row["kind"])
        c.need(
            sorted(full, key=by) == sorted(c.read(a.BASE / "first-a-owners.json"), key=by),
            "physical first-A owners, compiler modes, inputs or flags differ",
        )
    return all_vectors


def cargo_dirty(products, repo):
    def key(p):
        t = p["target"]
        return (
            p["package_id"],
            t["name"],
            tuple(t["kind"]),
            tuple(t["crate_types"]),
            t["src_path"],
            tuple(sorted(p["features"])),
            json.dumps(p["profile"], sort_keys=True),
            tuple(p["filenames"]),
            p["executable"] or "",
        )

    dirty = [p for p in products if not p["fresh"]]
    expected = c.read(a.BASE / "first-a-owners.json")
    fields = ("name", "kind", "source", "features", "profile", "package_version")
    actual = [
        {
            "name": p["target"]["name"],
            "kind": p["target"]["kind"],
            "source": str(Path(p["target"]["src_path"]).relative_to(repo)),
            "features": sorted(p["features"]),
            "profile": p["profile"],
            "package_version": p["package_id"].rsplit("#", 1)[-1],
        }
        for p in dirty
    ]
    c.need(
        sorted(json.dumps(r, sort_keys=True) for r in actual)
        == sorted(json.dumps({k: r[k] for k in fields}, sort_keys=True) for r in expected),
        "first-A dirty Cargo units differ from the signed 20",
    )
    return sorted(key(r) for r in dirty)


def same_vectors(observed, diagnostic):
    c.need(observed and observed == diagnostic, "ordinary and diagnostic kernel argv multisets differ")


def visit_evidence(z, old, root, work, selectors):
    refs, dirties, vectors, summaries = {}, {}, {}, {}
    parent_env = old.record(z, "execution-environment.json")["env"]
    ordinary_env(parent_env)
    for lane, phases in HISTORIES.items():
        for phase in phases:
            prefix = f"{lane}/{phase}"
            branch = "B" if phase == "B" else "A"
            bad = phase == "invalid"
            mode = trace_mode(lane, phase)
            clock = (lane, phase) == ("plain-1", "A")

            def record(n, visit_prefix=prefix):
                return old.record(z, visit_prefix + "/" + n)

            cmd = list(c.CMD)
            if mode:
                cmd = [
                    str(root / ("green-kit/capture" if mode=="cgured" else "cgu-capture")),
                    str(root / "logs" / prefix / "stage"),
                    selectors["rustc"][2],
                    mode,
                    *cmd,
                ]
            if clock:
                cmd = [str(root / "counter-kit/bin/plain"), str(root / "logs" / prefix / "clock.json"), *cmd]
            want = 101 if bad else 0
            c.need(
                record("invocation.json")
                == {"argv": cmd, "cargo": c.CMD, "cwd": str(root / "ruff"), "expected": want, "exit": want},
                "unregistered Cargo invocation",
            )
            c.need(
                record("cargo-environment.json") == (parent_env | ({REQUEST: FLAG} if mode else {}) |
                    (green_probe.environment(root, root/"logs"/prefix/"stage",work,selectors["rustc"][2]) if mode=="cgured" else {})),
                "different actual Cargo environment",
            )
            before = record("source-before.json")
            old.source_state(before, branch, bad)
            c.need(record("source-after.json") == before, "source changed during a visit")
            if phase == "unchanged":
                c.need(
                    before == old.record(z, lane + "/A/source-after.json"),
                    "unchanged visit changed source or branch watch",
                )
            if is_empty(lane, phase):
                nodes = record("empty-roots.json")
                c.need(
                    set(nodes) == {str(work / "target"), str(work / "build")}
                    and all(len(v) == 3 and min(v[:2]) > 0 and v[2] == [] for v in nodes.values())
                    and len({tuple(v[:2]) for v in nodes.values()}) == 2,
                    "fresh roots not independently empty",
                )
            rows = [
                json.loads(line) for line in gzip.decompress(z.read(prefix + "/cargo.stdout.gz")).splitlines()
            ]
            gzip.decompress(z.read(prefix + "/cargo.stderr.gz"))
            w.ownership.check_roots(rows, work)
            errors = w.ownership.typed(rows, bad)
            visit = record("visit.json")
            c.need(
                visit["phase"] == phase
                and visit["branch"] == branch
                and visit["source"] == before["rev"]
                and visit["mode"] == ("plain" if clock else "ordinary")
                and visit["diagnostic"] == record("diagnostic.json") == errors,
                "wrong visit, revision, or diagnostic",
            )
            ledger = record("path-inodes.json.gz")
            disk = record("storage.json")
            allocated = old.replay_metrics.allocation(ledger, disk, record("allocation-readers.json"))
            products = [r for r in rows if r["reason"] == "compiler-artifact"]
            if mode:
                args = recorded_roster(
                    z,
                    prefix + "/stage",
                    products,
                    root / "ruff",
                    work,
                    selectors["rustc"],
                    ledger,
                    mode,
                    lane != "diagnostic-empty" and phase == "A",
                )
                if phase == "A" and lane != "diagnostic-empty":
                    vectors[lane] = args
            else:
                c.need(
                    not any(p.startswith(prefix + "/stage/") for p in z.namelist()),
                    "tracing on an ordinary comparison",
                )
            c.need((prefix + "/clock.json" in z.namelist()) == clock, "measured an intervened or extra visit")
            if bad:
                c.need(
                    set(record("failed.json")) == set(disk["failed_sessions"]), "unaccounted failed session"
                )
                summaries[prefix] = {"expected_exit": want, "error": errors, "allocated": allocated}
                continue
            c.need(not disk["failed_sessions"], "unexplained failed session")
            if phase == "repair":
                grace = record("grace.json")
                c.need(
                    grace["sessions"] == old.record(z, lane + "/invalid/failed.json")
                    and grace["ready_ns"] >= grace["cutoff_ns"]
                    and grace["rustc_gc_grace_ns"] == 10_000_000_000,
                    "repaired before failed-session grace",
                )
            graph, products = w.ownership.graph(rows)
            c.need(
                graph == record("roster.json.gz") and visit["dirty"] == sum(not r["fresh"] for r in products),
                "incomplete 375-unit graph",
            )
            if is_empty(lane, phase):
                c.need(visit["dirty"] == 375, "fresh roots reused a Cargo artifact")
            if phase == "A" and not is_empty(lane, phase):
                dirties[lane] = cargo_dirty(products, root / "ruff")
            desc = old.replay_native.native_verdict(z, prefix, branch)
            old.actual_externs(z, prefix, products, root)
            c.need(
                visit["cli"] == desc["cli"]["whole"] and visit["reader"] == desc["reader"]["whole"],
                "wrong executable SHA",
            )
            if lane == "reference":
                refs[branch] = (graph, desc)
                for role, crate in (("cli", "ruff"), ("reader", "ohm_branch_reader")):
                    old.replay_elf.verify(
                        z, "native-bodies/" + desc[role]["whole"] + ".zst", desc[role], crate
                    )
            else:
                c.need(
                    (graph, desc) == refs[branch],
                    "native, diagnostic or graph differs from independent clean",
                )
            summaries[prefix] = {
                "cli": visit["cli"],
                "reader": visit["reader"],
                "dirty": visit["dirty"],
                "allocated": allocated,
            }
            if clock:
                count = w.instrument.clock_value(record("clock.json"))
                c.need(visit["whole"] == count, "incorrect ordinary PMU total")
                summaries[prefix]["whole_instructions"] = count
    c.need(
        dirties["plain-1"] == dirties["ordinary-observed"] == dirties["diagnostic"] == dirties["green-reasons"],
        "first-A Cargo dirty identities differ",
    )
    same_vectors(vectors["ordinary-observed"], vectors["diagnostic"])
    same_vectors(vectors["ordinary-observed"], vectors["green-reasons"])
    return {
        "visits": summaries,
        "first_A_kernel_argv": sorted(
            (hashlib.sha256(k).hexdigest(), v) for k, v in vectors["diagnostic"].items()
        ),
    }


def reopen(out, collector, contract, reviewed_head):
    a.verify_inherited_sources()
    old = module("signed_first_a_reopen", a.BASE / "reopen.py")
    z = c.Directory(out)
    c.need(
        "refusal.txt" not in z.namelist()
        and old.record(z, "cgu-history.json")
        == {"histories": {k: list(v) for k, v in HISTORIES.items()}, "pmu": ["plain-1/A"], "trace": TRACED},
        "incomplete history",
    )
    with a.registration():
        en, root, work, selectors, _, _ = old.read_subject(z, reviewed_head, None)
    c.need(
        z.read("cgu-capture-fixture.stdout")
        == b"Both target owners, observation, distinct-inode, unselected crate, and missing request passed.\n"
        and z.read("cgu-files-fixture.stdout")
        == b"Exact ELF/ar and optional-file receipts, stale inputs and malformed inputs passed.\n",
        "incomplete native recorder or physical evidence controls",
    )
    build = old.record(z, "capture-build.json")
    checkout_source = Path(build["argv"][-3])
    c.need(checkout_source.parts[-3:] == ("scripts", "ruff-cgu-inputs", "capture.c"), "wrong recorder source")
    c.need(
        build["argv"]
        == [
            "cc",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(checkout_source),
            "-o",
            str(root / "cgu-capture"),
        ]
        and build["source"] == c.sha(HERE / "capture.c")
        and build["cc"] == old.record(z, "selector-sha.json")["cc"]
        and hashlib.sha256(z.read("capture-program")).hexdigest() == build["elf"],
        "substituted tracer",
    )
    with tempfile.TemporaryDirectory(prefix="cgu-calibration-") as t:
        temp = Path(t)
        _, pmu = w.instrument.compile_sources(collector, contract, temp / "source")
        old.bounded_files(z, temp)
        pmu.calibration(temp / "counter-programs", temp, replay=True)
    original = visit_evidence(z, old, root, work, selectors)
    module("physical", HERE / "physical.py")
    physical = module("cgu_packet_reader", HERE / "reader.py").verify(out)
    owner=out/"green-reasons/A/stage/ruff_workspace"
    probe=green_probe.records(owner)
    c.need(probe==old.record(z,"green-probe-trace.json"), "changed original execution receipt")
    causes=green_probe.classify(out, Path(selectors["rustc"][2]).parents[1])
    c.need(causes==old.record(z,"green-probe-reasons.json"), "changed serialized graph explanation")
    emitted=set(old.record(z,"diagnostic/A/cgus.json")["ruff_workspace"]["emitted"])
    rejected={d["cgu"] for d in causes["decisions"] if d["actual_cgu_reuse"]=="No"}
    c.need(rejected==emitted, ("actual reuse decisions and actual saved LLVM inputs differ", sorted(rejected ^ emitted)))
    cohort=physical["comparisons"]["ruff_workspace"]["confirmed_against_both_empty_histories"]
    c.need(set(cohort)<=rejected, "an independently identical CGU had no actual compiler decision")
    cause_counts=Counter(d["reason"] for d in causes["decisions"] if d["cgu"] in cohort)

    return {
        "run": en["run"],
        "head": en["head"],
        "job": en["job"],
        "boot": en["boot"],
        "physical": physical,
        "signed_workspace_decisions": probe,
        "rejected":len(rejected),
        "independently_identical_causes":dict(cause_counts),
        **original,
    }


if __name__ == "__main__":
    if sys.argv[1:] == ["compile-capture"]:
        compile_capture()
    elif sys.argv[1:2] == ["run"] and len(sys.argv) == 4:
        try:
            worker(*(Path(p).resolve(strict=True) for p in sys.argv[2:]))
        except BaseException:
            if w.OUT.is_dir():
                (w.OUT / "refusal.txt").write_text(traceback.format_exc())
            raise
    elif sys.argv[1:2] == ["reopen"] and len(sys.argv) == 6:
        result = reopen(*(Path(p).resolve(strict=True) for p in sys.argv[2:5]), sys.argv[5])
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        raise SystemExit(
            "compile-capture | run COLLECTOR CONTRACT | reopen LOG_DIRECTORY COLLECTOR CONTRACT REVIEWED_HEAD"
        )
