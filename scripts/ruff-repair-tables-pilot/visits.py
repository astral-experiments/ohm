"""Run one registered Cargo visit and reopen its complete typed and native outputs after the counter stops."""

import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "branch-return-pmu"))
import worker as w

assert Path(w.__file__).resolve() == HERE.parent / "branch-return-pmu/worker.py"
sys.path.insert(0, str(HERE))
import check_metadata, guards, namespace, placement, protocol, source_state
import session_tables
import roles as output_roles

P = protocol
need = P.need
sha = lambda value: hashlib.sha256(value).hexdigest()


def parsed(stdout, stderr, expected):
    messages = [json.loads(line) for line in stdout.splitlines()]
    need(
        messages
        and messages[-1] == {"reason": "build-finished", "success": expected == 0}
        and all(m["reason"] != "build-finished" for m in messages[:-1]),
        "missing or duplicate Cargo verdict",
    )
    errors = [m for m in messages if m["reason"] == "compiler-message" and m["message"]["level"] == "error"]
    need(b"internal compiler error" not in stderr.lower() and b"panicked at" not in stderr, "compiler panic")
    if expected:
        tagged = [m for m in errors if m["message"].get("code")]
        need(
            len(tagged) == 1
            and tagged[0]["target"]["name"] == "ruff_python_parser"
            and tagged[0]["message"]["code"]["code"] == "E0308"
            and tagged[0]["message"]["message"] == "mismatched types"
            and any(
                s["is_primary"]
                and s["file_name"] == source_state.PARSER
                and s["line_start"] == 626
                and any(t["text"].strip() == source_state.BAD.decode().strip() for t in s["text"])
                for s in tagged[0]["message"]["spans"]
            )
            and all(
                m in tagged
                or (
                    not m["message"]["spans"]
                    and m["message"]["message"].startswith("aborting due to 1 previous error")
                )
                for m in errors
            ),
            "wrong real diagnostic, unit, source or line",
        )
    else:
        need(not errors, "error returned with successful Cargo")
    return messages


def physical(rows, phase, cargo):
    need(
        rows["cargos"][0]["argv"][1:] == cargo[2:],
        "trace did not execute the registered physical Cargo command",
    )
    full = []
    link = []
    for row in rows["rustcs"]:
        args = row["argv"]
        operands = [a for a in args if not a.startswith("-") and a.endswith((".rlink", ".rs"))]
        need(
            len(operands) == 1 and (row["mode"] == "link-only") == operands[0].endswith(".rlink"),
            "source/relink mode inconsistent",
        )
        (link if row["mode"] == "link-only" else full).append(row["crate"])
    if "invalid" in phase:
        need(
            full == ["ruff_python_parser"] and not link and not rows["wild"], "different invalid native stage"
        )
    elif phase not in ("stage-build", "stage-check"):
        if phase in ("first-B", "donor-A", "donor-B", *P.RETURNS):
            want = (20, 0)
        elif phase in ("unchanged-B", "private-repeat-B"):
            want = (0, 1)
        elif phase in ("verify-private-B", "private-restore-B", "private-UP035-B"):
            want = (2, 0)
        elif phase in ("stage-repair", "verify-repair", "repair"):
            want = (16, 0)
        else:
            raise ValueError(("unregistered traced phase", phase))
        need(
            (len(full), len(link)) == want
            and rows["wild"] == 1
            and all(n == "ruff" for n in link)
            and (not full or "ruff" in full)
            and (want != (2, 0) or set(full) == {"ruff", "ruff_linter"}),
            "physical warm compiler/link roster did not recur",
        )
    return {
        "full": sorted(full),
        "link_only": sorted(link),
        "wild": [r["output"] for r in rows["wild_processes"]],
        "other_linkers": rows["other_linkers"],
    }


