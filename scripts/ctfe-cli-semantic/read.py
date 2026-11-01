"""Reopen both original unscored worker ZIPs from an independently obtained Actions catalog."""

import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ctfe-crossover-pilot")]
import cases as s
import exercise
import reopen as old

BRANCH = "charlie/qa-ctfe-cli-semantic-20261101"
ARM = ("Eon", "Con")
STEPS = (
    "Reconstruct both 81-file compiler installations using original source artifacts",
    "Build the real edit, repair, revert, and independent empty at the same paths",
)
need = s.need
data = old.dataset
raw = old.replay_native.raw


def cargo_roots(events, root):
    bins = []
    for event in events:
        if event["reason"] not in ("compiler-artifact", "build-script-executed"):
            continue
        paths = event.get("filenames", []) + [p for p in (event.get("executable"), event.get("out_dir")) if p]
        for spelling in paths:
            path = PurePosixPath(spelling)
            need(
                str(path) == spelling
                and ".." not in path.parts
                and any(path.is_relative_to(root / "work" / n) for n in ("target", "build")),
                "foreign Cargo artifact",
            )
        if (
            event["reason"] == "compiler-artifact"
            and event["target"]["name"] == "ruff"
            and event["target"]["kind"] == ["bin"]
        ):
            bins.append(event["executable"])
    need(bins == [str(root / "work/target/debug/ruff")], "different binary owner")
    return bins[0]


def exec_records(text):
    """Retain literal argv and PID only for complete, successful execve calls."""
    pending = {}
    result = []
    for line in text.splitlines():
        first = re.fullmatch(r"(\d+)\s+(execve\(.*)", line)
        tail = re.fullmatch(r"(\d+)\s+<\.\.\. execve resumed>(.*)", line)
        if tail:
            pid = int(tail[1])
            need(pid in pending, "unmatched resumed execve")
            call = pending.pop(pid) + tail[2]
        elif first:
            pid, call = int(first[1]), first[2]
            need(pid not in pending, "concurrent execve with same PID")
        else:
            need(not re.search(r"\bexecve(?:at)?(?:\(| resumed>)", line), "unclassified exec")
            continue
        if call.endswith("<unfinished ...>"):
            pending[pid] = call.removesuffix("<unfinished ...>").rstrip()
        elif re.search(r"\)\s+= -1 [A-Z0-9]+(?: \(.*\))?$", call):
            continue
        else:
            m = re.fullmatch(r'execve\(("(?:\\.|[^"])*"), (\[.*\]), .*\)\s+= 0', call)
            need(m, "incomplete or opaque execve")
            exe, args = (ast.literal_eval(x) for x in m.groups())
            need(
                type(exe) is str and type(args) is list and args and all(type(v) is str for v in args),
                "truncated argv",
            )
            result.append((pid, exe, args))
    need(not pending, "unclosed execve")
    return result


