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
import donor_integrity as integrity


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
        v
        for v in stream
        if v["reason"] == "compiler-message" and v["message"]["level"] == "error"
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
                or (
                    not v["message"]["spans"]
                    and v["message"]["message"].startswith("aborting due to ")
                )
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
    paths, owners, provider, inputs = (
        proof[k] for k in ("paths", "owners", "reader", "operands")
    )
    actual = [
        v for v in stream if v["reason"] == "compiler-artifact" and v["executable"]
    ]
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
            art["executable"] == paths[k]
            and Path(paths[k]).is_relative_to(root / "work"),
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
                    a == "crates/ruff/" + src or a.endswith("/crates/ruff/" + src)
                    for a in r["argv"]
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
                and any(
                    a in ("ohm-branch-cache=yes", "-Zohm-branch-cache=yes")
                    for a in r["argv"]
                )
                and sum(
                    a.startswith(("incremental=", "-Cincremental=")) for a in r["argv"]
                )
                == 1,
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
            (link_rust,) = [
                r for r in phys["rustcs"] if r["event"] == ld["rustc_event"]
            ]
            # The package also owns a "ruff" lib. It cannot own the installed CLI link or its output basename.
            if link_rust["crate"] == name and re.fullmatch(
                re.escape(name) + r"(?:-[0-9a-f]{16})?", Path(ld["output"]).name
            ):
                expected.append({"pid": ld["pid"], "path": ld["output"]})
        q.need(
            expected == owner["linked_by"]
            and (
                len(expected) == 1 if cold and phys is not None else len(expected) <= 1
            )
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
                inputs[args["rlib"]] == inputs[r["path"]],
                "consumer points to different physical rlib",
            )
            if args["rmeta"]:
                sides.add(args["rmeta"])
        q.need(
            set(r["actual_rmeta"]) == sides
            and all(
                n in art["filenames"] and inputs[n][3] == r["actual_rmeta"][n]
                for n in sides
            ),
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
                q.sha(gzip.decompress(z.read(f"{p}/{label}.{field}.gz")))
                == cmd[field + "_sha256"],
                "changed typed command stream",
            )
        if label == "reader-compile":
            q.need(
                cmd["exit"] == 0
                and args[-2:] == ["-o", str(root / "full-cli-reader/reader")],
                "missing actual linked reader",
            )
    rr = json.loads(gzip.decompress(z.read(p + "/reader-run.json.gz")))
    q.need(
        rr["argv"] == [str(root / "full-cli-reader/reader")]
        and rr["exit"] == 0
        and all(
            rr[x + "_sha256"]
            == q.sha(gzip.decompress(z.read(p + "/reader-run." + x + ".gz")))
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
            (rec["exit"], rec["cwd"], rec["insta_root"], rec["cargo_bin"])
            == (0, package, cwd, cli)
            and all(q.sha(body(label, k)) == rec[k] for k in ("stdout", "stderr")),
            "changed suite process or wrong BIN",
        )
        argv = rec["argv"]
        if label in commands:
            q.need(
                argv == [*prefix, *commands[label]],
                "wrong executed suite/CLI argument list",
            )
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
            q.need(
                argv == [*prefix, *expected], "other executable or test case was traced"
            )
            records = processes.execs(
                io.StringIO(
                    gzip.decompress(z.read(p + "/" + label + ".exec.gz")).decode()
                )
            )
            (hp, he, ha), (cp, ce, ca) = records
            reg = lib["children"][label]
            q.need(
                hp != cp
                and (he, ha, ce)
                == (
                    harness,
                    [harness, "--exact", label, "--test-threads=1", "--color", "never"],
                    cli,
                )
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
        out, err = [
            gzip.decompress(z.read(tag + "." + ext + ".gz"))
            for ext in ("stdout", "stderr")
        ]
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


def official(folder, raw, head):
    """Verify the one attempt, its pre-outcome job enrollment and the complete transferred bytes."""
    get = lambda name: json.loads((folder / (name + ".json")).read_bytes())
    r, j, a, before = (get(k) for k in ("run", "jobs", "artifacts", "pre-outcome"))
    (job,), (art,) = j["jobs"], a["artifacts"]
    repo = "astral-experiments/ohm"
    q.need(
        j["total_count"] == a["total_count"] == 1
        and int(before["run"]) == r["id"]
        and before["job"] == job["id"]
        and before["head"] == head
        and before["assets"] == 0
        and (r["repository"]["full_name"], r["head_repository"]["full_name"])
        == (repo, repo)
        and (
            r["head_sha"],
            r["head_branch"],
            r["event"],
            r["run_attempt"],
            r["path"],
            r["conclusion"],
        )
        == (
            head,
            q.BRANCH,
            "workflow_dispatch",
            1,
            ".github/workflows/ci.yml",
            "success",
        )
        and (
            job["run_id"],
            job["head_sha"],
            job["run_attempt"],
            job["name"],
            job["labels"],
            job["status"],
            job["conclusion"],
        )
        == (
            r["id"],
            head,
            1,
            "GNU E D integration fast-forward contact",
            ["namespace-profile-ubuntu-24-04-16"],
            "completed",
            "success",
        )
        and all(x["conclusion"] == "success" for x in job["steps"])
        and art["workflow_run"]["id"] == r["id"]
        and art["workflow_run"]["head_sha"] == head
        and art["name"] == "gnu-donor-integration-fast-forward-contact"
        and not art["expired"]
        and art["size_in_bytes"] == raw.stat().st_size,
        "wrong, failed or substituted official job",
    )
    with raw.open("rb") as f:
        sha = hashlib.file_digest(f, "sha256").hexdigest()
    q.need(art["digest"] == "sha256:" + sha, "official original digest mismatch")
    return dict(
        run=r["id"],
        job=job["id"],
        runner=job["runner_name"],
        head=head,
        attempt=1,
        artifact=art["id"],
        sha256=sha,
        bytes=art["size_in_bytes"],
    )


def read(raw, meta, kernel, ruff, calibrator, observers):
    ctfe, sel, suite = q.packages()
    import pilot as local
    import reopen as n
    import contact_review

    source, _ = n.corpus.source(ruff)
    with zipfile.ZipFile(raw) as z:
        names = set(z.namelist())
        q.need(
            len(names) == len(z.infolist())
            and all(
                not Path(k).is_absolute() and ".." not in Path(k).parts for k in names
            )
            and "failure.txt" not in names,
            "failed or ambiguous archive",
        )
        D = lambda p: n.dataset(z, p)
        prefixes = [
            (arm, l, p, f"{arm}/{l}/{p}")
            for arm in policy.ORDER
            for l, p in policy.ACTIONS
        ]

        def expected(file, pred):
            q.need(
                {v for v in names if v.endswith("/" + file)}
                == {p + "/" + file for a, l, h, p in prefixes if pred(l, h)},
                "wrong complete inventory " + file,
            )

        expected("cargo.json.gz", lambda l, p: True)
        expected("clock.json", policy.is_counter)
        expected("kernel.tsv.gz", lambda l, p: not policy.is_counter(l, p))
        expected(
            "libtest-full.json",
            lambda l, p: p not in ("invalid", "dirty-X-B", "clean-semantic"),
        )
        expected(
            "live-drivers.json.gz",
            lambda l, p: (
                (l == "physical" and p == "X-B")
                or (l == "ordinary" and p in ("dirty-X-B", "comment"))
            ),
        )
        expected("donor-opens.json", lambda l, p: l == "ordinary" and p == "comment")
        expected("fresh.json", lambda l, p: l == "empty" or p == "Y-B")
        pos = D("position.json")
        q.need(
            (
                pos["mode"],
                pos["position"],
                pos["order"],
                pos["runner"],
                pos["run"],
                pos["head"],
                pos["command"],
            )
            == (
                "one-host-contact",
                "01",
                list(policy.ORDER),
                meta["runner"],
                meta["run"],
                meta["head"],
                q.COMMAND,
            )
            and pos["plan"]
            == q.sha((q.HERE / "PLAN.md").read_bytes())
            == q.sha(z.read("PLAN.md"))
            and pos["hardware_gate"] == local.reg.hardware_gate()
            and D("ruff-inputs.json") == source,
            "wrong observation or source",
        )
        q.fresh_runner(pos["boot"], meta["runner"])
        local.reg.host(pos["host"])
        meter = D("meter-ready.json")
        n.replay_controls.PACKAGING, n.replay_controls.OBSERVER = calibrator, observers
        calibration = n.replay_controls.calibration(z, pos["boot"])
        hardware = n.hardware.verify(z, calibration, meter)
        q.need(
            meter["boot"] == pos["boot"]
            and calibration["affinity"] == meter["affinity"]
            and (meter["observer"], meter["calibrator"])
            == (n.replay_controls.OBS, n.replay_controls.CAL),
            "wrong meter scope",
        )
        minimum = contact_review.host_guards(z, pos)
        for state, mem, disk in [
            (D("bootstrap-resources.json"), 32, 32),
            (D("resource/resources.json")["start"], 16, 4),
        ]:
            q.need(
                state["effective"]
                == min(
                    [
                        state["physical"],
                        *[v for _, v in state["cgroups"] if v is not None],
                    ]
                )
                and state["effective"] >= mem * 2**30
                and state["work"] >= disk * 2**30
                and state["receipts"] >= max(6, disk) * 2**30,
                "invalid entry floors",
            )
        n.kernel_binding(z, pos["boot"], "contact", kernel, None)
        kits = n.sdk_pair(z)
        eac = D("initial/eacces.json")
        eo = gzip.decompress(z.read("initial/eacces.stdout.gz"))
        ee = gzip.decompress(z.read("initial/eacces.stderr.gz"))
        q.need(
            eac["exit"] == 0
            and eac["stdout"] == q.sha(eo)
            and eac["stderr"] == q.sha(ee)
            and not ee
            and re.fullmatch(rb"\d+ file EACCES directory EACCES\n", eo),
            "permission test failed",
        )
        priv = (
            [
                "setpriv",
                "--bounding-set=-dac_override,-dac_read_search",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
                "--",
            ]
            if eo.startswith(b"0 ")
            else []
        )
        q.need(eac["argv"][: len(priv)] == priv, "wrong suite privileges")
        refs, records, bodies, host_images = {}, {}, {}, set()
        rosters, full_semantics, origin = {}, {}, {}
        for arm in policy.ORDER:
            cert, root = n.active(z, arm, arm, kits[arm[0]]["files"])
            fresh_owners = {}
            rows = {}
            previous = {}
            for lane, phase in policy.ACTIONS:
                p = f"{arm}/{lane}/{phase}"
                d = lambda key: D(p + "/" + key)
                counted = policy.is_counter(lane, phase)
                cold = lane == "empty" or phase == "Y-B"
                if phase == policy.LAYOUT[lane][0]:
                    lane_certificate, same_root = n.active(
                        z, arm + "/" + lane, arm, kits[arm[0]]["files"]
                    )
                    q.need(
                        lane_certificate == cert
                        and same_root == root
                        and z.read(arm + "/" + lane + "/arm.json")
                        == z.read(arm + "/arm.json"),
                        "compiler installation changed between histories",
                    )
                if cold:
                    previous = {}
                    f = d("fresh.json")
                    q.need(
                        set(f) == {str(root / "work/target"), str(root / "work/build")}
                        and len({tuple(v) for v in f.values()}) == 2
                        and all(
                            len(v) == 2 and all(type(i) is int and i > 0 for i in v)
                            for v in f.values()
                        ),
                        "incorrect empty roots",
                    )
                state = d("source.json")
                _, phase_id, lineage = policy.plan(lane, phase)
                branch, _ = n.source_state(state, phase_id, lineage)
                if phase == "unchanged":
                    q.need(
                        state == D(f"{arm}/{lane}/comment/source.json"),
                        "source changed on repeat",
                    )
                rc = 101 if phase == "invalid" else 0
                cmd, events = cargo(z, p, root, cert, rc)
                n.driver(z, arm + "/" + lane, p, arm, cert)
                real = phy = wild = None
                if counted:
                    clock = d("clock.json")
                    policy.timed(clock, phase)
                    q.need(
                        cmd["observer_argv"]
                        == [
                            meter["plain"],
                            str(root / "logs" / p / "clock.json"),
                            *q.COMMAND,
                        ]
                        and meter["plain"] == str(root / "logs/observers/plain"),
                        "unregistered meter invocation",
                    )
                else:
                    with (
                        patch.object(n, "CARGO", q.COMMAND),
                        patch.object(n.kernel, "COMMAND", q.COMMAND),
                    ):
                        raw_kernel = n.physical(z, p, arm, cert, cmd, rc)
                    family = n.kernel.parse(
                        gzip.decompress(z.read(p + "/kernel.tsv.gz")),
                        expected_sha=raw_kernel["kernel"],
                        expected_code=rc,
                        expected_schema=3,
                    )
                    q.install_boundary(family["execs"])
                    host_images.update(r["image"]["sha256"] for r in family["execs"])
                    real = d("native-execs.json.gz")
                    phy = q.identities(real)
                    wild = q.link_outputs(real)
                typed, dirty = sel.roster(events, Path(cmd["cwd"]))
                q.need(
                    d("roster.json.gz") == dict(units=typed, dirty=dirty),
                    "changed Cargo roster",
                )
                rosters[arm, lane, phase] = (typed, dirty)
                store = d("storage.json")
                inodes = d("path-inodes.json.gz")
                allocated = n.metrics.allocation(
                    inodes, store, d("allocation-readers.json")
                )
                q.need(
                    min(store["roots"].values()) > 0
                    and store["all_inodes"] > 1000
                    and (not cold or len(dirty) == 390 and store["packed_files"] == 0),
                    "false cold or storage",
                )
                if lane == "ordinary" and phase in (*policy.PLAIN, "dirty-X-B"):
                    ds = d("donor-state.json")
                    q.need(ds["source"] == state, "donor source mismatch")
                    local.dw.check_ledger(ds, inodes, root)
                if (lane == "physical" and phase == "X-B") or (
                    lane == "ordinary" and phase in ("dirty-X-B", "comment")
                ):
                    integrity.reopen_mappings(
                        local.dw, d("live-drivers.json.gz"), cert, real
                    )
                if lane == "ordinary" and phase == "comment":
                    pref = f"{arm}/ordinary/"
                    states = [
                        D(pref + x + "/donor-state.json")
                        for x in ("Y-B", "X-A", "X-B", "dirty-X-B")
                    ]
                    selected_donor = integrity.registered(
                        local.dw,
                        *states,
                        local.dw.rows(D(pref + "dirty-X-B/native-execs.json.gz")),
                        arm[0],
                    )
                    q.need(
                        selected_donor == d("donor-register.json"),
                        "incorrect immutable donor registration",
                    )
                    local.dw.check_refs(d("both-ref-tips.json"))
                    with patch.object(local.dw.donors, "OWN", integrity.AST):
                        selected_tables = local.dw.donors.verify_opens(
                            selected_donor,
                            d("donor-opens.json"),
                            local.dw.rows(real),
                            arm[0],
                        )
                    q.need(
                        selected_tables == d("donor-selected.json"),
                        "changed original selected file/PID",
                    )
                    origin[arm] = selected_tables
                rec = dict(
                    phase=phase,
                    arm=arm,
                    lane=lane,
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
                        "lost failed compile",
                    )
                else:
                    products = n.replay_native.native_verdict(z, p, branch)
                    images = {k: products[k] for k in ("cli", "reader")} | {
                        "harness": d("harness-elf.json")
                    }
                    ref = q.reference(phase)
                    if counted:
                        context = fresh_owners[ref]
                        rec["external_owner_witness"] = ref
                        q.need(
                            d("selected.json")["owners"]
                            == policy.reference_owners(context),
                            "counter provider mismatch",
                        )
                    else:
                        context = previous
                    paths, previous = selected(
                        z, p, events, real, context, cold, images, sel, root
                    )
                    if phase in q.EMPTY:
                        fresh_owners[phase] = previous
                    q.need(
                        len(typed) == 390 and not store["failed_sessions"],
                        "partial successful build",
                    )
                    for k, v in images.items():
                        n.verified_body(z, k, v, bodies)
                    whole = {k: v["whole"] for k, v in images.items()}
                    changed = phase in ("dirty-X-B", "clean-semantic")
                    if changed or phase in ("comment", "repair", "clean-edited", "X-B"):
                        local.behavior.verify(
                            d("semantic-pyi009.json"),
                            cmd["cwd"],
                            paths["cli"],
                            changed,
                            whole["cli"],
                        )
                        full_semantics[p] = whole["cli"]
                    if (
                        real is not None
                        and phase in ("X-A", "X-B", "dirty-X-B")
                        and lane != "empty"
                    ):
                        q.need(
                            any(
                                r["crate"] == "ruff_python_ast" and r["mode"] == "full"
                                for r in real["rustcs"]
                            )
                            and all(
                                previous[k]["linked_by"] for k in ("cli", "harness")
                            ),
                            "missing genuine linker or AST emitter",
                        )
                    oracle = (
                        None
                        if changed
                        else full_suite(
                            z,
                            p,
                            paths,
                            cmd["cwd"],
                            suite,
                            local.original.processes,
                            priv,
                        )
                    )
                    behavior = {
                        key: value
                        for key, value in products.items()
                        if key not in ("cli", "reader")
                    } | {"suite": oracle}
                    dirs = {
                        r["out_dir"]
                        for r in events
                        if r.get("reason") == "build-script-executed"
                        and "tikv-jemalloc-sys" in r["package_id"]
                    }
                    q.need(len(dirs) == 1, "native generator path absent")
                    observed = (typed, images, behavior, dirs)
                    if phase in q.EMPTY:
                        refs[arm, phase] = observed
                    else:
                        q.need(
                            observed == refs[arm, ref],
                            "warm full ELF, behavior, native path, or typed outputs differed from its own empty",
                        )
                    if phase == "repair":
                        grace = d("grace.json")
                        invalid = D(f"{arm}/{lane}/invalid/failed.json")
                        cutoff = (
                            max((v["created_ns"] for v in invalid.values()), default=0)
                            + 11_000_000_000
                        )
                        q.need(
                            grace["sessions"] == invalid
                            and grace["cutoff_ns"] == cutoff
                            and grace["rustc_gc_grace_ns"] == 10_000_000_000
                            and grace["ready_ns"] >= max(cutoff, grace["read_ns"]),
                            "failed session recovery mismatch",
                        )
                    rec.update(products=whole, suite_count=0 if changed else 96)
                q.need(
                    rec == d("visit.json"),
                    "projected visit differs from raw observations: " + p,
                )
                rows[lane + "/" + phase] = rec
            records[arm] = rows
            for phase in policy.PLAIN:
                q.need(
                    rosters[arm, "physical", phase] == rosters[arm, "ordinary", phase],
                    "different typed compiler rows in sibling",
                )
        for name in q.EMPTY:
            e, d = (refs[a, name] for a in policy.ORDER)
            q.need(
                e[0] == d[0]
                and e[2] == d[2]
                and all(
                    e[1][k][f] == d[1][k][f]
                    for k in ("harness", "reader", "cli")
                    for f in ("executable", "loads")
                ),
                "different cross-role loaded programs",
            )
        q.need(
            {n for n in names if n.startswith("native-bodies/") and not n.endswith("/")}
            == {"native-bodies/" + k[1] + ".zst" for k in bodies}
            and host_images.isdisjoint(k[1] for k in bodies),
            "unaccounted or in-window native product",
        )
        outcome = policy.outcomes(records)
        q.need(
            D("complete.json")
            == dict(
                qualified=True,
                decisions=0,
                kernel_schema=3,
                layout={k: list(v) for k, v in policy.LAYOUT.items()},
                records=records,
                observed=outcome,
            ),
            "wrong final record",
        )
        return dict(
            official=meta,
            qualified=True,
            boot=pos["boot"],
            result=outcome,
            records=records,
            minimum=minimum,
            whole_body_count=len(bodies),
            calibration=calibration,
            hardware=hardware,
            donors=origin,
            semantic_verdicts=full_semantics,
            complete_suites=sum(
                v.get("suite_count", 0) == 96
                for x in records.values()
                for v in x.values()
            ),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("zip", "official-dir", "kernel", "ruff", "calibrator", "observers"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--head", required=True)
    opts = parser.parse_args()
    os.environ.setdefault("RUNNER_TEMP", "/tmp")
    q.check_source(opts.head)
    meta = official(opts.official_dir, opts.zip, opts.head)
    result = read(
        opts.zip, meta, opts.kernel, opts.ruff, opts.calibrator, opts.observers
    )
    print(json.dumps(result, sort_keys=True, indent=2))
