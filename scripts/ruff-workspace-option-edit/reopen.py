"""Read the original whole clock, actual rustc processes, typed clients, and physical CGU bodies."""

from collections import Counter
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import study as p
import setup
from setup import c

sys.path[:0] = [str(setup.CGU), str(setup.BASE)]
import instrument
import ownership
import reader


def read(path):
    return json.loads(path.read_bytes())


def unpack(path):
    with path.open("rb") as f, gzip.GzipFile(fileobj=f) as raw:
        body = raw.read((512 << 20) + 1)
    p.need(len(body) <= 512 << 20, "oversized saved file")
    return body


def strict_clock(row, code):
    p.need(
        row["code"] == code
        and row["event_errno"] == 0
        and row["instructions"] > 0
        and row["running"] == row["enabled"] > 0,
        "incomplete native hardware window",
    )
    return row["instructions"]


def checked(desc, magic, store, cache, archive=False):
    key = desc["sha256"]
    size = desc["stat"][2]
    p.need(
        len(key) == 64 and all(c in "0123456789abcdef" for c in key) and 0 < size <= 512 << 20,
        "malformed stored digest/size",
    )
    if key not in cache:
        body = unpack(store / (key + ".gz"))
        p.need(
            len(body) == size and p.sha(body) == key and body.startswith(magic),
            "damaged compressed physical original",
        )
        if magic == b"\x7fELF":
            p.need(
                body[:7] == b"\x7fELF\x02\x01\x01" and struct.unpack_from("<H", body, 18)[0] == 62,
                "wrong native client architecture",
            )
        cache[key] = (size, magic, reader.members(body, p.OWNER) if archive else None)
    p.need(cache[key][:2] == (size, magic), "conflicting artifact descriptor")
    return cache[key][2]


def nul(path):
    body = path.read_bytes()
    p.need(body.endswith(b"\0") and 1 < len(body) <= 1 << 20, "incomplete actual rustc arguments")
    return [os.fsdecode(s) for s in body[:-1].split(b"\0")]


def roster(stage, mode, sdk, env, phase, bad, products, rows):
    out = []
    seqs = [json.loads(line) for line in (stage / "rustc.jsonl").read_bytes().splitlines()]
    real_files = {f.name for f in stage.iterdir() if f.is_file()}
    files = {"rustc.jsonl"}
    owned = []
    for seq, r in enumerate(seqs, 1):
        entry = f"rustc-{seq:05d}.nul"
        files.add(entry)
        p.need(
            r["entry"] == entry and r["seq"] == seq and type(r["pid"]) == int and r["pid"] > 0,
            "unbound raw rustc event",
        )
        argv = nul(stage / entry)
        p.need(argv[0] == sdk and p.FLAG not in argv, "foreign or modified rustc entry")
        name = ownership.option(argv, "--crate-name") if "--crate-name" in argv else ""
        p.need(name == r["crate"], "wrong rustc crate in raw roster")
        query = ownership.rustc_query(argv)
        # The genuine Cargo platform probe asks one rustc for six crate-type filenames.
        crate_types = [value for flag, value in zip(argv, argv[1:]) if flag == "--crate-type"]
        target = "+".join(crate_types)
        selected = (
            name == p.OWNER
            and target == "lib"
            and "--out-dir" in argv
            and "--emit=dep-info,metadata,link" in argv
        )
        out.append((name, target, query, argv))
        if selected:
            owned.append(r["pid"])
            actor = stage / p.OWNER
            actual = nul(actor / "observed.nul")
            process = read(actor / "process.json")
            p.need(
                argv == nul(actor / "original.nul")
                and actual == argv + ([p.FLAG] if mode == "capture" else []),
                "additional compiler flags or unrelated event",
            )
            p.need(
                process["pid"] == r["pid"]
                and [process["compiler_dev"], process["compiler_ino"]] == rows["bin/rustc"][1:3]
                and process["argc"] == [len(argv), len(actual)]
                and process["capture"] == (mode == "capture")
                and process["envc"][0] - process["envc"][1] == int(mode == "capture")
                and 0 < process["aux_pairs"] <= 128,
                "foreign physical compiler or malformed argv",
            )
    need_actor = bad or any(r["target"]["name"] == p.OWNER and not r["fresh"] for r in products)
    p.need(
        files == real_files and len(owned) == int(need_actor) and not (stage / "ruff_linter").exists(),
        "unmatched compiler participant or non-workspace capture",
    )
    if phase in ("new", "repair", "revert", "unchanged", "invalid") and mode:
        # The exact class of every actual compiler is retained. No unnamed frontend or link is free.
        if phase == "unchanged":
            p.need(all(query for _, _, query, _ in out), "genuine Rust compilation on unchanged visit")
    return out