def link(z, prefix, phase, cert, root, cmd, cli, native):
    sdk = PurePosixPath(cert["sdk"])
    argv = [
        "strace",
        "-f",
        "-qq",
        "--seccomp-bpf",
        "-s",
        "262144",
        "-e",
        "trace=execve,execveat",
        "-o",
        str(root / "logs" / prefix / "exec.raw"),
        *old.CARGO,
    ]
    need(cmd["observer_argv"] == argv, "wrong native trace invocation")
    events = exec_records(raw(z, prefix, "exec.raw.gz").decode())
    phys = data(z, prefix + "/native-execs.json.gz")
    rustcs, wilds, cargos = [], [], []
    for pid, exe, args in events:
        if (
            exe == str(sdk / "bin/rustc")
            and "--crate-name" in args
            and not any(a.startswith("--print") for a in args)
        ):
            mode = (
                "link-only"
                if any(
                    v in ("link-only", "ohm-link-only") or v.startswith(("link-only=", "-Zlink-only"))
                    for v in args
                )
                else "full"
            )
            rustcs.append(dict(pid=pid, exe=exe, argv=args, mode=mode, crate=s.flag(args, "--crate-name")))
        if exe == str(sdk / s.WILD) and "-o" in args:
            wilds.append(dict(pid=pid, exe=exe, argv=args, output=s.flag(args, "-o")))
        if exe == str(sdk / "bin/cargo") and args[1:] == old.CARGO[2:]:
            cargos.append(dict(pid=pid, exe=exe, argv=args))
    need(
        phys["rustcs"] == rustcs
        and phys["wild_processes"] == wilds
        and phys["wild"] == len(wilds)
        and phys["cargos"] == cargos
        and len(cargos) == phys["real_cargo"] == 1
        and phys["successful_exec_count"] == len(events),
        "kernel trace differs from the successful Cargo/compiler/link rows",
    )
    for row in rustcs:
        if row["crate"] in ("ruff", "ruff_python_ast", "ruff_python_parser"):
            need(
                any(v in ("-Zohm-branch-cache=yes", "ohm-branch-cache=yes") for v in row["argv"])
                and any("ohm-check-relink-inputs" in v for v in row["argv"]),
                "incorrect physical compiler flags",
            )
    r, w = s.link_rows(rustcs, wilds, cli, sdk, phase)
    need(not any(e["output"] == w["output"] for e in phys["other_linkers"]), "ambiguous native output writer")
    linker_names = {"ld", "ld.bfd", "ld.lld", "ld.gold", "wild", "mold", "rust-lld"}
    need(
        not any(
            PurePosixPath(exe).name in linker_names
            and exe != str(sdk / s.WILD)
            and "-o" in args
            and s.flag(args, "-o") == w["output"]
            for _, exe, args in events
        ),
        "another native linker wrote the CLI",
    )
    receipt = data(z, prefix + "/link-owner.json")
    identity = receipt["reported_identity"]
    need(
        receipt
        == dict(
            rustc=r["pid"],
            wild=w["pid"],
            output=w["output"],
            reported=cli,
            output_identity=identity,
            reported_identity=identity,
            stock=cert["files"][s.WILD],
            whole=native["cli"]["whole"],
        )
        and cert["files"][s.WILD][0] == s.WILD_SHA
        and len(identity) == 6
        and all(type(v) is int and v > 0 for v in identity)
        and identity[2] & 0o111
        and identity[3] == native["cli"]["size"],
        "Wild did not own the complete reported CLI",
    )
    return dict(
        rustc=r["pid"],
        mode=r["mode"],
        wild=w["pid"],
        rustcs=[[x["crate"], x["mode"]] for x in rustcs],
        stock_writes=len(wilds),
        output=w["output"],
    )


def stub(z, prefix, phase, cli, cwd):
    result = {}
    for case in s.CASES:
        label = "stub-" + case
        rec = data(z, prefix + "/" + label + ".json")
        out, err = (raw(z, prefix, label + "." + ext + ".gz") for ext in ("stdout", "stderr"))
        need(
            rec
            == dict(
                argv=[cli, *s.argv(case)],
                cwd=cwd,
                exit=rec["exit"],
                stdin_sha256=s.sha(s.SOURCE),
                stdout_sha256=s.sha(out),
                stderr_sha256=s.sha(err),
            ),
            "unbound native stub command",
        )
        result[case] = s.verdict(case, phase in s.EDITED, rec["exit"], out, err, cwd)
    return result


def parser_error(z, prefix, events):
    errors = [e for e in events if e["reason"] == "compiler-message" and e["message"]["level"] == "error"]
    tagged = [e for e in errors if e["message"]["code"]]
    need(
        errors == data(z, prefix + "/diagnostics.json.gz")
        and tagged
        and all(
            e["target"]["name"] == "ruff_python_parser"
            and e["message"]["code"]["code"] == "E0308"
            and any(
                span["is_primary"]
                and span["file_name"] == s.PARSER
                and span["line_start"] == 626
                and any("ohm_branch_switch_invalid" in t["text"] for t in span["text"])
                for span in e["message"]["spans"]
            )
            for e in tagged
        ),
        "different compiler error",
    )
    for e in errors:
        if not e["message"]["code"]:
            need(
                not e["message"]["spans"] and e["message"]["message"].startswith("aborting due to "),
                "additional error",
            )


