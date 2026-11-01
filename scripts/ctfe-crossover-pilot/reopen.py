"""Independently read the two whole Ruff histories, their native products, and inherited counters."""

import argparse
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctfe_pilot_registration as reg

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "kernel-review"), str(HERE.parent / "branch-storage-e-confirmation/review")]
import corpus
import hardware
import replay_controls
import replay_elf
import replay_metrics as metrics
import replay_native

KERNEL = {"kernel_projection.py": "fb3f2f38d0ef14eb99c4456f668837e5367f032243747e1ee1192bcc724d4ecf",
          "read_events.py": reg.READER}
for name, expected in KERNEL.items():
    metrics.need(metrics.sha((HERE / "kernel-review" / name).read_bytes()) == expected, "wrong kernel reader " + name)
import kernel_projection as kernel

ROLES = ("Eon", "Con")
REFS = ("clean-A", "clean-B", "clean-edited")
PHASES = ("Y-B", "X-A", "X-B", "comment", "unchanged", "invalid", "repair")
TRACED = {"return": {"X-B", "comment", "unchanged", "invalid", "repair"}, "stay": {"comment", "unchanged"}}
CARGO = metrics.COMMAND
WILD = kernel.WILD
DRIVER = "lib/librustc_driver-c5276fb6f0cdddb4.so"
SOURCES = {"E": "393b4b05a4bfa3f531a36023846f86236a6b71a9", "C": "df2c077a113a709ab379c8ec34e62c94c7513325"}
TREES = {"E": "89dcac9002ea6a0307d6fef82c0652b15c85dcca", "C": "37bae6b16cbb4858b2dd597f70048cb7f2dc041c"}
MANIFEST = {"E": "2f104fd6f02b2cf583a6b203e55cc17af4fbb9539398d915277cdfe2be9c0113",
            "C": "5c852dd08970b9762189eb1e1094df97bfba84bf06aea35e7db6e10530bcd701"}
# Canonical content of every member of the two original SDK records in official ZIP 13073252134.
SDK_CONTENT = {"E": "d6fcbf8965036941a40a46acfb0147c53bbf160d0f51db7b8ee4c9edcc2b3786",
               "C": "a51417a5cb8bdc6d20570b879e52e19fd07c40e686410815544a113779b6ed57"}
NODE = "crates/ruff_python_ast/src/nodes.rs"
PARSER = "crates/ruff_python_parser/src/lib.rs"
AST = {"A": "19d7a907a8ff1cb9a6030e04d20d4e58e78a03a9de7d40c67f5644ad45ab025c",
       "B": "299c122da4caf5214b15cb4d36dba18ca7855beb31ea50f9050d9a0cc816275c",
       "edited": "dbda1ba0b8c4a8ae98c62da763c9128260db17fc0c3911e2a377073a5284e937"}
PARSER_SHA = {False: "ee24a1933840a400c4730778a5c222d30c36d4b1b4f96bd97b502acfc07a4875",
              True: "3fbac7f54be2b5cd47eee1993f11e6d58724e32301c0ba3e5afb624562283ab5"}
BRANCH = {"A": "historical-parent", "B": "historical-feature"}
require = metrics.need
digest = metrics.sha


def compact(value):
    return digest((metrics.canonical(value) + "\n").encode())


def dataset(z, path):
    raw = z.read(path)
    return json.loads(gzip.decompress(raw) if path.endswith(".gz") else raw)


def source_state(source, phase, route):
    branch = "A" if phase in ("clean-A", "X-A") else "B"
    checkout = "A" if branch == "A" or phase == "X-B" or route == "stay" and phase in ("comment", "unchanged") else "B"
    edited = phase in ("clean-edited", "comment", "unchanged", "invalid", "repair")
    bad = phase == "invalid"
    ref = BRANCH[checkout]
    names = ([NODE] if edited else []) + ([PARSER] if bad else [])
    require((source["branch"], source["revision"], source["tree"], source["ref"], source["modified"],
             source["nodes"], source["parser"]) ==
            (branch, metrics.REVS[branch], corpus.TREES[branch], ref, sorted(names), AST["edited" if edited else branch],
             PARSER_SHA[bad]), ("wrong checkout, edit, or repair", phase, route))
    watched = source["watched"]
    head = "refs/heads/" + ref
    require(set(watched) == {"HEAD", head} and watched["HEAD"][-1] == digest(("ref: " + head + "\n").encode())
            and watched[head][-1] == digest((metrics.REVS[branch] + "\n").encode())
            and all(len(x) == 5 and all(type(i) is int and i > 0 for i in x[:4]) for x in watched.values()),
            "wrong physical build-script Git inputs")
    return branch, "clean-edited" if edited else "clean-" + branch