def physical_rows(where, rows, bad, store, cache):
    inventory = read(where / "cgus.json")
    if bad:
        p.need(not inventory, "falling back to stale library after expected E0308")
        return {}, {}, {}, {}
    p.need(set(inventory) == {p.OWNER}, "additional owner in library receipt")
    r = inventory[p.OWNER]
    obj, meta = checked(r["archive"], b"!<arch>\n", store, cache, True)
    root = read(where / "root-archive.json")
    (product,) = [
        q
        for q in rows
        if q.get("reason") == "compiler-artifact"
        and q["target"]["name"] == p.OWNER
        and q["target"]["kind"] == ["lib"]
    ]
    p.need(
        root["promoted"] in product["filenames"]
        and r["fresh"] == product["fresh"]
        and r["archive_path"] == root["compiler"]
        and r["archive"]["sha256"] == root["sha256"]
        and r["archive"]["stat"] == root["stats"][1],
        "mismatched root .rlib",
    )
    p.need(
        root["stats"][0][2] == root["stats"][1][2]
        and root["same_inode"] == (root["stats"][0][:2] == root["stats"][1][:2]),
        "conflicting promoted/hashed file identities",
    )
    bits = {}
    for key, d in r["emitted"].items():
        p.need(reader.module(d["name"], p.OWNER, "no-opt.bc") == key and key in obj, "unowned LLVM module")
        checked(d, b"BC\xc0\xde", store, cache)
        bits[key] = d["sha256"]
    if r["call"]:
        actor = where / "stage" / p.OWNER
        args = nul(actor / "observed.nul")
        p.need(
            r["call"]["argv"] == args
            and r["call"]["process"] == read(actor / "process.json")
            and str(Path(r["archive_path"]).parent) == ownership.option(args, "--out-dir"),
            "wrong physical archive/argv",
        )
        emitted = read(actor / "emitted.json")
        p.need(
            len(emitted) == len(bits) and {x["unit"] for x in emitted} == set(bits),
            "unaccounted newly-created bitcode",
        )
        for x in emitted:
            d = r["emitted"][x["unit"]]
            p.need(
                x["after"] == d["stat"] and x["before"][:4] == x["after"][:4] and x["name"] == d["name"],
                "replaced or unrelated bitcode",
            )
    else:
        p.need(not bits, "LLVM body without compiler event")
    return obj, meta, bits, r


def copy_trace(src, dest):
    total = 0
    for child in src.iterdir():
        target = dest / child.name
        p.need(child.name not in (".", "..") and "/" not in child.name, "escaping raw trace name")
        if child.is_dir():
            target.mkdir()
            copy_trace(child, target)
        else:
            body = child.read_bytes()
            total += len(body)
            p.need(total <= 64 << 20, "unbounded counter evidence")
            target.write_bytes(body)


def measure_owner(topo, where, selectors, sdk, products, repo, env, temp):
    trace = temp / "owner-trace"
    trace.mkdir()
    copy_trace(where / "owner-trace", trace)

    def classify(root, events, selected, samples, tasks, chains):
        p.need(
            sum(e["path"] == str(sdk / "bin/cargo") and e["argv"][1:] == p.CMD[2:] for e in events) == 1,
            "missing actual signed Cargo build",
        )
        compilers = [e for e in selected.values() if e["kind"] == 1]
        pids = {e["pid"] for e in compilers}
        p.need(
            len(pids) == len(compilers) > 0 and not any(pids.intersection(chains[k][1:]) for k in pids),
            "overlapping rustc charges",
        )
        charged = []
        targets = []
        for e in events:
            if e["kind"] == 1 and e["serial"] not in selected:
                p.need(ownership.rustc_query(e["argv"]), "unaccounted compiler")
        for e in compilers:
            a = e["argv"]
            name = ownership.option(a, "--crate-name")
            kind = ownership.option(a, "--crate-type")
            (source,) = [str(repo / s) for s in a if s.endswith(".rs")]
            matches = [
                r
                for r in products
                if r["target"]["name"].replace("-", "_") == name
                and r["target"]["src_path"] == source
                and not r["fresh"]
            ]
            p.need(
                len(matches) == 1 and matches[0]["target"]["crate_types"] == [kind], "ambiguous dirty unit"
            )
            targets.append(matches[0]["package_id"] + " " + matches[0]["target"]["name"])
            seconds = [v for v in selected.values() if v["kind"] in (2, 4) and e["pid"] in chains[v["pid"]]]
            charged.append(
                {
                    "crate": name,
                    "pid": e["pid"],
                    "instructions": samples[e["serial"]],
                    "subordinate_cc_wild": [[v["kind"], v["pid"], samples[v["serial"]]] for v in seconds],
                }
            )
        p.need(
            Counter(targets)
            == Counter(r["package_id"] + " " + r["target"]["name"] for r in products if not r["fresh"]),
            "extra/missing physical Cargo owner",
        )
        p.need(
            all(any(k in chains[e["pid"]] for k in pids) for e in selected.values() if e["kind"] != 1),
            "unowned physical linker",
        )
        residue = samples[0] - sum(r["instructions"] for r in charged)
        p.need(
            residue >= 0 and len([r for r in charged if r["crate"] == p.OWNER]) == 1,
            "invalid disjoint compiler attribution",
        )
        return {
            "whole": samples[0],
            "outside_measured_compilers": residue,
            "compilers": charged,
            "tasks": len(tasks),
            "execs": len(events),
        }

    return topo.read(trace, selectors, "tree", component=classify)