def visit(z, phase, cert, root, bodies):
    pre = "visits/" + phase
    source, cmd, rec = (data(z, pre + "/" + k) for k in ("source.json", "cargo.json.gz", "visit.json"))
    s.check_source(source, phase)
    expected = 101 if phase == "invalid" else 0
    need(
        rec["phase"] == phase
        and rec["status"] == expected == cmd["expected"]
        and cmd["env"] == cert["env"]
        and cmd["cwd"] == str(root / "ruff")
        and cmd["stdin_sha256"] == s.sha(b""),
        "wrong source/env/Cargo",
    )
    out, err = (raw(z, pre, "cargo." + k + ".gz") for k in ("stdout", "stderr"))
    roster = old.metrics.cargo_messages(out, err, cmd, expected, cmd["cwd"])
    events = [json.loads(line) for line in out.splitlines()]
    traced = phase in s.LINKED
    need(
        rec["observer"] == ("structural" if traced else "ordinary")
        and (cmd["observer_argv"] is not None) == traced,
        "incorrect instrumentation scope",
    )
    for file in ("exec.raw.gz", "native-execs.json.gz", "link-owner.json"):
        need((pre + "/" + file in z.NameToInfo) == traced, "missing or unexpected native trace")
    if phase in s.COLD:
        fresh = data(z, pre + "/fresh.json")
        need(
            set(fresh) == {str(root / "work" / r) for r in ("target", "build")}
            and len({tuple(v) for v in fresh.values()}) == 2
            and all(len(v) == 2 and all(type(n) is int and n > 0 for n in v) for v in fresh.values()),
            "same or unowned empty roots",
        )
    if not roster:
        parser_error(z, pre, events)
        need(
            not any(n.startswith(pre + "/stub-") or n == pre + "/native.json.gz" for n in z.namelist()),
            "executed after failed build",
        )
        return dict(source=source, status=101)
    need(
        roster == data(z, pre + "/roster.json.gz")
        and old.compact(roster["members"]) == rec["graph"] == s.GRAPH
        and old.compact(roster["dirty"]) == rec["dirty"]
        and (phase not in s.COLD or len(roster["dirty"]) == 375),
        "wrong graph or false empty",
    )
    cli = cargo_roots(events, root)
    native = old.replay_native.native_verdict(z, pre, source["branch"])
    old.typed_inputs(z, pre, out, root)
    for name in ("cli", "reader"):
        need(native[name]["whole"] == rec[name], "unbound native product")
        old.verified_body(z, name, native[name], bodies)
    verdicts = stub(z, pre, phase, cli, cmd["cwd"])
    need(verdicts == rec["stub"], "unmatched native CLI cases")
    positive = link(z, pre, phase, cert, root, cmd, cli, native) if traced else None
    return dict(
        source=source, status=0, native=native, stub=verdicts, dirty=len(roster["dirty"]), positive=positive
    )


def same_history(states):
    need(
        set(states) == set(s.PHASES) and states["repeat"]["source"] == states["edit"]["source"],
        "missing visits or changed repeat",
    )
    for phase in ("X-B", "revert", "edit", "repeat", "repair"):
        base = states["empty-edit" if phase in s.EDITED else "Y-B"]
        need(
            states[phase]["native"] == base["native"] and states[phase]["stub"] == base["stub"],
            ("warm executable, typed reader, or behavior differs from its independent empty", phase),
        )
    need(
        states["edit"]["native"]["cli"]["whole"]
        != states["Y-B"]["native"]["cli"]["whole"]
        != states["X-A"]["native"]["cli"]["whole"],
        "historical or semantic source did not change CLI bytes",
    )