def sdk_pair(z):
    pair = {r: dataset(z, "sdk/" + r + ".json") for r in SOURCES}
    records = []
    for role, row in pair.items():
        source = row["source"]["role"]["commit"] if role == "E" else row["source"]
        files = row["files"]
        require(row["role"] == role and source == SOURCES[role] and row["driver"] == DRIVER
                and len(files) == 81 and compact({k: [v[0], v[4], v[3]] for k, v in files.items()}) == SDK_CONTENT[role],
                "wrong complete original SDK " + role)
        ids = {tuple(entry[1:3]) for entry in files.values()}
        require(len(ids) == 81, "aliased SDK members")
        records.append(ids)
    require(records[0].isdisjoint(records[1]), "reused physical SDK members")
    return pair


def active(z, top, arm, files):
    cert = dataset(z, top + "/arm.json")
    env = cert["env"]
    root = PurePosixPath(env["CARGO_TARGET_DIR"]).parent.parent
    require(root.is_absolute() and root.name == "ohm-branch-object-qa"
            and cert["arm"] == arm and cert["role"] == arm[0] and cert["source_manifest"] == MANIFEST[arm[0]]
            and cert["files"] == {f: files[f] for f in ("bin/cargo", "bin/rustc", "bin/rustdoc", DRIVER, WILD)}
            and cert["sdk"] == str(root / "home/.rustup/toolchains/ohm")
            and env["CARGO_ENCODED_RUSTFLAGS"] == "-Zohm-branch-cache=yes" and env["CARGO_NET_OFFLINE"] == "true"
            and env["CARGO_TARGET_DIR"] == str(root / "work/target") and env["CARGO_BUILD_BUILD_DIR"] == str(root / "work/build")
            and not ({"RUSTC", "RUSTFLAGS", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER"} & env.keys()),
            "incorrect physical compiler or effective Cargo environment")
    return cert, root


def kernel_fixtures(z, base, source):
    from contact_review import fixtures
    group = fixtures(z, base, source)
    q = dataset(z, base + "/qualified.json")
    pos = {"abort": 13, "duplicate": 19, "family": 23, "long": 0, "signals": 14, "thread": 37}
    refused = {"escape", "escape3"}
    expected = {name + "." + ext for name in set(pos) | refused for ext in ("stderr", "stdout", "tsv")} | {"run.json"}
    require(q["qualified"] and digest(z.read(base + "/observe.elf")) == q["observer_sha256"]
            and q["sources"] == {k.split("/")[1]: v for k,v in group["sources"].items() if k.startswith("kernel/")}
            and q["sources"]["observe.c"] == reg.SOURCE and q["sources"]["read_events.py"] == reg.READER
            and q["native"]["live_physical_reopen"] and q["native"]["long_argument_bytes"] == 98003
            and set(q["originals"]) == expected and set(q["native"]["positive"]) == set(pos)
            and set(q["native"]["negative"]) == refused and len(q["native"]["mutations_rejected"]) == 16
            and len(q["ruff_projection"]["refusals"]) == 12, "unqualified kernel observer/fixture")
    for n, h in q["originals"].items():
        require(digest(z.read(base + "/original/" + n)) == h, "changed raw observer fixture")
    for name, code in pos.items():
        raw = z.read(base + "/original/" + name + ".tsv")
        record = q["native"]["positive"][name]
        checked = kernel.parse(raw, code, record["sha256"], expected_schema=3)
        require(all(checked[k] == record[k] for k in ("code", "lifetimes", "reaped", "displaced", "spawned", "images"))
                and len(checked["execs"]) == record["image_installs"], "different physical fixture closure")
    for name in refused:
        bad = z.read(base + "/original/" + name + ".tsv")
        reason = b"clone3 CLONE_UNTRACED escape" if name == "escape3" else b"CLONE_UNTRACED escape"
        require(digest(bad) == q["native"]["negative"][name] and bad.splitlines()[-1].split(b"\t")[:2] == [b"REFUSE", reason],
                "wrong escape negative")
        try:
            kernel.parse(bad, expected_schema=3)
        except kernel.Refused:
            continue
        raise ValueError("accepted an escaped process family")
    return group


def kernel_binding(z, boot, mode, source, prior):
    base = "kernel-qualification"
    b = dataset(z, base + "/binding.json")
    require(compact(b["official"]) == "4e1f6dfa8d05fb00d6db418db7efdbc3e7c130a38865263883d9e7801c67eef5"
            and compact(b["independent"]) == b["official"]["independent_sha256"]
            and digest((json.dumps(b["root_independent"], sort_keys=True, indent=2) + "\n").encode())
            == b["official"]["root_independent_sha256"]
            and b["official"]["head"] == "2969895dc49c9d8970ef121e1ff024ef001dc7ce"
            and b["source_head"] == reg.OBSERVER and b["projector_head"] == reg.PROJECTOR
            and b["boot"] == boot != b["official"]["boot"]
            and b["fixtures_sha256"] == digest(z.read(base + "/fixtures/qualified.json")), "wrong enrolled kernel history")
    group = kernel_fixtures(z, base + "/fixtures", source)
    reg.fresh(boot, [b["official"]["boot"]] + ([prior["boot"]] if prior else []))
    require(b["mode"] == mode and b["prior_v3"] == (prior["official"] if prior else None) and
            ((mode == "full-pilot") == (prior is not None)) and
            b["group_fixtures_sha256"] == digest(z.read(base + "/fixtures/group-v2/qualified.json")) and
            group["schema"] == 3 and group["qualified"] is True and group["boot"] == boot and
            group["kernel"] == dataset(z,"host.json")["platform"]["release"] and
            group["observer_sha256"] == b["observer_sha256"] == digest(z.read(base + "/fixtures/observe.elf")) and
            (not prior or prior["observer_sha256"] == b["observer_sha256"]) and
            group["stock_wild_sha256"] == kernel.STOCK, "wrong host fixture, prior contact or binary")
    return b


def driver(z, top, prefix, arm, cert):
    path = str(PurePosixPath(cert["sdk"]) / DRIVER)
    identity = cert["files"][DRIVER]
    proof = dict(source=SOURCES[arm[0]], compiler_tree=TREES[arm[0]], driver=path,
                 driver_identity=identity, source_manifest=cert["source_manifest"])
    require(dataset(z, prefix + "/source-before.json") == proof == dataset(z, prefix + "/source-after.json"),
            "unbound compiler before or after positive native observation")
    loader = dataset(z, top + "/loader.json")
    interp = "/lib64/ld-linux-x86-64.so.2"
    base = PurePosixPath(DRIVER).name
    require(loader["driver_identity"] == identity and loader["driver"] in (path, cert["sdk"] + "/bin/../" + DRIVER)
            and loader["interpreter"] == interp
            and re.findall(r"\[Requesting program interpreter: ([^\]]+)\]", z.read(top + "/loader-interpreter.txt").decode()) == [interp]
            and [x for x in re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", z.read(top + "/loader-needed.txt").decode())
                 if x.startswith("librustc_driver-")] == [base]
            and re.findall(r"^\s*" + re.escape(base) + r" => (\S+) \(0x[0-9a-f]+\)$",
                           z.read(top + "/loader-resolved.txt").decode(), re.MULTILINE) == [loader["driver"]],
            "wrong physically loaded compiler driver")


def physical(z, prefix, arm, cert, cmd, expected):
    top = prefix.rsplit("/", 1)[0]
    catalog = dataset(z, top + "/catalog.json")
    kernel.catalog_guard(catalog)
    proxy = dataset(z, "sdk/proxy.json")
    for role, name in kernel.ROLES.items():
        require(catalog[role]["identity"] == cert["files"][name]
                and catalog[role]["path"] == str(PurePosixPath(cert["sdk"]) / name), "kernel catalog/SDK mismatch")
    require(catalog["cargo"]["identity"][0] == kernel.STRICT and catalog["wild"]["identity"][0] == kernel.STOCK
            and catalog["proxy"]["identity"][0] == proxy["sha256"] and catalog["proxy"]["path"] in proxy["paths"]
            and all(v == catalog["proxy"]["identity"][1:] for v in proxy["paths"].values()), "wrong proxy or native kit")
    kernel.bound_launch(z, prefix, cmd)
    raw = gzip.decompress(z.read(prefix + "/kernel.tsv.gz"))
    life = dataset(z, prefix + "/lifecycle.json")
    rows, closed = kernel.classify(raw, catalog, tuple(proxy["paths"]), CARGO, arm, expected, cmd["cwd"], life["sha256"])
    require(closed["schema"] == 3 and life == {k: len(v) if isinstance(v, list) else v for k, v in closed.items()}, "unclosed process family")
    kernel.match_rows(rows, dataset(z, prefix + "/native-execs.json.gz"))
    if expected == 101:
        parser, = [r for r in rows["rustcs"] if (r["crate"], r["mode"]) == ("ruff_python_parser", "full")]
        wait_tag = f"T\t{parser['lifetime']}\t{parser['pid']}\t".encode()
        status, = [int(line.split(b"\t")[3]) for line in raw.splitlines() if line.startswith(wait_tag)]
        require(os.waitstatus_to_exitcode(status) == 1, "the registered real parser compiler did not fail")
    workers = {}
    for row in rows["rustcs"]:
        args = row["argv"]
        types = [a.partition("=")[2] if a.startswith("--crate-type=") else args[i + 1]
                 for i, a in enumerate(args) if a == "--crate-type" or a.startswith("--crate-type=")]
        workers[row["event"]] = [row["crate"], ",".join(sorted(types)) or "<implicit>"]
    compilers = sorted([r["crate"], r["mode"]] for r in rows["rustcs"])
    # Distinguish a workspace lib from its like-named bin. Associate links with the actual rustc ancestor.
    full = sorted(workers[r["event"]] for r in rows["rustcs"] if r["mode"] == "full")
    links = sorted(workers[r["rustc_event"]] for r in rows["wild_processes"])
    helpers = reg.wild_helpers(raw, rows["wild_processes"])
    require(helpers == dataset(z,prefix+"/wild-helpers.json"), "different inherited physical Wild fork-group")
    groups = reg.compiler_groups(raw, rows["rustcs"])
    require(groups == dataset(z,prefix+"/compiler-groups.json"), "different installed compiler exit groups")
    return {"compilers": compilers, "full_units": full, "link_units": links, "links": len(links), "wild_helpers": helpers, "compiler_groups": groups,
            "system": [r["kind"] for r in rows["other_linkers"]], "kernel": life["sha256"]}


def verified_body(z, name, desc, checked):
    key = (name, desc["whole"])
    if key not in checked:
        replay_elf.verify(z, "native-bodies/" + desc["whole"] + ".zst", desc, "ruff" if name == "cli" else None)
        checked[key] = desc
    require(checked[key] == desc, "inconsistent descriptions of the same physical ELF")


def behavior(native):
    return {k: v for k, v in native.items() if k not in ("cli", "reader")}


def typed_inputs(z, prefix, stdout, root):
    products = [e for e in map(json.loads, stdout.splitlines()) if e["reason"] == "compiler-artifact"]
    externs = []
    for name in ("ruff_python_ast", "ruff_python_parser"):
        path, = [f for e in products if e["target"]["name"] == name and "lib" in e["target"]["kind"]
                 for f in e["filenames"] if f.endswith(".rlib")]
        member = PurePosixPath(path)
        require(".." not in member.parts and any(member.is_relative_to(root / "work" / space) for space in ("target", "build")),
                "external client used a foreign workspace rlib")
        externs.append(name + "=" + path)
    reader = str(root / "full-cli-reader/reader")
    for label in ("reader-compile", "layout-64", "layout-56"):
        argv = dataset(z, prefix + "/" + label + ".json.gz")["argv"]
        require(argv[:2] == ["rustc", "+ohm"] and [argv[i + 1] for i, a in enumerate(argv) if a == "--extern"] == externs,
                "typed check did not consume both actual emitted rlibs")
        if label == "reader-compile":
            require(argv[-2:] == ["-o", reader], "wrong linked external native reader")
    require(dataset(z, prefix + "/reader-run.json.gz")["argv"] == [reader], "different external native reader ran")


def read_phase(z, prefix, phase, lane, route, arm, cert, root, bodies):
    source = dataset(z, prefix + "/source.json")
    branch, reference = source_state(source, phase, route)
    score = dataset(z, prefix + "/visit.json")
    cmd = dataset(z, prefix + "/cargo.json.gz")
    expected = 101 if phase == "invalid" else 0
    where = root / "logs" / prefix
    require(score["phase"] == phase and score["status"] == cmd["expected"] == expected and cmd["env"] == cert["env"]
            and cmd["cwd"] == str(root / "ruff") and cmd["stdin_sha256"] == digest(b""), "Cargo source/role/status")
    raw = replay_native.raw(z, prefix, "cargo.stdout.gz")
    error = replay_native.raw(z, prefix, "cargo.stderr.gz")
    roster = metrics.cargo_messages(raw, error, cmd, expected, cmd["cwd"])
    totals = dataset(z, prefix + "/storage.json")
    allocated = metrics.allocation(dataset(z, prefix + "/path-inodes.json.gz"), totals,
                                   dataset(z, prefix + "/allocation-readers.json"))
    require(allocated == score["allocated"] and totals["all_inodes"] > 1000 and min(totals["roots"].values()) > 0,
            "incomplete allocation")
    result = dict(status=expected, allocated=allocated, source=source, reference=reference, graph=None, dirty=None, cli=None, reader=None)
    if roster is not None:
        graph = compact(roster["members"])
        require(not totals["failed_sessions"] and roster == dataset(z, prefix + "/roster.json.gz")
                and graph == score["graph"] and compact(roster["dirty"]) == score["dirty"], "different Cargo graph")
        if phase.startswith("clean-") or phase == "Y-B":
            require(len(roster["dirty"]) == 375 and totals["packed_files"] == 0, "false empty reference")
        native = replay_native.native_verdict(z, prefix, branch)
        typed_inputs(z, prefix, raw, root)
        for name in ("cli", "reader"):
            require(native[name]["whole"] == score[name], "unbound native product")
            verified_body(z, name, native[name], bodies)
        result.update(graph=graph, dirty=score["dirty"], cli=score["cli"], reader=score["reader"], native=native)
    else:
        errors = [v for v in map(json.loads, raw.splitlines()) if v["reason"] == "compiler-message"
                  and v["message"]["level"] == "error" and v["message"]["code"]]
        require(errors and all(v["target"]["name"] == "ruff_python_parser" and v["message"]["code"]["code"] == "E0308"
                and any(s["is_primary"] and s["file_name"] == PARSER and s["line_start"] == 626 and
                        any("ohm_branch_switch_invalid" in t["text"] for t in s["text"]) for s in v["message"]["spans"])
                for v in errors), "wrong actual parser error")
        require(set(totals["failed_sessions"]) == set(dataset(z, prefix + "/failed.json")), "wrong failed sessions")
    clock_path = prefix + "/clock.json"
    traced = lane == "structural" and phase in TRACED[route]
    require(score["observer"] == ("kernel" if traced else "pmu" if lane == "measured" else "ordinary"), "wrong observation header")
    if lane == "measured":
        require(cmd["observer_argv"] == [str(root / "logs/observers/plain"), str(where / "clock.json"), *CARGO]
                and all(prefix + "/" + name not in z.NameToInfo for name in ("kernel.tsv.gz","native-execs.json.gz","lifecycle.json","wild-helpers.json","compiler-groups.json")), "wrong or traced PMU launch")
        clock = dataset(z, clock_path)
        require(set(clock) == {"start", "stop", "user_us", "system_us", "instructions", "enabled", "running", "event_errno", "code"}
                and all(type(v) is int for v in clock.values()) and clock["stop"] > clock["start"]
                and clock["user_us"] + clock["system_us"] > 0, "wrong PMU ABI")
        result.update(instructions=metrics.measured_count(clock, expected), start=clock["start"], stop=clock["stop"])
        require(result["instructions"] == score["instructions"], "reported instructions differ")
    else:
        require(clock_path not in z.NameToInfo and score["instructions"] is None, "unexpected counter in structural control")
        if traced:
            driver(z, prefix.rsplit("/", 1)[0], prefix, arm, cert)
            result.update(physical(z, prefix, arm, cert, cmd, expected))
            require(result["compilers"] == score["compilers"] and result["links"] == score["links"], "wrong physical roster")
            if phase in ("comment", "X-A", "X-B"):
                require(["ruff_python_ast", "full"] in result["compilers"] and
                        (phase == "comment" or result["links"] > 0), "historical source did not run its compiler/link")
        else:
            require(cmd["observer_argv"] is None and prefix + "/kernel.tsv.gz" not in z.NameToInfo
                    and all(prefix+"/"+n not in z.NameToInfo for n in ("native-execs.json.gz","lifecycle.json","wild-helpers.json","compiler-groups.json"))
                    and "compilers" not in score and "links" not in score, "invented physical rows or instrumented clean")
    return result


def compare(rows):
    issues = []
    for state in REFS:
        e, c = (rows[a]["clean/reference/" + state] for a in ROLES)
        require(e["graph"] == c["graph"] and behavior(e["native"]) == behavior(c["native"]), "different clean behavior")
        for kind in ("cli", "reader"):
            if any(e["native"][kind][key] != c["native"][kind][key] for key in ("executable", "loads")):
                issues.append(dict(reference=state, different_executable_bytes=kind, E=e[kind], C=c[kind]))
    for arm, visits in rows.items():
        require(visits["clean/reference/clean-A"]["cli"] != visits["clean/reference/clean-B"]["cli"],
                "historical A/B did not change the full Ruff executable")
        for key, data in visits.items():
            lane, route, phase = key.split("/")
            if phase == "unchanged":
                require(data["source"] == visits[f"{lane}/{route}/comment"]["source"], "changed inputs before unchanged")
            if lane == "clean" or phase == "invalid":
                continue
            want = visits["clean/reference/" + data["reference"]]
            require(data["graph"] == want["graph"] and behavior(data["native"]) == behavior(want["native"]),
                    "warm typed graph, diagnostics or CLI behavior differs from own independent empty")
            for kind in ("cli", "reader"):
                if data[kind] != want[kind]:
                    issues.append(dict(visit="-".join([lane, route, arm]) + "/" + phase, product=kind,
                                       actual=data[kind], empty=want[kind]))
        for phase in PHASES:
            warm = visits["measured/return/" + phase]
            structural = visits["structural/return/" + phase]
            for key in ("status", "graph", "dirty", "cli", "reader"):
                if warm[key] != structural[key]:
                    issues.append(dict(arm=arm, phase=phase, structural_disagreement=key))
    return issues


def counts(items):
    return collections.Counter(tuple(u) if isinstance(u, list) else u for u in items)


def decision(rows, issues):
    observed = [rows[arm]["structural/return/comment"] for arm in ROLES]
    full = [counts(v["full_units"]) for v in observed]
    links = [counts(v["link_units"]) for v in observed]
    other = [counts(v["system"]) for v in observed]
    insn = {arm: rows[arm]["measured/return/comment"]["instructions"] for arm in ROLES}
    def units(counter):
        return [list(k) for k in sorted(counter.elements())]
    return dict(instructions=insn, ratio=insn["Eon"] / insn["Con"], skipped=units(full[0] - full[1]),
                added=units(full[1] - full[0]), added_link_owners=units(links[1] - links[0]),
                eligible=not issues and insn["Eon"] >= 2 * insn["Con"] and full[0] > full[1]
                and links[1] <= links[0] and other[1] <= other[0])


def reopen(path, position, source, prior):
    from contact_review import host_guards
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and all(not PurePosixPath(n).is_absolute()
                and ".." not in PurePosixPath(n).parts for n in names), "ambiguous or unsafe ZIP")
        pos = dataset(z, "position.json")
        order = list(ROLES if position == "01" else reversed(ROLES))
        meter = dataset(z, "meter-ready.json")
        boot = pos["boot"]
        require(pos["mode"] == "full-pilot" and prior["qualified"] is True and prior["head"] == pos["head"]
                and dataset(z,"prior-v3-contact.json") == prior, "borrowed or missing independent prior contact")
        host_guards(z,pos)
        binding = kernel_binding(z,boot,"full-pilot",source,prior)
        cal = replay_controls.calibration(z, boot)
        clock_proof = hardware.verify(z, cal, meter)
        require(pos["position"] == position and pos["order"] == order and pos["command"] == CARGO
                and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot)
                and re.fullmatch(r"[0-9a-f]{40}", pos["head"]) and int(pos["run"]) > 0
                and pos["plan"] == digest((HERE / "PLAN.md").read_bytes())
                and boot == meter["boot"] and cal["affinity"] == meter["affinity"]
                and meter["observer"] == replay_controls.OBS and meter["calibrator"] == replay_controls.CAL,
                "wrong run, plan, counter scope, or boot")
        pair = sdk_pair(z)
        rows = {a: {} for a in ROLES}
        bodies = {}
        previous_stop = 0
        envs = {}
        clocks, ledgers = set(), set()
        for lane, route, phases in (("clean", "reference", REFS), ("structural", "stay", PHASES[:5]),
                                    ("structural", "return", PHASES), ("measured", "return", PHASES)):
            for arm in order:
                top = "-".join((lane, route, arm))
                cert, root = active(z, top, arm, pair[arm[0]]["files"])
                require(envs.setdefault(arm, cert["env"]) == cert["env"], "changed within-role environment")
                require(meter["plain"] == str(root / "logs/observers/plain"), "different calibrated counter binary")
                require(binding["observer"] == str(root / "kernel-qualification/tools/observe"), "foreign recorder path")
                for phase in phases:
                    prefix = top + "/" + phase
                    result = read_phase(z, prefix, phase, lane, route, arm, cert, root, bodies)
                    rows[arm]["/".join((lane, route, phase))] = result
                    if lane == "measured":
                        clocks.add(prefix + "/clock.json")
                        require(previous_stop < result["start"], "overlapping or reordered measured intervals")
                        previous_stop = result["stop"]
                    elif lane == "structural" and phase in TRACED[route]:
                        ledgers.add(prefix + "/kernel.tsv.gz")
        require({n for n in names if n.startswith(("structural-", "measured-", "clean-reference-")) and n.endswith("/kernel.tsv.gz")} == ledgers
                and {n for n in names if n.startswith(("structural-", "measured-", "clean-reference-")) and n.endswith("/clock.json")} == clocks,
                "unexpected extra or absent meter/structural observation")
        require(envs["Eon"] == envs["Con"], "different compiler-role Cargo environments")
        issues = compare(rows)
        verdict = decision(rows, issues)
        pilot = dataset(z, "pilot.json")
        require(pilot["position"] == position and pilot["order"] == order and pilot["ratio"] == verdict["ratio"]
                and counts(map(metrics.canonical, issues)) == counts(map(metrics.canonical, pilot["qualification_issues"])),
                "worker's endpoint or native issues disagree with physically reopened originals")
        for arm in ROLES:
            measured = rows[arm]["measured/return/comment"]
            traced = rows[arm]["structural/return/comment"]
            require(pilot["primary"][arm] == dict(instructions=measured["instructions"], allocated=measured["allocated"],
                    compilers=traced["compilers"], links=traced["links"]), "reported primary is not the raw primary")
        require(not pilot["candidate_for_confirmation"] or verdict["eligible"], "unsafe worker promotion")
        require("failure.txt" not in names or not verdict["eligible"], "incomplete worker promoted")
        report = {arm: {key: {k: v for k, v in obs.items() if k not in ("source", "native", "start", "stop")}
                        for key, obs in visits.items()} for arm, visits in rows.items()}
        return dict(position=position, boot=boot, head=pos["head"], run=int(pos["run"]), **verdict,
                    worker_accepted=pilot["candidate_for_confirmation"], issues=issues,
                    checked_elfs=len(bodies), calibration=clock_proof, visits=report)


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("archives",type=Path,nargs=2,metavar="ZIP")
    args.add_argument("--official",type=Path,required=True)
    args.add_argument("--run",type=int,required=True)
    args.add_argument("--head",required=True)
    args.add_argument("--observer-source",type=Path,required=True)
    args.add_argument("--contact-archive",type=Path,required=True)
    args.add_argument("--contact-official",type=Path,required=True)
    args.add_argument("--contact-run",type=int,required=True)
    opt=args.parse_args()
    from contact_review import from_official
    source=opt.observer_source.resolve(strict=True)
    prior=from_official(opt.contact_archive,opt.contact_official,opt.contact_run,opt.head,source)
    meta=reg.official(opt.official,opt.run,opt.head,"full-pilot",opt.archives)
    pair=[reopen(p,pos,source,prior) for pos,p in zip(("01","02"),opt.archives,strict=True)]
    require(len({prior["boot"], *(r["boot"] for r in pair)}) == 3 and
            all((r["run"],r["head"])==(opt.run,opt.head) for r in pair), "reused boot or different source/run")
    print(json.dumps(dict(positions=pair,official=meta,contact=prior["official"],
                          advance=all(r["eligible"] and r["worker_accepted"] for r in pair)),sort_keys=True,indent=2))