def execute_clients(root, typed, gold, temp):
    states = {}
    for key, digest in typed.items():
        rev = p.revision(key.split("/")[1])
        p.need(states.setdefault(digest, rev) == rev, "one ELF cannot emit both different field texts")
    for digest, rev in states.items():
        payload = unpack(root / "client-bodies" / (digest + ".gz"))
        p.need(p.sha(payload) == digest, "modified stored executable")
        fd = os.memfd_create("signed-option-client", os.MFD_CLOEXEC)
        try:
            with os.fdopen(os.dup(fd), "wb") as f:
                f.write(payload)
            os.fchmod(fd, 0o500)
            for key, code in ((p.KEY, 0), (p.SIBLING, 0), (p.MISSING, 2)):
                run = subprocess.run(
                    [f"/proc/self/fd/{fd}", key],
                    cwd=temp,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                    pass_fds=(fd,),
                    capture_output=True,
                    timeout=30,
                )
                p.need(
                    (run.returncode, run.stdout, run.stderr) == (code, gold[rev].get(key, b""), b""),
                    ("reopened typed executable", digest, key),
                )
        finally:
            os.close(fd)
    return len(states)


def verify(root, collector, contract, head, temp, execute=False):
    os.environ.setdefault("RUNNER_TEMP", str(temp))
    sys.path.insert(0, str(HERE))
    import worker as w

    enrollment = read(root / "enrollment.json")
    catalog = read(root / "catalog.json")
    current = catalog["current"]
    (job,) = catalog["this_jobs"]
    registration_env = {
        "GITHUB_RUN_ID": str(current["id"]),
        "GITHUB_SHA": head,
        "REVIEWED_HEAD": head,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_JOB": "diagnostic",
        "GITHUB_REPOSITORY": c.REPO,
        "GITHUB_REF": "refs/heads/" + p.BRANCH,
        "RUNNER_NAME": job["runner_name"],
    }
    setup.previous.BRANCH, setup.previous.JOB = p.BRANCH, p.JOB
    with setup.previous.registration():
        reproduced = setup.acquire.enrollment(
            *(catalog[key] for key in ("prior", "jobs", "artifacts", "excluded", "current", "this_jobs")),
            registration_env,
            enrollment["boot"],
        )
    p.need(
        reproduced == enrollment and catalog["excluded"] == read(HERE / "excluded-boots.json"),
        "inconsistent official boot or job custody",
    )
    p.need(
        len(head) == 40
        and current["head_sha"] == enrollment["head"] == head
        and current["id"] == enrollment["run"]
        and current["run_attempt"] == 1
        and current["event"] == "workflow_dispatch"
        and current["head_branch"] == p.BRANCH
        and current["repository"]["full_name"] == c.REPO
        and job["name"] == p.JOB
        and job["id"] == enrollment["job"]
        and job["runner_name"] == enrollment["runner"]
        and all(enrollment[k] != v for k, v in setup.FRESH.items()),
        "unauthenticated worker",
    )
    sdkrows = read(root / "sdk.json")
    asset = read(root / "asset.json")
    env = read(root / "environment.json")
    p.need(
        asset == c.SDK["asset"]
        and set(sdkrows) == set(c.SDK["members"])
        and all(
            (v[0], v[3], v[4]) == (c.SDK["members"][n][3], c.SDK["members"][n][1], c.SDK["members"][n][2])
            for n, v in sdkrows.items()
        ),
        "wrong signed SDK",
    )
    sdk = Path(env["RUSTUP_HOME"]) / "toolchains/ohm"
    sdk_rustc = str(sdk / "bin/rustc")
    p.need(
        (root / "source/option-client.rs").read_bytes() == (HERE / "client.rs").read_bytes()
        and (root / "source/bad-option-client.rs").read_bytes() == p.BAD_CLIENT,
        "different downstream consumer source",
    )
    fixture = read(root / "signed-fixture.json")["results"]
    p.need(
        set(fixture)
        == {"observe-old", "capture-old", "capture-new", "capture-unchanged", "capture-empty-new"}
        and all(
            v["field"] == p.EXPECTED[p.OLD if phase.endswith("-old") else p.NEW]
            and v["new_compiler"] == (phase != "capture-unchanged")
            and (v["cgus"] > 0) == (phase in {"capture-old", "capture-new", "capture-empty-new"})
            for phase, v in fixture.items()
        ),
        "signed fixture has wrong native polarity",
    )
    p.need(
        read(root / "recorder.json")
        == {
            "source": p.sha(setup.capture_source()),
            "elf": p.sha((root / "recorder").read_bytes()),
            "parent": setup.CAPTURE,
        },
        "recorder authentication",
    )
    topo, pmu = instrument.compile_sources(collector, contract, temp / "counter-source")
    (temp / "calibration").mkdir()
    copy_trace(root / "calibration", temp / "calibration")
    (temp / "counter-bins").mkdir()
    for n in ("plain", "tree", "nested", "loop"):
        (temp / "counter-bins" / n).write_bytes((root / "counter-programs" / n).read_bytes())
    pmu.calibration(temp / "counter-bins", temp, replay=True)
    selectors = read(root / "selectors.json")
    p.need(
        selectors["rustc"][:2] == sdkrows["bin/rustc"][1:3] and selectors["rustc"][2] == sdk_rustc,
        "owner selector",
    )
    gold = {}
    graphs = {}

    def git_hash(data):
        return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

    for lab, rev in p.REVISIONS.items():
        inputs = {}
        for n, sha in (
            (p.OPTIONS, p.INPUTS[rev][1]),
            (p.SCHEMA, p.INPUTS[rev][2]),
            ("Cargo.lock", p.LOCK),
            ("Cargo.toml", "2e809b607964dd98782025a6b63e281cbd11c278"),
            ("crates/ruff_workspace/Cargo.toml", p.PACKAGE_MANIFEST),
        ):
            body = unpack(root / "source" / (lab + "-" + n.replace("/", "_") + ".gz"))
            p.need(git_hash(body) == sha, "unbound original Ruff source bytes")
            inputs[n] = body
        gold[rev] = p.expected_outputs(rev, inputs[p.OPTIONS].decode())
        graphs[lab] = unpack(root / (lab + "-plan.json.gz"))
    p.need(graphs["old"] == graphs["new"], "different unit graphs")
    graph = w.graph_units(json.loads(graphs["old"]))
    all_cgus = {}
    all_clocks = {}
    raw = {}
    typed = {}
    cached = {}
    binaries = {}
    physical_counts = {}
    for lane, phases in p.HISTORIES.items():
        for phase in phases:
            where = root / lane / phase
            inv = read(where / "invocation.json")
            repo = Path(inv["cwd"])
            rev = p.revision(phase)
            bad = phase == "invalid"
            code = 101 if bad else 0
            source = read(where / "source-before.json")
            p.need(
                source == read(where / "source-after.json")
                and (source["base"], source["effective"], source["invalid"]) == (p.OLD, rev, bad),
                "wrong source state",
            )
            label = "old" if rev == p.OLD else "new"
            options = unpack(root / "source" / (label + "-" + p.OPTIONS.replace("/", "_") + ".gz"))
            p.need(
                source["options"] == p.sha(options + (p.INVALID if bad else b""))
                and source["schema"] == p.sha(unpack(root / "source" / (label + "-" + p.SCHEMA + ".gz"))),
                "incorrect actual working-tree bytes",
            )
            if phase == "unchanged":
                p.need(
                    source == read(root / lane / "new/source-after.json"), "unchanged event changed files"
                )
            if p.fresh(lane, phase):
                p.need(
                    set(read(where / "empty-roots.json"))
                    == {env["CARGO_TARGET_DIR"], env["CARGO_BUILD_BUILD_DIR"]},
                    "shared or missing empty roots",
                )
            mode = w.TRACE.get(lane)
            p.need(
                inv["cargo"] == p.CMD
                and inv["cmd"][-len(p.CMD) :] == p.CMD
                and inv["env"] == {**env, **({"OHM_CGU_REQUEST": p.FLAG} if mode else {})}
                and read(where / "exit.json") == code,
                "wrong Cargo invocation",
            )
            # Compare all outer actor arguments, including the boundary of the actual PMU.
            base = sdk.parents[3]
            paths = {name: [*coords[:2], coords[2]] for name, coords in selectors.items()}
            cmd = list(p.CMD)
            if mode:
                cmd = [
                    str(base / "workspace-cgu"),
                    str(base / "logs" / lane / phase / "stage"),
                    str(sdk / "bin/rustc"),
                    mode,
                    *cmd,
                ]
            if lane == "owner" and phase == "new":
                cmd = [
                    str(base / "counter-kit/bin/tree"),
                    str(base / "logs" / lane / phase / "owner-trace"),
                    "tree",
                    *[paths[r][2] for r in topo.ROLES],
                    *cmd,
                ]
            clock = lane == "plain" or (lane in ("observe", "capture") and phase == "new")
            if clock:
                cmd = [
                    str(base / "counter-kit/bin/plain"),
                    str(base / "logs" / lane / phase / "clock.json"),
                    *cmd,
                ]
            p.need(inv["cmd"] == cmd and (where / "clock.json").exists() == clock, "wrong PMU scope")
            rows = [json.loads(line) for line in unpack(where / "cargo.stdout.gz").splitlines()]
            prods = p.results(rows, not bad)
            if not bad:
                p.need(
                    Counter(w.graph_key(r["package_id"], r["target"], r["features"]) for r in prods)
                    == graph,
                    "partial Cargo build graph",
                )
                if p.fresh(lane, phase):
                    p.need(all(not r["fresh"] for r in prods), "empty reference reused a product")
                if phase == "unchanged":
                    p.need(all(r["fresh"] for r in prods), "unexpected fresh-build polarity")
                path = where / "client"
                data = read(path / "native.json")
                libs = {name: str(p.artifact(prods, name)) for name in (p.OWNER, "ruff_options_metadata")}
                compile_info = read(path / "compile.json")
                positive = compile_info["argv"]
                negative = read(path / "invalid.json")["argv"]
                p.need(
                    data["libs"] == libs
                    and compile_info["exit"] == 0
                    and positive[:7]
                    == [
                        "rustc",
                        "+ohm",
                        str(base / "option-client.rs"),
                        "--edition=2024",
                        "--crate-name",
                        "ohm_option_client",
                        "--error-format=json",
                    ]
                    and positive[-2:] == ["-o", str(base / "option-client")]
                    and positive[7:11]
                    == [piece for name, file in libs.items() for piece in ("--extern", name + "=" + file)]
                    and len(positive[11:-2]) % 2 == 0
                    and all(x == "-L" for x in positive[11:-2:2])
                    and negative
                    == [
                        "rustc",
                        "+ohm",
                        str(base / "bad-option-client.rs"),
                        *positive[3:-2],
                        "--emit=metadata",
                        "-o",
                        str(base / "bad-option.rmeta"),
                    ],
                    "consumer was not built against both Cargo-selected libraries",
                )
                checked(data["elf"], b"\x7fELF", root / "client-bodies", binaries)
                for check, key, status in (
                    ("field", p.KEY, 0),
                    ("sibling", p.SIBLING, 0),
                    ("missing", p.MISSING, 2),
                ):
                    p.need(
                        read(path / (check + ".json"))["exit"] == status
                        and (path / (check + ".stdout")).read_bytes() == gold[rev].get(key, b"")
                        and not (path / (check + ".stderr")).read_bytes(),
                        "wrong native client behavior",
                    )
                errors = [json.loads(s) for s in (path / "invalid.stderr").read_bytes().splitlines()]
                p.need(
                    read(path / "invalid.json")["exit"] == 1
                    and [x["code"]["code"] for x in errors if x.get("code") and x["level"] == "error"]
                    == ["E0308"],
                    "wrong client error",
                )
                typed[lane + "/" + phase] = data["elf"]["sha256"]
            if mode:
                roster_rows = roster(where / "stage", mode, sdk_rustc, env, phase, bad, prods, sdkrows)
                physical_counts[lane + "/" + phase] = dict(
                    Counter((n or "<unnamed>") + ("/query" if q else "/" + t) for n, t, q, _ in roster_rows)
                )
                if phase == "new" and lane in ("observe", "capture"):
                    raw[lane] = Counter(tuple(a) for _, _, _, a in roster_rows)
            if clock:
                all_clocks[lane + "/" + phase] = strict_clock(read(where / "clock.json"), code)
            if lane == "owner" and phase == "new":
                owner = measure_owner(topo, where, selectors, sdk, prods, repo, env, temp)
            obj, meta, bits, record = physical_rows(where, rows, bad, root / "cgu-originals", cached)
            all_cgus[lane, phase] = (obj, meta, bits)
    p.need(
        raw["observe"] == raw["capture"],
        "effective test histories did not start from the same ordinary compiler arguments",
    )
    p.need(
        {f.name for f in (root / "cgu-originals").iterdir()} == {h + ".gz" for h in cached}
        and {f.name for f in (root / "client-bodies").iterdir()} == {h + ".gz" for h in binaries},
        "unexpected or missing stored originals",
    )
    old, _, ob = all_cgus["capture", "old"]
    new, _, nb = all_cgus["capture", "new"]
    empty, _, eb = all_cgus["capture-empty", "new"]
    p.need(set(ob) == set(old) and set(eb) == set(empty), "incomplete genuinely cold pre-LLVM coverage")
    shared = set(nb) & set(ob)
    exactbc = {k for k in shared if ob[k] == nb[k]}
    exacto = {k for k in shared if old[k] == new[k]}
    strict = {
        k
        for k in exactbc & exacto
        if eb.get(k) == nb[k]
        and all(
            all_cgus[lane, phase][0].get(k) == new[k]
            for lane, phase in (
                ("plain", "old"),
                ("plain", "new"),
                ("observe", "old"),
                ("observe", "new"),
                ("reference", "new"),
                ("capture-empty", "new"),
            )
        )
    }
    primary = all_clocks["plain/new"]
    (workspace,) = [r["instructions"] for r in owner["compilers"] if r["crate"] == p.OWNER]
    residual = owner["whole"] - workspace
    p.need(residual > 0, "missing outer work")
    owner["workspace_share"] = workspace / owner["whole"]
    owner["ideal_ceiling_if_all_workspace_rustc_work_disappeared"] = owner["whole"] / residual
    executed = execute_clients(root, typed, gold, temp) if execute else None
    return {
        "qualified": True,
        "enrollment": enrollment,
        "graph_compile_units": sum(graph.values()),
        "whole_user_instructions": all_clocks,
        "observer_over_plain": {l: all_clocks[l + "/new"] / primary for l in ("observe", "capture")},
        "separate_owner_clock": owner,
        "rustc_events": physical_counts,
        "complete_client_elfs": typed,
        "independently_executed_distinct_clients": executed,
        "all_client_stdout_checks": len(typed) * 3,
        "full_old_modules": len(ob),
        "full_new_modules": len(eb),
        "warm_newly_emitted": len(nb),
        "warm_rebuilt_keys": sorted(nb),
        "comparable_old_keys": len(shared),
        "unchanged_preoptimization": sorted(exactbc),
        "unchanged_native": sorted(exacto),
        "strictly_identical_on_both_empty_and_plain": sorted(strict),
        "other_emitted": sorted(set(nb) - strict),
        "new_compiler_treatments": 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("collector")
    ap.add_argument("contract")
    ap.add_argument("head")
    ap.add_argument(
        "--execute",
        action="store_true",
        help="run all verified typed ELFs again on a compatible GNU x86-64 host",
    )
    ns = ap.parse_args()
    path = Path(ns.original).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="ohm-option-read-") as d:
        args = Path(ns.collector).resolve(), Path(ns.contract).resolve(), ns.head, Path(d), ns.execute
        if path.is_dir():
            result = verify(path, *args)
        else:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                p.need(
                    len(set(names)) == len(names)
                    and len(names) <= 100000
                    and sum(a.file_size for a in z.infolist()) <= 3 << 30
                    and all(not n.startswith("/") and ".." not in Path(n).parts for n in names),
                    "unsafe ZIP roster",
                )
                result = verify(zipfile.Path(z), *args)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