def invoke(where, env, method, expected, arm, phase, observer):
    cmd = P.CHECK if phase in ("stage-check", "clean-check-B") else P.COMMAND
    if method == "measured":
        outer = [str(w.OUT / "observers/plain"), str(where / "clock.json"), *cmd]
    elif method == "trace" and phase == "verify-repair":
        outer = [
            "strace",
            "-f",
            "-qq",
            "--seccomp-bpf",
            "-yy",
            "-s",
            "262144",
            "-e",
            "trace=execve,execveat,openat,openat2,flock",
            "-o",
            str(where / "exec.raw"),
            *cmd,
        ]
    elif method == "trace":
        outer = [
            "strace",
            "-f",
            "-qq",
            "--seccomp-bpf",
            "-s",
            "262144",
            "-e",
            "trace=execve,execveat",
            "-o",
            str(where / "exec.raw"),
            *cmd,
        ]
    elif method == "peak":
        outer = namespace.command(cmd, w, env, where, observer)
    else:
        need(method == "plain", "invalid observation")
        outer = cmd
    w.publish(
        where / "intent.json.gz",
        dict(
            argv=cmd,
            launch=list(map(str, outer)),
            expected=expected,
            cwd=str(w.kit.TREE),
            env=env,
            method=method,
        ),
    )
    rc = guards.run(outer, w.kit.TREE, env, where, w.WORK, w.OUT)
    stdout, stderr = [(where / ("outer." + k)).read_bytes() for k in ("stdout", "stderr")]
    for key, data in (("stdout", stdout), ("stderr", stderr)):
        (where / ("cargo." + key + ".gz")).write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
        (where / ("outer." + key)).unlink()
    w.save(where / "command.json", dict(status=rc, stdout_sha256=sha(stdout), stderr_sha256=sha(stderr)))
    need(rc == expected, ("wrong Cargo/observer exit", where, expected, rc, stderr[-1400:]))
    native = None
    if method == "trace":
        try:
            observed = w.processes.inventory(where / "exec.raw", arm)
            w.publish(where / "native-execs.json.gz", observed)
            native = physical(observed, phase, cmd)
        finally:
            w.processes.compact(where / "exec.raw", where / "exec.raw.gz")
    n = None
    if method == "measured":
        clock = w.clock(where / "clock.json", rc)
        need(
            clock["enabled"] == clock["running"],
            ("counter did not cover the complete inherited interval", clock),
        )
        n = clock["instructions"]
    return parsed(stdout, stderr, expected), n, native


def up035(cli, env, where, edited):
    out = {}
    for symbol, want in (("no_type_check", True), ("no_type_check_decorator", edited)):
        args = [
            cli,
            "check",
            "--isolated",
            "--no-cache",
            "--select",
            "UP035",
            "--target-version",
            "py312",
            "--output-format",
            "json",
            "-",
        ]
        p = w.native.run(
            args,
            env,
            w.kit.TREE,
            where / ("up035-" + symbol),
            int(want),
            ("from typing_extensions import " + symbol + "\n").encode(),
        )
        d = json.loads(p.stdout)
        need(
            len(d) == int(want)
            and not p.stderr
            and (
                not want
                or d[0]["code"] == "UP035"
                and d[0]["fix"]["edits"][0]["content"] == "from typing import " + symbol
            ),
            "real changed UP035 behavior failed",
        )
        out[symbol] = [p.returncode, sha(p.stdout), sha(p.stderr)]
    return out