def worker(path, arm):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        need(
            len(names) == len(set(names))
            and all(
                not PurePosixPath(n).is_absolute()
                and ".." not in PurePosixPath(n).parts
                and not n.endswith(("/clock.json", "/kernel.tsv.gz"))
                for n in names
            ),
            "unsafe archive or timed workload",
        )
        en = data(z, "enrollment.json")
        need(
            en["arm"] == arm
            and en["command"] == old.CARGO
            and en["phases"] == list(s.PHASES)
            and en["job"] == "semantic"
            and en["attempt"] == 1
            and re.fullmatch(r"[a-f0-9-]{36}", en["boot"])
            and en["runner"]
            and en["plan"] == s.sha((HERE / "PLAN.md").read_bytes()),
            "wrong worker or plan",
        )
        need(
            data(z, "complete.json")
            == dict(arm=arm, phases=list(s.PHASES), qualification="unscored-native-correctness")
            and "failure.txt" not in names,
            "incomplete native worker",
        )
        corpus = data(z, "ruff-inputs.json")
        need(
            corpus["commits"] == s.REVS
            and corpus["trees"] == s.TREES
            and corpus["lock"] == old.corpus.LOCK
            and old.compact(corpus["archives"])
            == "cd586cd0fe2b3b6b6529b6c8d8f157164073edc3b4e24f09b0ac5be88897193c"
            and old.compact(corpus["changed"])
            == "715155d874b322001e381f12dc398185f64584054878046de4d8568da01928ea",
            "different historical edit or registry",
        )
        original, edited, good, invalid = (
            z.read("source-files/" + h) for h in (s.BEFORE, s.AFTER, s.GOOD, s.BAD)
        )
        need(
            s.altered(original) == edited
            and s.sha(good) == s.GOOD
            and good + s.INVALID == invalid
            and s.sha(invalid) == s.BAD,
            "wrong semantic edit or broken parser source",
        )
        prior_receipts = {
            "sdk/ctfe-official.json": "6185b04d8df7d4a1bc3b174608389ac25d3b2bc99791bcc9bd5c4edd528c1957",
            "sdk/ctfe-native-source.json": "4209d84bd5f48e959e64b623ada78f9904c8f2c40a5ba1223049e45f984d0f6d",
        }
        need(
            all(s.sha(z.read(n)) == h for n, h in prior_receipts.items()),
            "wrong source qualification or prior refusal",
        )
        guard = data(z, "resource/resources.json")
        need(
            guard["exit"] == 0
            and guard["refusal"] is None
            and all(
                guard["minimum"][k] >= g * (1 << 30)
                for k, g in (("work", 4), ("receipts", 6), ("effective", 8))
            ),
            "resource guard refused native workload",
        )
        source_probe = data(z, "history-preflight.json")["source"]
        need(
            source_probe
            == {p: {k: s.source_state(p)[k] for k in ("ast", "parser", "modified")} for p in s.PHASES},
            "separate source rehearsal did not match the registered history",
        )
        pair = old.sdk_pair(z)
        cert, root = old.active(z, "visits", arm, pair[arm[0]]["files"])
        s.roots(cert["env"], root)
        bodies = {}
        states = {p: visit(z, p, cert, root, bodies) for p in s.PHASES}
        same_history(states)
        replayed = {}
        for phase in s.PHASES:
            row = states[phase]
            if phase == "invalid":
                continue
            key = row["native"]["cli"]["whole"], phase in s.EDITED
            if key not in replayed:
                replayed[key] = exercise.replay(z, row["native"], row["source"]["revision"], key[1])
            need(
                replayed[key] == {case: value[0] for case, value in row["stub"].items()},
                "different native rerun",
            )
        need(
            {n for n in names if n.startswith("native-bodies/") and not n.endswith("/")}
            == {"native-bodies/" + h + ".zst" for _, h in bodies},
            "extra or absent complete native ELF",
        )
        grace = data(z, "visits/repair/grace.json")
        need(
            data(z, "visits/invalid/failed.json") == grace["sessions"]
            and grace["ready_ns"] >= grace["cutoff_ns"]
            and grace["rustc_gc_grace_ns"] == 10_000_000_000,
            "different or active failed session at repair",
        )
        return en, str(root), states


