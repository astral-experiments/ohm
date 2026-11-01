"""Independently reopen the official contact ZIP, including both whole executables and their true clients."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as q
import instructions as policy


def official(folder, run, head, archives):
    def load(name):
        return json.loads((folder / (name + ".json")).read_bytes())

    info, jobs, artifacts = map(load, ("run", "jobs", "artifacts"))
    q.need(
        (
            info["id"],
            info["run_attempt"],
            info["head_sha"],
            info["head_branch"],
            info["path"],
            info["event"],
            info["conclusion"],
            info["status"],
        )
        == (
            run,
            1,
            head,
            policy.BRANCH,
            ".github/workflows/ci.yml",
            "workflow_dispatch",
            "success",
            "completed",
        )
        and info["repository"]["full_name"]
        == info["head_repository"]["full_name"]
        == "astral-experiments/ohm"
        and jobs["total_count"]
        == len(jobs["jobs"])
        == artifacts["total_count"]
        == len(artifacts["artifacts"])
        == 2,
        "unqualified official run",
    )
    result = {}
    steps = (
        "Bind sources and reserve the runner",
        "Restore exact compilers and the original native contact",
        "Measure the two registered integration histories",
    )
    for pos in policy.ORDER:
        (job,) = [a for a in jobs["jobs"] if a["name"] == "CTFE integration hardware " + pos]
        (a,) = [x for x in artifacts["artifacts"] if x["name"] == "ctfe-integration-hardware-" + pos]
        q.need(
            (
                job["run_id"],
                job["run_attempt"],
                job["head_sha"],
                job["status"],
                job["conclusion"],
                job["labels"],
            )
            == (run, 1, head, "completed", "success", ["namespace-profile-ubuntu-24-04-16"])
            and [s["name"] for s in job["steps"] if s["name"] in steps and s["conclusion"] == "success"]
            == list(steps)
            and (a["workflow_run"]["id"], a["workflow_run"]["head_sha"], a["expired"])
            == (run, head, False)
            and 0 < a["size_in_bytes"] == archives[pos].stat().st_size < 2**30
            and job["runner_name"],
            "different official job or artifact",
        )
        with archives[pos].open("rb") as f:
            data = hashlib.file_digest(f, "sha256").hexdigest()
        q.need(a["digest"] == "sha256:" + data, "official archive bytes differ")
        result[pos] = dict(
            position=pos,
            run=run,
            head=head,
            attempt=1,
            job=job["id"],
            runner=job["runner_name"],
            artifact=a["id"],
            sha256=data,
            bytes=a["size_in_bytes"],
        )
    q.need(
        len({v["job"] for v in result.values()}) == len({v["runner"] for v in result.values()}) == 2,
        "official jobs reused a worker",
    )
    return result


def cargo(z, p, root, cert, rc):
    def raw(name):
        return gzip.decompress(z.read(p + "/" + name + ".gz"))

    rec = json.loads(raw("cargo.json"))
    out, err = raw("cargo.stdout"), raw("cargo.stderr")
    q.need(
        rec["argv"] == q.COMMAND
        and rec["env"] == cert["env"]
        and rec["cwd"] == str(root / "ruff")
        and rec["stdin_sha256"] == q.sha(b"")
        and rec["expected"] == rec["exit"] == rc
        and (rec["stdout_sha256"], rec["stderr_sha256"]) == (q.sha(out), q.sha(err)),
        "incorrect ordinary Cargo",
    )
    stream = list(map(json.loads, out.splitlines()))
    q.need(
        stream[-1] == {"reason": "build-finished", "success": not rc}
        and sum(v["reason"] == "build-finished" for v in stream) == 1,
        "incomplete Cargo result",
    )
    errors = [
        v for v in stream if v["reason"] == "compiler-message" and v["message"]["level"] == "error"
    ]
    if rc:
        q.need(
            json.loads(raw("diagnostics.json")) == errors,
            "raw Cargo diagnostic and retained error table differ",
        )
        tagged = [v for v in errors if v["message"].get("code")]
        q.need(
            len(tagged) == 1
            and tagged[0]["target"]["name"] == "ruff_python_parser"
            and tagged[0]["message"]["code"]["code"] == "E0308"
            and any(
                v["is_primary"]
                and v["file_name"] == "crates/ruff_python_parser/src/lib.rs"
                and v["line_start"] == 626
                and any("ohm_branch_switch_invalid" in t["text"] for t in v["text"])
                for v in tagged[0]["message"]["spans"]
            ),
            "incorrect parser diagnostic",
        )
        q.need(
            all(
                v in tagged
                or (not v["message"]["spans"] and v["message"]["message"].startswith("aborting due to "))
                for v in errors
            ),
            "additional unexpected error",
        )
    else:
        q.need(not errors, "an error accompanied a successful Cargo")
    q.need(
        all(
            type(v["fresh"]) is bool and v["filenames"]
            for v in stream
            if v["reason"] == "compiler-artifact"
        ),
        "missing typed outputs",
    )
    return rec, stream


def selected(z, p, stream, phys, prior, cold, product, sel, root):
    D = lambda f: json.loads(z.read(p + "/" + f))
    proof = D("selected.json")
    paths, owners, provider, inputs = (proof[k] for k in ("paths", "owners", "reader", "operands"))
    actual = [v for v in stream if v["reason"] == "compiler-artifact" and v["executable"]]
    names = {
        "cli": ("ruff", "bin", "src/main.rs"),
        "harness": ("integration_test", "test", "tests/integration_test.rs"),
    }
    q.need(
        len(actual) == len(owners) == len(paths) == 2
        and set(names) == set(owners) == set(paths)
        and set(proof["terminal_files"]) == set(names)
        and paths["cli"] == str(root / "work/target/debug/ruff"),
        "undeclared output",
    )
    for k, (name, kind, src) in names.items():
        (art,) = [
            m
            for m in actual
            if (m["target"]["name"], m["target"]["kind"], m["target"]["src_path"])
            == (name, [kind], str(root / "ruff/crates/ruff" / src))
        ]
        q.need(
            art["executable"] == paths[k] and Path(paths[k]).is_relative_to(root / "work"),
            "foreign selected ELF",
        )
        owner = owners[k]
        full = (
            []
            if phys is None
            else [
                r
                for r in phys["rustcs"]
                if r["mode"] == "full"
                and r["crate"] == name
                and any(
                    a == "crates/ruff/" + src or a.endswith("/crates/ruff/" + src) for a in r["argv"]
                )
                and ("--test" in r["argv"]) == (k == "harness")
            ]
        )
        if full:
            (r,) = full
            q.need(
                r["pid"] == owner["pid"]
                and sel.selected_externs(r["argv"]) == owner["externs"]
                and "-Zohm-check-relink-inputs" in r["argv"]
                and any(a in ("ohm-branch-cache=yes", "-Zohm-branch-cache=yes") for a in r["argv"])
                and sum(a.startswith(("incremental=", "-Cincremental=")) for a in r["argv"]) == 1,
                "wrong physical owner options",
            )
        else:
            q.need(
                (phys is None or not cold)
                and owner["pid"] is None
                and owner["externs"] == prior[k]["externs"],
                "missing or mislabeled emitter",
            )
        records = proof["terminal_files"][k]
        expected = []
        for ld in phys["wild_processes"] if phys is not None else []:
            (link_rust,) = [r for r in phys["rustcs"] if r["event"] == ld["rustc_event"]]
            # The package also owns a "ruff" lib. It cannot own the installed CLI link or its output basename.
            if link_rust["crate"] == name and re.fullmatch(
                re.escape(name) + r"(?:-[0-9a-f]{16})?", Path(ld["output"]).name
            ):
                expected.append({"pid": ld["pid"], "path": ld["output"]})
        q.need(
            expected == owner["linked_by"]
            and (len(expected) == 1 if cold and phys is not None else len(expected) <= 1)
            and set(records) == {paths[k], *(v["path"] for v in expected)},
            "unaccounted final link",
        )
        for label, (dev, ino, size, digest) in records.items():
            q.need(
                type(dev) is type(ino) is int
                and dev > 0
                and ino > 0
                and (size, digest) == (product[k]["size"], product[k]["whole"]),
                "observed GNU link operand does not equal the complete installed ELF",
            )
    q.need(
        set(provider) == set(sel.LIBS)
        and all(set(o["externs"]) == set(sel.LIBS) for o in owners.values()),
        "unbound inputs",
    )
    expected_paths = set()
    ext = []
    for name in sel.LIBS:
        r = provider[name]
        (art,) = [
            m
            for m in stream
            if m["reason"] == "compiler-artifact"
            and m["target"]["name"] == name
            and "lib" in m["target"]["kind"]
            and r["path"] in m["filenames"]
        ]
        q.need(
            (art["features"], art["profile"]) == (r["features"], r["profile"])
            and inputs[r["path"]][2:] == [r["bytes"], r["sha256"]]
            and r["bytes"] > 0,
            "wrong selected Cargo provider",
        )
        expected_paths.add(r["path"])
        sides = set()
        for k in names:
            args = owners[k]["externs"][name]
            expected_paths.add(args["rlib"])
            q.need(
                inputs[args["rlib"]] == inputs[r["path"]], "consumer points to different physical rlib"
            )
            if args["rmeta"]:
                sides.add(args["rmeta"])
        q.need(
            set(r["actual_rmeta"]) == sides
            and all(n in art["filenames"] and inputs[n][3] == r["actual_rmeta"][n] for n in sides),
            "unexpected actual rmeta inputs",
        )
        expected_paths.update(sides)
        ext.append(name + "=" + r["path"])
    q.need(
        set(inputs) == expected_paths
        and all(
            Path(k).is_relative_to(root / "work")
            and v[0] > 0
            and v[1] > 0
            and v[2] > 0
            and re.fullmatch("[0-9a-f]{64}", v[3])
            for k, v in inputs.items()
        ),
        "unregistered input",
    )
    for label in ("reader-compile", "layout-64", "layout-56"):
        cmd = json.loads(gzip.decompress(z.read(p + "/" + label + ".json.gz")))
        args = cmd["argv"]
        q.need(
            args[:2] == ["rustc", "+ohm"]
            and [args[i + 1] for i, a in enumerate(args) if a == "--extern"] == ext,
            "typed oracle used another dependency",
        )
        for field in ("stdout", "stderr"):
            q.need(
                q.sha(gzip.decompress(z.read(f"{p}/{label}.{field}.gz"))) == cmd[field + "_sha256"],
                "changed typed command stream",
            )
        if label == "reader-compile":
            q.need(
                cmd["exit"] == 0 and args[-2:] == ["-o", str(root / "full-cli-reader/reader")],
                "missing actual linked reader",
            )
    rr = json.loads(gzip.decompress(z.read(p + "/reader-run.json.gz")))
    q.need(
        rr["argv"] == [str(root / "full-cli-reader/reader")]
        and rr["exit"] == 0
        and all(
            rr[x + "_sha256"] == q.sha(gzip.decompress(z.read(p + "/reader-run." + x + ".gz")))
            for x in ("stdout", "stderr")
        ),
        "incorrect external reader execution",
    )
    return paths, owners


def full_suite(z, p, paths, cwd, suite, processes, prefix):
    def read(label):
        return json.loads(z.read(f"{p}/{label}.json"))

    def body(label, stream):
        return gzip.decompress(z.read(f"{p}/{label}.{stream}.gz"))

    lib = read("libtest")
    harness, cli = (paths[k] for k in ("harness", "cli"))
    package = str(Path(cwd) / "crates/ruff")
    commands = {
        "libtest-list": [harness, "--list", "--format", "pretty"],
        "libtest-full": [harness, "--test-threads=1", "--color", "never"],
        "dev-rule": [cli, "rule", "RUF950"],
    }
    names = suite.inventory(body("libtest-list", "stdout"))
    for label in (*commands, *suite.EXACT):
        rec = read(label)
        q.need(
            (rec["exit"], rec["cwd"], rec["insta_root"], rec["cargo_bin"]) == (0, package, cwd, cli)
            and all(q.sha(body(label, k)) == rec[k] for k in ("stdout", "stderr")),
            "changed suite process or wrong BIN",
        )
        argv = rec["argv"]
        if label in commands:
            q.need(argv == [*prefix, *commands[label]], "wrong executed suite/CLI argument list")
        else:
            rawroot = Path(cwd).parent / "logs" / p
            expected = [
                "strace",
                "-f",
                "-qq",
                "--seccomp-bpf",
                "-s",
                "262144",
                "-e",
                "trace=execve,execveat",
                "-o",
                str(rawroot / (label + ".exec")),
                harness,
                "--exact",
                label,
                "--test-threads=1",
                "--color",
                "never",
            ]
            q.need(argv == [*prefix, *expected], "other executable or test case was traced")
            records = processes.execs(
                io.StringIO(gzip.decompress(z.read(p + "/" + label + ".exec.gz")).decode())
            )
            (hp, he, ha), (cp, ce, ca) = records
            reg = lib["children"][label]
            q.need(
                hp != cp
                and (he, ha, ce)
                == (harness, [harness, "--exact", label, "--test-threads=1", "--color", "never"], cli)
                and ca[:2] == [cli, "check"]
                and "--isolated" in ca
                and "--no-cache" in ca
                and any(
                    (
                        a == "@!.txt"
                        if label == suite.EXACT[1]
                        else a.startswith("@/") and a.endswith("/file_paths.txt")
                    )
                    for a in ca
                )
                and reg == dict(harness_pid=hp, ruff_pid=cp, ruff_path=ce, argv=ca),
                "wrong real argfile execution",
            )
            suite.verdict(body(label, "stdout"), [label], 95)
    suite.verdict(body("libtest-full", "stdout"), names)
    ruf = body("dev-rule", "stdout")
    q.need(
        b"ruf950" in ruf.lower()
        and lib["rule"] == q.sha(ruf)
        and lib["inventory"] == suite.LIST_SHA
        and lib["total"] == lib["passed"] == 96
        and lib["package"] == package
        and set(lib["children"]) == set(suite.EXACT),
        "missing real feature or suite case",
    )
    return {"inventory": suite.LIST_SHA, "names": sorted(names), "dev_rule": q.sha(ruf)}


def stubs(z, p, s, cli, cwd, edited):
    result = {}
    for k in s.CASES:
        tag = p + "/stub-" + k
        row = json.loads(z.read(tag + ".json"))
        out, err = [gzip.decompress(z.read(tag + "." + ext + ".gz")) for ext in ("stdout", "stderr")]
        q.need(
            row
            == dict(
                argv=[cli, *s.argv(k)],
                cwd=cwd,
                exit=row["exit"],
                stdin=q.sha(s.SOURCE),
                stdout=q.sha(out),
                stderr=q.sha(err),
            ),
            "wrong PYI009 input, sources, executable or recorded streams",
        )
        result[k] = s.verdict(k, edited, row["exit"], out, err, cwd)
    return result


def read(path, meta, kernel, ruff, reference, calibrator, observers):
    ctfe, sel, suite = q.packages()
    import reopen as n
    import contact_review
    import pilot as local

    semantic = q.semantics()
    source_receipt, _ = n.corpus.source(ruff)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        q.need(
            len(names) == len(z.infolist())
            and all(not Path(f).is_absolute() and ".." not in f.split("/") for f in names)
            and "failure.txt" not in names
            and "meter-ready.json" in names,
            "refusal, ambiguous archive or missing calibration",
        )
        clocks = {f"{a}/{p}/clock.json" for a in q.ARMS for p in q.HISTORY}
        observed = {f"{a}/{p}" for a in q.ARMS for p in (*q.EMPTY, "semantic-edit", "semantic-empty")}
        q.need(
            {n for n in names if n.endswith("/clock.json")} == clocks
            and {
                n.removesuffix("/kernel.tsv.gz")
                for n in names
                if n.endswith("/kernel.tsv.gz") and n.split("/")[0] in q.ARMS
            }
            == observed
            and {
                n.removesuffix("/native-execs.json.gz")
                for n in names
                if n.endswith("/native-execs.json.gz") and n.split("/")[0] in q.ARMS
            }
            == observed,
            "missing or overlapping counter and native scopes",
        )
        expected_calls = {
            a + "/" + p + "/cargo.json.gz"
            for a in q.ARMS
            for p in (*q.PHASES, "semantic-edit", "semantic-empty")
        }
        q.need(
            {f for f in names if f.endswith("/cargo.json.gz")} == expected_calls,
            "missing or repeated official Cargo invocation",
        )
        D = lambda key: n.dataset(z, key)
        pos = D("position.json")
        q.need(
            (pos["mode"], pos["order"], pos["head"], pos["run"], pos["plan"], pos["command"])
            == (
                "counter-pilot",
                list(policy.ORDER[meta["position"]]),
                meta["head"],
                meta["run"],
                q.sha((q.HERE / "PLAN.md").read_bytes()),
                q.COMMAND,
            )
            and q.sha(z.read("PLAN.md")) == pos["plan"]
            and D("ruff-inputs.json") == source_receipt,
            "wrong endpoint, order or source",
        )
        policy.fresh_boot(pos["boot"])
        q.need(
            (pos["position"], pos["runner"]) == (meta["position"], meta["runner"])
            and D("prior-native-contact.json") == reference,
            "different job or prior native control",
        )
        meter = D("meter-ready.json")
        n.replay_controls.PACKAGING, n.replay_controls.OBSERVER = calibrator, observers
        calibration = n.replay_controls.calibration(z, pos["boot"])
        hardware = n.hardware.verify(z, calibration, meter)
        q.need(
            meter["boot"] == pos["boot"]
            and calibration["affinity"] == meter["affinity"]
            and meter["observer"] == n.replay_controls.OBS
            and meter["calibrator"] == n.replay_controls.CAL,
            "wrong hardware acquisition source/boot",
        )
        boot_resources = D("bootstrap-resources.json")
        session = D("resource/resources.json")
        for state, mem, disk in [(boot_resources, 32, 32), (session["start"], 16, 4)]:
            cgroups = state["cgroups"]
            q.need(
                state["effective"] == min([state["physical"], *[v for _, v in cgroups if v is not None]])
                and state["effective"] >= mem * 2**30
                and state["work"] >= disk * 2**30
                and state["receipts"] >= max(6, disk) * 2**30,
                "incorrect physical bootstrap or entry floors",
            )
        minimum = contact_review.host_guards(z, pos)
        binding = n.kernel_binding(z, pos["boot"], "contact", kernel, None)
        kit = n.sdk_pair(z)
        eax = D("initial/eacces.json")
        eout = gzip.decompress(z.read("initial/eacces.stdout.gz"))
        eerr = gzip.decompress(z.read("initial/eacces.stderr.gz"))
        q.need(
            eax["exit"] == 0
            and eax["stdout"] == q.sha(eout)
            and eax["stderr"] == q.sha(eerr)
            and not eerr
            and re.fullmatch(rb"\d+ file EACCES directory EACCES\n", eout),
            "permission-negative not exercised",
        )
        privileges = (
            [
                "setpriv",
                "--bounding-set=-dac_override,-dac_read_search",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
                "--",
            ]
            if eout.startswith(b"0 ")
            else []
        )
        q.need(eax["argv"][: len(privileges)] == privileges, "different privileges in suite")
        refs, records, bodies, separate, clean_owners = {}, {}, {}, {}, {}
        installed_hashes = set()
        for arm in q.ARMS:
            cert, root = n.active(z, arm, arm, kit[arm[0]]["files"])
            previous = {}
            sem_warm = None
            rows = {}
            sem_cert = []
            for phase in (*q.PHASES, "semantic-edit", "semantic-empty"):
                p = f"{arm}/{phase}"
                d = lambda f: D(p + "/" + f)
                cold = phase in (*q.EMPTY, "Y-B", "semantic-empty")
                semantic_phase = phase.startswith("semantic-")
                if cold:
                    previous = {}
                    fresh = d("fresh.json")
                    q.need(
                        set(fresh) == {str(root / "work/target"), str(root / "work/build")}
                        and len({tuple(v) for v in fresh.values()}) == 2
                        and all(
                            len(v) == 2 and all(type(i) is int and i > 0 for i in v)
                            for v in fresh.values()
                        ),
                        "missing distinct native empty roots",
                    )
                else:
                    q.need(p + "/fresh.json" not in names, "warm visit reset its roots")
                state = d("source.json")
                if semantic_phase:
                    expected = dict(
                        ref=n.BRANCH["B"],
                        commit=n.metrics.REVS["B"],
                        tree=n.corpus.TREES["B"],
                        modified=sorted([semantic.AST, n.NODE]),
                        body=semantic.AFTER,
                        comment=n.AST["edited"],
                        parser=semantic.GOOD,
                    )
                    q.need(state == expected, "incorrect semantic edit")
                    branch = "B"
                else:
                    branch, _ = n.source_state(state, phase, "return")
                    if phase == "unchanged":
                        q.need(
                            state == D(arm + "/comment/source.json"), "changed source before unchanged"
                        )
                rc = 101 if phase == "invalid" else 0
                cmd, events = cargo(z, p, root, cert, rc)
                n.driver(z, arm, p, arm, cert)
                counted = phase in q.HISTORY
                if counted:
                    clock = d("clock.json")
                    policy.timed(clock, phase)
                    q.need(
                        cmd["observer_argv"]
                        == [meter["plain"], str(root / "logs" / p / "clock.json"), *q.COMMAND]
                        and meter["plain"] == str(root / "logs/observers/plain"),
                        "different complete untraced command or counter binary",
                    )
                    real = phy = wild = None
                else:
                    with patch.object(n, "CARGO", q.COMMAND), patch.object(
                        n.kernel, "COMMAND", q.COMMAND
                    ):
                        physical = n.physical(z, p, arm, cert, cmd, rc)
                    raw = gzip.decompress(z.read(p + "/kernel.tsv.gz"))
                    family = n.kernel.parse(
                        raw, expected_sha=physical["kernel"], expected_code=rc, expected_schema=3
                    )
                    q.install_boundary(family["execs"])
                    installed_hashes.update(r["image"]["sha256"] for r in family["execs"])
                    real = d("native-execs.json.gz")
                    phy = q.identities(real)
                    wild = q.link_outputs(real)
                typed, dirty = sel.roster(events, Path(cmd["cwd"]))
                q.need(d("roster.json.gz") == dict(units=typed, dirty=dirty), "wrong typed inventory")
                policy.rosters_admit(reference, arm, phase, typed, dirty)
                store = d("storage.json")
                allocated = n.metrics.allocation(
                    d("path-inodes.json.gz"), store, d("allocation-readers.json")
                )
                q.need(
                    min(store["roots"].values()) > 0
                    and store["all_inodes"] > 1000
                    and (not cold or (len(dirty) == 390 and store["packed_files"] == 0)),
                    "incorrect physical storage or dirty cold",
                )
                if not semantic_phase:
                    rec = dict(
                        phase=phase,
                        arm=arm,
                        status=rc,
                        allocated=allocated,
                        typed=len(typed),
                        dirty=len(dirty),
                        physical=phy,
                        wild_outputs=wild,
                    )
                if counted:
                    rec["clock"] = clock
                if rc:
                    q.need(
                        sorted(d("failed.json")) == sorted(store["failed_sessions"]),
                        "lost incomplete session after invalid compile",
                    )
                else:
                    products = n.replay_native.native_verdict(z, p, branch)
                    images = {k: products[k] for k in ("cli", "reader")} | {
                        "harness": d("harness-elf.json")
                    }
                    if counted:
                        ref = q.reference(phase)
                        comparison = clean_owners[arm, ref]
                        rec["external_owner_witness"] = ref
                        q.need(
                            d("selected.json")["owners"] == policy.reference_owners(comparison),
                            "counted Cargo inputs not bound to same-boot same-role empty owner",
                        )
                    else:
                        comparison = previous
                    paths, previous = selected(z, p, events, real, comparison, cold, images, sel, root)
                    if phase in q.EMPTY:
                        clean_owners[arm, phase] = previous
                    q.need(len(typed) == 390 and not store["failed_sessions"], "incomplete native build")
                    for k, v in images.items():
                        n.verified_body(z, k, v, bodies)
                    whole = {k: v["whole"] for k, v in images.items()}
                    if semantic_phase:
                        q.need(
                            all(previous[k]["linked_by"] for k in ("harness", "cli"))
                            and any(
                                r["crate"] == "ruff_python_ast" and r["mode"] == "full"
                                for r in real["rustcs"]
                            )
                            and whole["cli"] != rows["repair"]["products"]["cli"],
                            "no true semantic recompilation/relink",
                        )
                        signs = stubs(z, p, semantic, paths["cli"], cmd["cwd"], True)
                        q.need(
                            d("semantic.json")
                            == dict(
                                phase=phase,
                                products=whole,
                                stubs=signs,
                                allocated=allocated,
                                physical=phy,
                                wild_outputs=wild,
                            ),
                            "wrong semantic report",
                        )
                        current = images, typed, n.behavior(products), signs
                        if sem_warm is not None:
                            q.need(current == sem_warm, "edited native body did not match own empty")
                        sem_warm = current
                        sem_cert.append(q.sha(z.read(p + "/semantic.json")))
                        continue
                    oracle = full_suite(
                        z, p, paths, cmd["cwd"], suite, local.original.processes, privileges
                    )
                    behavior = n.behavior(products) | {"suite": oracle}
                    (outdir,) = {
                        v["out_dir"]
                        for v in events
                        if v.get("reason") == "build-script-executed"
                        and "tikv-jemalloc-sys" in v["package_id"]
                    }
                    native_state = (typed, images, behavior, outdir)
                    if phase in q.EMPTY:
                        refs[arm, phase] = native_state
                    else:
                        q.need(
                            native_state == refs[arm, q.reference(phase)],
                            "original products/behavior or path differ from own empty",
                        )
                    if phase == "repair":
                        stubs(z, p, semantic, paths["cli"], cmd["cwd"], False)
                        # The inherited worker records the failed-session grace observation before issuing TOML Cargo.
                        grace = d("grace.json")
                        invalid = D(arm + "/invalid/failed.json")
                        cutoff = (
                            max((v["created_ns"] for v in invalid.values()), default=0) + 11_000_000_000
                        )
                        q.need(
                            grace["sessions"] == invalid
                            and grace["cutoff_ns"] == cutoff
                            and grace["rustc_gc_grace_ns"] == 10_000_000_000
                            and grace["ready_ns"] >= max(cutoff, grace["read_ns"]),
                            "wrong failed-session grace before repair",
                        )
                    rec.update(products=whole, suite_count=96)
                q.need(d("visit.json") == rec, "reported visit differs from raw observations")
                rows[phase] = rec
            q.need(
                all(
                    rows["X-A"]["products"][k] != rows["X-B"]["products"][k]
                    for k in ("cli", "harness", "reader")
                ),
                "historical products unchanged",
            )
            separate[arm] = sem_cert
            records[arm] = rows
        for key in q.EMPTY:
            e, c = (refs[arm, key] for arm in q.ARMS)
            q.need(
                e[0] == c[0]
                and e[2] == c[2]
                and all(
                    e[1][r][f] == c[1][r][f]
                    for r in ("cli", "reader", "harness")
                    for f in ("executable", "loads")
                ),
                "cross-role clean differences",
            )
        q.need(
            {f for f in names if f.startswith("native-bodies/") and not f.endswith("/")}
            == {"native-bodies/" + key[1] + ".zst" for key in bodies},
            "unexplained or missing full native body",
        )
        q.need(
            installed_hashes.isdisjoint(key[1] for key in bodies),
            "an actual selected CLI, libtest or native ABI reader ran inside an observed Cargo call",
        )
        result = policy.outcomes(records)
        q.need(
            D("complete.json")
            == dict(
                qualified=True,
                scored=14,
                schema=3,
                phases=list(q.PHASES),
                visits=records,
                semantic=separate,
                observed=result,
                prerequisite=policy.REGISTERED,
            ),
            "incorrect terminal gate",
        )
        return dict(
            official=meta,
            boot=pos["boot"],
            qualified=True,
            position=meta["position"],
            runner=meta["runner"],
            job=meta["job"],
            run=meta["run"],
            head=meta["head"],
            order=pos["order"],
            prerequisite=policy.REGISTERED,
            hardware=hardware,
            scored=14,
            commands=24,
            unchanged_histories=2,
            complete_96_case_suites=18,
            expected_E0308=2,
            semantic_commands=4,
            unique_whole_elfs=sorted({v[1] for v in bodies}),
            resources=minimum,
            source=q.KERNEL,
            observer=binding["observer_sha256"],
            records=records,
            observed=result,
        )


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("official_folder", type=Path)
    for key in ("01", "02", "prior", "original_source", "kernel", "ruff", "calibrator", "observers"):
        a.add_argument("--" + key.replace("_", "-"), dest=key, type=Path, required=True)
    a.add_argument("--run", type=int, required=True)
    a.add_argument("--head", required=True)
    args = a.parse_args()
    q.check_source(args.head)
    archives = {p: getattr(args, p) for p in policy.ORDER}
    require = policy.raw_contact(args.prior, args.original_source, args.ruff, args.kernel)
    officials = official(args.official_folder, args.run, args.head, archives)
    results = {
        p: read(
            archives[p], officials[p], args.kernel, args.ruff, require, args.calibrator, args.observers
        )
        for p in policy.ORDER
    }
    print(json.dumps({"positions": results, "paired": policy.pair(results)}, sort_keys=True, indent=2))