def visit(phase, arm, env, where, method, state, observer, refs, *, reference=False):
    where.mkdir()
    ischeck = phase in ("stage-check", "clean-check-B")
    branch = P.branch(phase)
    kind = P.state(phase)
    key = (arm, branch, "check" if ischeck else kind)
    if phase.endswith("repair") or phase == "repair":
        before = w.failed_session.observed(w.WORK)
        need(before and state.get("failed") == before, "wrong or vanished preceding genuine failed session")
        w.failed_session.before_repair(w.WORK, before, where / "failed-session-grace.json")
    src = source_state.select(w.kit.TREE, w.kit.NAMES, w.kit.REVS, w.kit.TREES, branch, kind)
    w.save(where / "source.json", src)
    rc = 101 if kind == "invalid" else 0
    held = None
    if state.get("physical_tables") and phase in ("repair", "verify-repair"):
        held = placement.donor_capture(state["last"], w.WORK, state["version"], session_tables)
        w.publish(where / "before-donors.json.gz", held)
    messages, insn, phys = invoke(where, env, method, rc, arm, phase, observer)
    dom = w.failed_session.observed(w.WORK)
    need(bool(dom) == bool(rc), ("incorrect failed-session inventory", phase, dom))
    state["failed"] = dom
    if dom:
        w.save(where / "working.json", dom)
    space = w.disk.allocated(w.WORK / "target", w.WORK / "build", where, failed_sessions=dom)
    need(min(space["roots"].values()) > 0 and space["all_inodes"] > 1000, "short native allocation inventory")
    result = {
        "phase": phase,
        "method": method,
        "arm": arm,
        "rc": rc,
        "source": src,
        "allocated": space["allocated"],
        "instructions": insn,
        "native_execs": phys,
    }
    if method == "peak":
        with gzip.open(where / "peak.json.gz", "rt") as stream:
            obs = json.load(stream)
        need(
            obs["argv"] == P.COMMAND
            and obs["exit"] == 0
            and obs["after"]["allocated"] == space["allocated"]
            and len(obs["samples"]) >= 3
            and obs["reaped"][str(obs["main_pid"])] == 0
            and obs["outside_namespace"] != obs["namespace"]
            and max(r["runnable_window_ns"] for r in obs["samples"]) <= 500_000_000
            and all(n > 0 for n in (obs["pss_peak"], obs["rss_peak"], len(obs["lifetime_sampled_max"])))
            and any(len(r["processes"]) >= 2 for r in obs["samples"]),
            "unqualified sampled high-water or storage disagreement",
        )
        result["peak"] = {
            k: obs[k]
            for k in (
                "allocated_including_deleted_peak",
                "allocated_peak",
                "pss_peak",
                "pss_anon_peak",
                "rss_peak",
            )
        }
        coverage = obs["sampled_deleted_accounting_complete"]
        unresolved = [m for r in obs["samples"] for m in r["unresolved_deleted_maps"]]
        need(coverage == (not unresolved), "inconsistent sampler coverage")
        duplicate_pairs = max(
            sum(
                any(
                    dict(f).get(n, 0) > 0 and dict(f).get("ohm-packed-" + n, 0) > 0
                    for n in ("dep-graph.bin", "query-cache.bin")
                )
                for f in r["working_tables"].values()
            )
            for r in obs["samples"]
        )
        result["peak"].update(
            all_deleted_mappings_accounted=coverage,
            unresolved_deleted_mapping_ids=sorted({(m[0], m[1]) for m in unresolved}),
            max_working_table_pairs_observed=duplicate_pairs,
            model="sampled maxima; lower bounds on actual transient peaks",
            max_unpaused_ns=max(r["runnable_window_ns"] for r in obs["samples"]),
            max_simultaneous_private_sessions=max(len(r["working_tables"]) for r in obs["samples"]),
            snapshots=len(obs["samples"]),
        )
    if state.get("physical_tables"):
        ledger = w.historical.load(where / "path-inodes.json.gz")
        traces = None
        if phase == "verify-repair":
            with gzip.open(where / "exec.raw.gz", "rt") as stream:
                traces = placement.returned(stream)
        state["last"] = placement.inspect(
            state.get("last"),
            ledger,
            where,
            w.WORK,
            state["version"],
            arm,
            phase,
            session_tables,
            messages,
            held,
            traces,
        )
    allocation = output_roles.artifacts(messages, w.WORK, w.kit.TREE)
    w.publish(where / "output-roles.json.gz", allocation)
    result["output_roles"] = w.historical.commit(allocation)
    if rc:
        w.save(where / "visit.json", result)
        return result
    if ischeck:
        checked = check_metadata.verdict(w, messages, env, where)
        checked["output_roles"] = result["output_roles"]
        w.publish(where / "checked.json.gz", checked)
        if reference:
            refs[key] = checked
        else:
            check_metadata.equivalent(checked, refs[key])
        result.update(
            checked=len(checked["graph"]), providers={n: v["sha256"] for n, v in checked["providers"].items()}
        )
    else:
        rows, dirty = w.historical.roster(messages)
        if phase.startswith("clean-") or phase == "single-source-B":
            expected = 375
        else:
            expected = P.EXPECT.get(phase)
        if expected is not None:
            need(len(dirty) == expected, ("wrong dirty compiler units", phase, len(dirty), expected))
        if phase in ("first-B", "donor-A", "donor-B", *P.RETURNS):
            need(w.historical.commit(dirty) == w.settled_link.SWITCH_DIRTY, "foreign branch-change unit set")
        if phase in ("unchanged-B", "private-repeat-B", "single-repeat-B", "adjacent-unchanged-B"):
            w.settled_link.sole_bin(dirty)
        if expected == 7:
            need(
                {u["name"] for u in dirty}
                == {"ruff_linter", "ruff_graph", "ruff_workspace", "ruff_markdown", "ruff_server", "ruff"},
                "different UP035 dependents",
            )
        w.publish(where / "roster.json.gz", dict(members=rows, dirty=dirty))
        products, files = w.native.observed(
            messages, branch, w.kit.REVS[branch], env, w.ROOT, w.kit.TREE, w.WORK, where
        )
        extra = up035(files["cli"], env, where, kind == "private")
        jem = w.historical.stable_sdk.output_directory(messages, "tikv-jemalloc-sys")
        if reference:
            for name, path in files.items():
                w.native.preserve(path, products[name], w.BODIES, w.BUNDLE)
            refs[key] = {
                "typed": rows,
                "products": products,
                "jemalloc": jem,
                "up035": extra,
                "output_roles": result["output_roles"],
            }
        else:
            clean = refs[key]
            need(
                rows == clean["typed"]
                and w.same_products(products, clean["products"])
                and jem == clean["jemalloc"]
                and extra == clean["up035"]
                and result["output_roles"] == clean["output_roles"],
                "native runtime, CLI, graph or source path diverged from own empty",
            )
            for name, path in files.items():
                w.native.same_file(path, products[name], clean["products"][name], w.BODIES, where)
        result.update(
            graph=w.historical.commit(rows),
            dirty=len(dirty),
            dirty_digest=w.historical.commit(dirty),
            cli=products["cli"]["whole"],
            reader=products["reader"]["whole"],
            native_output=jem,
            up035=extra,
        )
    w.save(where / "visit.json", result)
    return result