def official(folder, run_id, head, files):
    fetch = lambda n: json.loads((folder / (n + ".json")).read_bytes())
    run, jobs, assets = (fetch(n) for n in ("run", "jobs", "artifacts"))
    need(
        run["id"] == run_id
        and run["head_sha"] == head
        and run["run_attempt"] == 1
        and run["event"] == "workflow_dispatch"
        and run["repository"]["full_name"] == "astral-experiments/ohm"
        and run["path"] == ".github/workflows/ci.yml"
        and run["head_branch"] == BRANCH
        and run["status"] == "completed"
        and run["conclusion"] == "success"
        and jobs["total_count"] == len(jobs["jobs"]) == assets["total_count"] == len(assets["artifacts"]) == 2,
        "wrong official run or incomplete catalog",
    )
    hosts = {}
    for arm, file in zip(ARM, files, strict=True):
        (job,) = [j for j in jobs["jobs"] if j["name"] == "Verify Ruff file classification " + arm]
        (asset,) = [a for a in assets["artifacts"] if a["name"] == "ctfe-cli-semantic-" + arm]
        need(
            job["run_id"] == run_id
            and job["run_attempt"] == 1
            and job["head_sha"] == head
            and job["status"] == "completed"
            and job["conclusion"] == "success"
            and all(
                any(
                    st["name"] == name and st["conclusion"] == "success" and st["status"] == "completed"
                    for st in job["steps"]
                )
                for name in STEPS
            )
            and asset["workflow_run"]["id"] == run_id
            and asset["workflow_run"]["head_sha"] == head
            and not asset["expired"]
            and asset["size_in_bytes"] == file.stat().st_size,
            "wrong original job, archive or steps",
        )
        with file.open("rb") as f:
            need(
                asset["digest"] == "sha256:" + hashlib.file_digest(f, "sha256").hexdigest(),
                "wrong original archive bytes",
            )
        hosts[arm] = dict(
            runner=job["runner_name"], job=job["id"], artifact=asset["id"], sha256=asset["digest"]
        )
    need(
        all(len({row[k] for row in hosts.values()}) == 2 for k in ("runner", "job", "artifact")),
        "reused worker, job, or archive",
    )
    return hosts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--official", type=Path, required=True)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("archives", nargs=2, type=Path, metavar="ZIP")
    a = ap.parse_args()
    hosts = official(a.official, a.run, a.head, a.archives)
    results = {arm: worker(file, arm) for arm, file in zip(ARM, a.archives, strict=True)}
    for arm, (en, _, _) in results.items():
        need(
            (en["head"], en["run"], en["runner"]) == (a.head, a.run, hosts[arm]["runner"]),
            "different original native worker",
        )
    e, c = (results[k] for k in ARM)
    need(e[0]["boot"] != c[0]["boot"] and e[1] == c[1], "reused boot or different absolute comparison roots")
    native = {}
    for phase in s.PHASES:
        if phase == "invalid":
            continue
        l, r = e[2][phase], c[2][phase]
        need(
            l["stub"] == r["stub"] and old.behavior(l["native"]) == old.behavior(r["native"]),
            "different E/C behavior",
        )
        native[phase] = {
            arm: dict(
                cli=states[phase]["native"]["cli"]["whole"],
                reader=states[phase]["native"]["reader"]["whole"],
                typed=states[phase]["native"]["typed"],
                dirty=states[phase]["dirty"],
                positive=states[phase]["positive"],
            )
            for arm, (_, _, states) in results.items()
        }
        for name in ("cli", "reader"):
            need(
                all(l["native"][name][k] == r["native"][name][k] for k in ("loads", "executable")),
                ("different cross-compiler executable bytes", phase, name),
            )
    print(
        json.dumps(
            dict(
                qualified=True,
                run=a.run,
                head=a.head,
                hosts=hosts,
                native=native,
                parser_error="E0308",
                clocks=0,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
