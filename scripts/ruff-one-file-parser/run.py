"""Run the two default signed Cargo commands on ordinary working-tree edits."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol as p
import parser_tests
import check_checkout
import inventory
import worker as base
import instrument
import acquire

c, f = p.c, p.f
root, logs, work, repo = base.ROOT, base.OUT, base.WORK, base.REPO


def cpu():
    physical = {}
    for n in sorted(os.sched_getaffinity(0)):
        d = Path(f"/sys/devices/system/cpu/cpu{n}/topology")
        key = tuple(int((d / k).read_text()) for k in ("physical_package_id", "core_id"))
        physical.setdefault(key, n)
    f.require(
        len(physical) >= 4 and shutil.disk_usage(work).free >= 24 << 30,
        "four physical CPUs and 24 GiB initial storage",
    )
    selected = list(physical.items())[:4]
    os.sched_setaffinity(0, [n for _, n in selected])
    c.save(logs / "cpu-selection.json", selected)


def invoke(where, actual, want):
    proc = subprocess.run(
        list(map(str, actual)), env=base.ENV, cwd=repo, capture_output=True, timeout=1200
    )
    for label, data in [("stdout", proc.stdout), ("stderr", proc.stderr)]:
        (where / ("cargo." + label + ".gz")).write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
    c.save(
        where / "invocation.json", dict(argv=list(map(str, actual)), cwd=str(repo), exit=proc.returncode)
    )
    f.require(
        proc.returncode == want, ("unexpected Cargo exit", want, proc.returncode, proc.stderr[-600:])
    )
    return [json.loads(line) for line in proc.stdout.splitlines()]


def roots():
    base.b.fresh_outputs()
    result = {}
    for leaf in ("target", "build"):
        target = work / leaf
        s = target.stat()
        f.require(
            not any(target.iterdir()) and target.resolve(strict=True) == target, "nonempty starting root"
        )
        result[str(target)] = [s.st_dev, s.st_ino, []]
    return result


def store_aliases(where, records):
    paths = {Path(path) for r in records for path in r["filenames"]}
    for line in (where / "trace/exec.tsv").read_text().splitlines():
        v = line.split("\t")
        argv = (where / "trace" / f"args-{int(v[0]):04d}").read_bytes().decode().split("\0")[:-1]
        if v[2] == "1" and v[3] == "1":
            folder = Path(p.ownership.option(argv, "--out-dir"))
            name = p.ownership.option(argv, "--crate-name")
            suffix = [a.split("=", 1)[1] for a in argv if a.startswith("extra-filename=")]
            f.require(
                len(suffix) <= 1 and folder.is_relative_to(work) and ".." not in folder.parts,
                "ambiguous physical product",
            )
            basename = name + "".join(suffix)
            for leaf in (basename, "lib" + basename + ".rmeta", "lib" + basename + ".rlib"):
                path = folder / leaf
                if path.is_file():
                    paths.add(path)
    result = {}
    for path in paths:
        f.require(
            path.is_relative_to(work) and path.resolve(strict=True) == path and path.is_file(),
            "nonregular or redirected product",
        )
        s = path.stat()
        result[str(path.relative_to(work))] = [
            s.st_dev,
            s.st_ino,
            s.st_size,
            s.st_mode,
            s.st_mtime_ns,
            s.st_ctime_ns,
        ]
    c.save(where / "output-inodes.json.gz", result)
    return result


def observe(where, role, mark, rows, binary):
    if role == "cli":
        desc, files = base.native.observed(rows, "B", f.B, base.ENV, root, repo, work, where)
        raw = f.check_output(binary, mark, env=base.ENV, cwd=repo, verify=False)
        c.save(where / "syntax.json.gz", raw)
        f.validate(raw, binary, mark)
        return {k: desc[k] for k in files}, files

    def identity():
        stat = binary.stat()
        return dict(
            path=str(binary),
            sha256=c.sha(binary),
            size=stat.st_size,
            device=stat.st_dev,
            inode=stat.st_ino,
            mode=stat.st_mode,
            mtime_ns=stat.st_mtime_ns,
            ctime_ns=stat.st_ctime_ns,
        )

    before = identity()
    try:
        native = parser_tests.run(binary, repo, mark, base.ENV)
    finally:
        after = identity()
        c.save(where / "test-executable.json", dict(before=before, after=after))
    f.require(before == after, "parser suite used an unstable native executable")
    c.save(where / "test-suite.json.gz", native)
    parser_tests.verify_calls(native, parser_tests.roster(repo), mark, binary, repo)
    return {"fixtures": base.native.elf(binary)}, {"fixtures": binary}


def history(role, tools, topo, selectors, sdk):
    state = "baseline"
    refs = {}
    expected_error = None
    dest = logs / role
    dest.mkdir()
    cmd = p.command(role)
    plan_dir = dest / "plan"
    plan_dir.mkdir()
    (plan_raw,) = invoke(plan_dir, [*cmd[:3], "-Zunstable-options", "--unit-graph", *cmd[3:]], 0)
    plan = p.unitplan(plan_raw, role, repo)
    for lane, phases in p.LANES.items():
        here = dest / lane
        here.mkdir()
        starting = roots()
        for idx, phase in enumerate(phases):
            mark = p.STATE.get(phase, phase)
            p.change(repo, state, mark)
            state = mark
            where = here / phase
            where.mkdir()
            if idx == 0:
                c.save(where / "empty-roots.json", starting)
            before = f.state(repo, mark)
            c.save(where / "source-before.json", before)
            actual = cmd
            if phase == "edited" and lane.startswith("plain-"):
                actual = [tools / "plain", where / "clock.json", *cmd]
            if phase == "edited" and lane == "inventory":
                trace = where / "trace"
                trace.mkdir()
                actual = [
                    tools / "tree",
                    trace,
                    "topology",
                    *[selectors[k][2] for k in topo.ROLES],
                    *cmd,
                ]
            rows = invoke(where, actual, 101 if mark == "invalid" else 0)
            f.require(before == f.state(repo, mark), "Ruff checkout changed inside Cargo")
            c.save(where / "source-after.json", before)
            if mark == "invalid":
                diag = p.error(rows)
                c.save(where / "diagnostic.json", diag)
                if lane == "empty-invalid":
                    expected_error = diag
                else:
                    f.require(
                        diag == expected_error, "warm typed fault vs independently empty diagnostic"
                    )
                continue
            graph, dirty, records, binary = p.graph(rows, role, repo, work)
            p.validate_planned(plan, records)
            if idx == 0:
                f.require(dirty == graph, "fresh roots reused artifacts")
            c.save(where / "roster.json.gz", dict(graph=graph, dirty=dirty))
            if phase == "edited" and lane == "inventory":
                ins = store_aliases(where, records)
                actual_roles = inventory.read(
                    where / "trace", topo, role, repo, work, records, ins, sdk, selectors
                )
                c.save(where / "inventory.json", actual_roles)
            if phase == "edited" and lane.startswith("plain-"):
                instrument.strict_clock(where / "clock.json")
            try:
                desc, files = observe(where, role, mark, rows, binary)
            except Exception:
                # Keep the exact stale or otherwise refused user-facing ELF as well as its raw verdict.
                base.native.preserve(
                    binary,
                    base.native.elf(binary),
                    root / "refusal-bodies",
                    logs / "refused-native-bodies",
                )
                raise
            c.save(where / "elf.json.gz", desc)
            if lane.startswith("empty-"):
                refs[mark] = (graph, desc)
                for k, path in files.items():
                    base.native.preserve(path, desc[k], base.BODIES, logs / "native-bodies")
            else:
                old_graph, old = refs[mark]
                f.require(graph == old_graph and old.keys() == desc.keys(), "native roster vs reference")
                for k, path in files.items():
                    base.native.same_file(path, desc[k], old[k], base.BODIES, where)
            f.require(before == f.state(repo, mark), "native clients changed the checkout")
    p.change(repo, state, "baseline")


def main(collector, contract):
    f.require(
        not any(
            os.environ.get(k)
            for k in ("GH_TOKEN", "GITHUB_TOKEN", "RUSTFLAGS", "RUSTC_WRAPPER", "LD_PRELOAD")
        ),
        "unexpected token or interposition",
    )
    f.require(
        c.read(logs / "enrollment.json")["boot"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "different boot",
    )
    cpu()
    sys.path.insert(0, str(p.HERE.parent / "ruff-repair-tables-pilot"))
    import guards

    guards.admit(guards.resources(work, logs), entry=True)
    base.inputs()
    c.save(logs / "checkout-preflight.json", check_checkout.check(repo))
    base.ruff.git("switch", "-q", "-c", f.BRANCH.split("/")[-1], f.B)
    f.require(
        not f.git(repo, "remote").strip()
        and f.state(repo, "baseline")["source_sha256"] == f.SOURCE_SHA["baseline"],
        "disposable Ruff B",
    )
    c.save(logs / "registered-cases.json", sorted(parser_tests.roster(repo)))
    raw, pmu = instrument.compile_sources(collector, contract, root / "calibrator-source")
    topo = inventory.decoder(raw)
    kit = root / "counter-kit"
    kit.mkdir()
    tools = pmu.compilers(kit)
    pmu.calibration(tools, logs)
    shutil.copytree(tools, logs / "counter-programs")
    gcc = Path(shutil.which("cc", path=base.ENV["PATH"])).resolve(strict=True)
    collect = Path(
        subprocess.check_output([gcc, "-print-prog-name=collect2"], env=base.ENV, text=True).strip()
    ).resolve(strict=True)
    selectors = {
        n: topo.location(path)
        for n, path in zip(
            topo.ROLES, (base.b.SDK / "bin/rustc", gcc, collect, base.b.SDK / base.b.WILD), strict=True
        )
    }
    c.save(logs / "selectors.json", selectors)
    c.save(logs / "selector-sha.json", {k: c.sha(v[2]) for k, v in selectors.items()})
    sdk = c.read(logs / "sdk.json")
    for role in p.ROLES:
        history(role, tools, topo, selectors, sdk)
    f.require(
        acquire.verify_sdk(base.b.SDK) == sdk
        and all(c.sha(v[2]) == c.read(logs / "selector-sha.json")[k] for k, v in selectors.items()),
        "changed subject",
    )
    c.save(logs / "sdk-after.json", sdk)
    c.save(
        logs / "collection.json",
        {"roles": list(p.ROLES), "lanes": p.LANES, "source": f.state(repo, "baseline")},
    )


if __name__ == "__main__":
    try:
        main(*map(Path, sys.argv[1:]))
    except BaseException:
        if logs.is_dir() and not (logs / "refusal.txt").exists():
            (logs / "refusal.txt").write_text(traceback.format_exc())
        raise
