"""Run nine ordinary Cargo builds on a single verified E or C installation."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as s

sys.path.insert(0, str(HERE.parent / "ctfe-crossover-pilot"))
import pilot as p

BRANCH = "charlie/qa-ctfe-cli-semantic-20261101"


def admission():
    e = os.environ
    s.need(
        e["GITHUB_REPOSITORY"] == p.b.REPO
        and e["GITHUB_REF"] == "refs/heads/" + BRANCH
        and e["GITHUB_RUN_ATTEMPT"] == "1"
        and e["GITHUB_SHA"] == e["REVIEWED_HEAD"] == p.b.git(HERE, "rev-parse", "HEAD")
        and p.ROOT.resolve() == p.ROOT
        and (p.WORK / ".owned-by-packed-study").read_text() == str(p.ROOT),
        "unreviewed source or unowned working root",
    )


def fresh(where, env):
    paths = s.roots(env, p.ROOT)
    s.physical_roots(paths, empty=False)
    p.b.fresh_outputs()
    report = s.physical_roots(paths, empty=True)
    p.save(where / "fresh.json", report)


def observe_stub(file, env, where, edited):
    results = {}
    bad = []
    for case in s.CASES:
        # Keep every actual exit, even when one of the registered semantic alternatives fails.
        argv = [str(file), *s.argv(case)]
        cmd = subprocess.run(argv, input=s.SOURCE, capture_output=True, cwd=p.kit.TREE, env=env, timeout=30)
        for key, raw in (("stdout", cmd.stdout), ("stderr", cmd.stderr)):
            (where / f"stub-{case}.{key}.gz").write_bytes(gzip.compress(raw, mtime=0))
        receipt = dict(
            argv=argv,
            cwd=str(p.kit.TREE),
            exit=cmd.returncode,
            stdin_sha256=s.sha(s.SOURCE),
            stdout_sha256=s.sha(cmd.stdout),
            stderr_sha256=s.sha(cmd.stderr),
        )
        p.save(where / f"stub-{case}.json", receipt)
        try:
            results[case] = s.verdict(case, edited, cmd.returncode, cmd.stdout, cmd.stderr, p.kit.TREE)
        except ValueError as error:
            bad.append(str(error))
    s.need(not bad, bad)
    return results


def link_owner(phase, where, observed, cli, cli_hash, arm):
    cert = json.loads((where.parent / "arm.json").read_bytes())
    r, w = s.link_rows(observed["rustcs"], observed["wild_processes"], cli, p.b.SDK, phase)
    actual = Path(w["output"])
    s.require_same_output(cli, actual, cli_hash)
    s.need(p.sha(p.b.SDK / s.WILD) == s.WILD_SHA and cert["arm"] == arm, "wrong physical stock linker")
    # numbers() returns dev, ino, mode bits, size, mtime, ctime.
    record = dict(
        rustc=r["pid"],
        wild=w["pid"],
        output=str(actual),
        reported=str(cli),
        output_identity=p.b.numbers(actual),
        reported_identity=p.b.numbers(cli),
        stock=cert["files"][s.WILD],
        whole=cli_hash,
    )
    p.save(where / "link-owner.json", record)
    return record


def run(arm):
    s.need(
        arm in ("Eon", "Con") and shutil.disk_usage(p.WORK).free > 20 * 2**30,
        "foreign role or insufficient cold capacity",
    )
    rows = {role: json.loads((p.OUT / "sdk" / (role + ".json")).read_bytes())["files"] for role in ("E", "C")}
    top = p.OUT / "visits"
    top.mkdir()
    env = p.subjects.activate(arm, rows, top)
    s.roots(env, p.ROOT)
    p.b.prepare_inputs(p.kit, env)
    source_preflight = subprocess.check_output([sys.executable, "-IB", HERE / "test.py", "--repo", p.kit.TREE])
    p.save(p.OUT / "history-preflight.json", json.loads(source_preflight))
    p.routes.begin(p.kit.TREE, p.kit.REVS, p.kit.NAMES)
    p.save(
        p.OUT / "enrollment.json",
        dict(
            arm=arm,
            head=os.environ["GITHUB_SHA"],
            run=int(os.environ["GITHUB_RUN_ID"]),
            attempt=1,
            job=os.environ["GITHUB_JOB"],
            runner=os.environ["RUNNER_NAME"],
            boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            plan=p.sha(HERE / "PLAN.md"),
            phases=s.PHASES,
            command=p.original.CARGO,
        ),
    )
    sources = p.OUT / "source-files"
    sources.mkdir()
    results = {}
    products = {}
    for phase in s.PHASES:
        where = top / phase
        where.mkdir()
        if phase in s.COLD:
            fresh(where, env)
        if phase == "repair":
            previous = json.loads((top / "invalid/failed.json").read_bytes())
            p.original.failed_session.before_repair(p.WORK, previous, where / "grace.json")
        s.advance(p.kit.TREE, phase)
        source = s.snapshot(p.kit.TREE, phase)
        s.check_source(source, phase)
        p.save(where / "source.json", source)
        for path in (s.AST, s.PARSER):
            data = (p.kit.TREE / path).read_bytes()
            dst = sources / s.sha(data)
            if not dst.exists():
                dst.write_bytes(data)
            s.need(dst.read_bytes() == data, "retained source differs")
        if phase == "repeat":
            s.need(source == json.loads((top / "edit/source.json").read_bytes()), "repeat changed source")
        status = 101 if phase == "invalid" else 0
        obs = "structural" if phase in s.LINKED else "ordinary"
        messages, count, physical = p.original.invocation(where, env, obs, status, arm)
        s.need(count is None and ((physical is not None) == (phase in s.LINKED)), "unexpected observer")
        failed = p.original.failed_session.observed(p.WORK)
        rec = dict(phase=phase, status=status, observer=obs)
        if status:
            p.save(where / "failed.json", failed)
        else:
            s.need(not failed, "open failed state after successful Cargo")
            roster, dirty = p.original.historical.roster(messages)
            p.publish(where / "roster.json.gz", dict(members=roster, dirty=dirty))
            rec.update(graph=p.original.historical.commit(roster), dirty=p.original.historical.commit(dirty))
            s.need(
                rec["graph"] == s.GRAPH and (phase not in s.COLD or len(dirty) == 375),
                "false graph or false cold",
            )
            branch = source["branch"]
            native, files = p.original.native.observed(
                messages, branch, s.REVS[branch], env, p.ROOT, p.kit.TREE, p.WORK, where
            )
            for name, file in files.items():
                p.original.native.preserve(file, native[name], p.original.BODIES, p.original.BUNDLE)
            if physical is not None:
                link_owner(phase, where, physical, files["cli"], native["cli"]["whole"], arm)
            rec["stub"] = observe_stub(files["cli"], env, where, phase in s.EDITED)
            rec.update(cli=native["cli"]["whole"], reader=native["reader"]["whole"])
            products[phase] = native
        p.save(where / "visit.json", rec)
        results[phase] = rec
        print(arm, phase, status, rec.get("cli"), flush=True)
    for phase in ("X-B", "revert", "edit", "repeat", "repair"):
        witness = "empty-edit" if phase in s.EDITED else "Y-B"
        s.need(
            products[phase] == products[witness] and results[phase]["stub"] == results[witness]["stub"],
            ("complete native outputs differ at the same physical path", phase, witness),
        )
    s.need(
        results["edit"]["cli"] != results["Y-B"]["cli"] and results["X-A"]["cli"] != results["Y-B"]["cli"],
        "real changed program did not change",
    )
    s.need(
        p.b.inventory(p.b.SDK) == rows[arm[0]]
        and p.b.inventory(p.b.PARK / ("C" if arm == "Eon" else "E")) == rows["C" if arm == "Eon" else "E"],
        "SDK changed during fixture",
    )
    p.save(p.OUT / "complete.json", dict(arm=arm, phases=s.PHASES, qualification="unscored-native-correctness"))


if __name__ == "__main__":
    try:
        admission()
        if sys.argv[1] == "acquire":
            p.subjects.acquire(Path(sys.argv[2]))
        else:
            run(sys.argv[1])
    except BaseException:
        if p.OUT.is_dir():
            (p.OUT / "failure.txt").write_text(traceback.format_exc())
        raise
