"""Independent offline four-arm replay. No reported hardware contrast is accepted until both original ZIPs pass."""

import argparse
import gzip
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol
import post_sync
import storage
import notify_calibration

sys.path.insert(1, str(protocol.FROZEN))
import read_contact as original
from read_contact import old, ev, kernel, get, archive, contact

need = protocol.require


def observation(z, top, mode, structural, cert, root, files, refs, bodies, reader, observer):
    pre = top + "/repair"
    where = root / "logs" / pre
    arm = "Eon" if mode == "E" else "Con"
    sdk = PurePosixPath(cert["sdk"])
    cmd = get(z, pre + "/cargo.json.gz")
    visit = get(z, pre + "/visit.json")
    source = get(z, pre + "/source.json")
    need(
        old.source_state(source, "repair", "return") == ("B", "clean-edited"),
        "wrong repaired graph state",
    )
    launch = (
        contact.launch("O", Path(where), Path(sdk), old.CARGO)
        if structural
        else protocol.launches(mode, root, where, sdk)
    )
    need(
        cmd["argv"] == list(protocol.CARGO)
        and cmd["observer_argv"] == launch
        and cmd["env"] == cert["env"]
        and cmd["expected"] == cmd["exit"] == 0
        and cmd["cwd"] == str(root / "ruff")
        and cmd["stdin_sha256"] == old.digest(b"")
        and get(z, pre + "/intent.json") == dict(launch=launch, env=cert["env"], cwd=str(root / "ruff")),
        "changed real command/context",
    )
    stdout = old.replay_native.raw(z, pre, "cargo.stdout.gz")
    stderr = old.replay_native.raw(z, pre, "cargo.stderr.gz")
    graph = old.metrics.cargo_messages(stdout, stderr, cmd, 0, cmd["cwd"])
    need(
        graph == get(z, pre + "/roster.json.gz")
        and old.compact(graph["members"]) == visit["graph"] == refs["graph"] == protocol.GRAPH
        and old.compact(graph["dirty"]) == visit["dirty"]
        and sorted([r["name"], r["kind"][0]] for r in graph["dirty"]) == contact.REG["physical_units"],
        "different repaired units",
    )
    desired = {role: files[k] for role, k in {**contact.ROLES, "driver": ev.DRIVER}.items()}
    need(
        get(z, pre + "/physical-before.json") == get(z, pre + "/physical-after.json") == desired,
        "different SDK at repair",
    )
    native = old.replay_native.native_verdict(z, pre, "B")
    old.typed_inputs(z, pre, stdout, root)
    for key in ("cli", "reader"):
        old.verified_body(z, key, native[key], bodies)
        need(
            native[key]["whole"] == visit[key] == refs[key],
            "complete native output does not match actual own empty",
        )
    need(old.behavior(native) == old.behavior(refs["native"]), "different source/native verdict")
    prior = get(z, top + "/invalid/path-inodes.json.gz")
    post = get(z, pre + "/path-inodes.json.gz")
    disk = get(z, pre + "/storage.json")
    n = old.metrics.allocation(post, disk, get(z, pre + "/allocation-readers.json"))
    need(
        visit["status"] == 0
        and visit["phase"] == "repair"
        and visit["allocated"] == n
        and not disk["failed_sessions"],
        "invalid terminal disk or verdict",
    )
    before, after, pl = [get(z, pre + "/" + f + ".json.gz") for f in ("before", "after", "placements")]
    selected = contact.REG["selected"]
    owners = selected + contact.REG["other"]
    need(
        set(before["owners"]) == set(owners) == set(pl) and before["owners"] == after["owners"],
        "wrong actual owner roots",
    )
    notifier = mode in ("P", "B")
    link = get(z, pre + "/link.json")
    wild = None
    commands = None
    if notifier:
        images, events = original.captured_calls(
            z,
            pre,
            mode,
            sdk,
            [before["owners"][o] for o in selected],
            [before["owners"][o] for o in owners],
            files,
        )
        wild = ev.roster(images, events, contact.REG, old.CARGO, before["owners"])
        commands = ev.compiler_commands(images)
        need(commands == get(z, pre + "/physical-compilers.json.gz"), "different charged compiler argv")
        movement = ev.routes(before, after, images, events, selected, mode == "B", all_owners=owners)
        need(
            movement
            == {o: {k: row[k] for k in ("final", "donor", "packed_pair")} for o, row in pl.items()},
            "different source read, output inode or error",
        )
    else:
        need(not any(k.startswith(pre + "/calls/") for k in z.NameToInfo), "notifier on ordinary repair")
        for owner, row in pl.items():
            fresh = set(after["sessions"][owner]) - set(before["sessions"][owner])
            packed = mode == "O" and owner in selected
            need(
                fresh == {row["final"]}
                and row["packed_pair"] == packed
                and set(after["sessions"][owner][row["final"]]) == set(ev.FILES if packed else ev.RAWS),
                "different ordinary table placement",
            )
    cp = pre + "/clock.json"
    kp = pre + "/positive.tsv.gz"
    if structural:
        need(
            cp not in z.NameToInfo
            and visit["instructions"] is None
            and visit["observer"] == "kernel-v3",
            "scored/foreign structural process",
        )
        need(
            get(z, pre + "/observer-before.json")
            == get(z, pre + "/observer-after.json")
            == kernel.signature(observer)
            and observer["resolved"] == str(root / "repair-kernel-tools/observe"),
            "different physical v3 observer",
        )
        catalog = get(z, pre + "/exec-before.json")
        need(catalog == get(z, pre + "/exec-after.json"), "executable catalog changed")
        proxy = Path(cert["env"]["PATH"].split(":")[0])
        proxy_receipt = get(z, "sdk/proxy.json")
        need(
            catalog[str(proxy / "cargo")][1]
            == [proxy_receipt["sha256"], *proxy_receipt["paths"][str(proxy / "cargo")]],
            "unregistered proxy",
        )
        raw = original.positive_ledger(z, kp)
        topology = kernel.topology(
            reader,
            raw,
            catalog,
            files,
            Path(sdk),
            proxy,
            old.CARGO,
            contact.REG["physical_units"],
            root / "ruff",
        )
        need(
            topology == get(z, pre + "/topology.json.gz")
            and protocol.completion(raw) == get(z, pre + "/completion.json"),
            "kernel lineage or closure changed",
        )
        wild = topology["wild_output"]
        clock = None
    else:
        clock = get(z, cp)
        need(
            protocol.measured(clock) == visit["instructions"]
            and kp not in z.NameToInfo
            and visit["observer"] == ("notifier-outside-pmu" if notifier else "pmu"),
            "altered/observed hardware window",
        )
    need(wild is None or wild == link["wild_output"], "different actual linker target")
    need(
        get(z, pre + "/link-source.json")
        == {"basis": "output inode and actual Wild argv" if wild else "post-command inode aliases"},
        "unsupported linker claim",
    )
    aliases = [
        k
        for k, v in post.items()
        if v == post["target/debug/ruff"] and PurePosixPath(k).parts[-2:] == ("out", "ruff")
    ]
    need(
        aliases == [str(PurePosixPath(link["wild_output"]).relative_to(root / "work"))],
        "wrong/nonunique final CLI inode",
    )
    barrier = get(z, pre + "/post-sync-tables.json.gz")
    post_sync.verify(
        barrier,
        before,
        after,
        pl,
        post,
        contact.REG["selected"],
        mode,
        root / "work",
        None if structural else get(z, cp),
    )
    archive.publication(prior, post, before, after, pl, link, native["cli"]["whole"], root / "work")
    report = {
        "prior": storage.allocation(prior, get(z, top + "/invalid/storage.json")["allocated"]),
        "repaired": storage.allocation(post, n),
        "fresh": storage.owners(pl, mode, contact.REG),
    }
    need(
        get(z, pre + "/allocation-consequences.json.gz") == report,
        "different actual allocation or native object classes",
    )
    return visit, clock, pl, commands, report


def checked_notifier_counter(z, root, sdk, env, mode):
    prior = root / "logs/nested-notifier-meter"
    out = []
    for i, value in enumerate(notify_calibration.SIZES):
        name = f"nested-notifier-meter/{mode}-{i}"
        d = prior / f"{mode}-{i}"
        c = d / "calls"
        launch = [
            str(root / "logs/tools/table-notify"),
            str(c),
            str(sdk),
            str(c / "notify.status"),
            "--",
            str(root / "logs/observers/plain"),
            str(d / "clock.json"),
            str(root / "logs/observers/loop"),
            "1",
            str(value),
            "2",
        ]
        record = get(z, name + "/receipt.json")
        need(
            get(z, name + "/intent.json") == dict(argv=launch, env=env, cwd=str(d))
            and not z.read(name + "/stdout")
            and not z.read(name + "/stderr"),
            "different counted calibrated descendant",
        )
        need(
            record["clock"] == get(z, name + "/clock.json")
            and record["listener"] == list(map(int, z.read(name + "/calls/notify.status").split()))
            and z.read(name + "/calls/config").decode() == ev.config(mode, [str(d / "empty-owner")])
            and z.read(name + "/calls/owners").decode() == str(d / "empty-owner") + "\n"
            and not z.read(name + "/calls/adopted"),
            "altered known counter or unowned calibrator",
        )
        need(
            {
                n[len(name + "/calls/") :]
                for n in z.namelist()
                if n.startswith(name + "/calls/") and not n.endswith("/")
            }
            == {"notify.status", "config", "owners", "adopted", "driver.reference"},
            "unexpected selected native command in calibration",
        )
        out.append(record)
    return notify_calibration.parse(out, mode)


def notifier_version(z, root, cert, files):
    """Reopen the physically mapped -vV command through the same seccomp launch used for P/B."""
    first_dir = str(root / "logs/notifier-preflight/empty-owner")
    images, events = original.captured_calls(
        z, "notifier-preflight", "P", Path(cert["sdk"]), [first_dir], [first_dir], files
    )
    (entry,) = images.values()
    first = get(z, "notifier-preflight/result.json")
    stub = root / "logs/notifier-preflight/calls"
    version = gzip.decompress(z.read("notifier-preflight/stdout.gz"))
    ev.need(
        not events
        and entry["role"] == "rustc"
        and entry["argv"] == [cert["sdk"] + "/bin/rustc", "-vV"]
        and first
        == {
            "argv": [
                str(root / "logs/tools/table-notify"),
                str(stub),
                cert["sdk"],
                str(stub / "notify.status"),
                "--",
                *entry["argv"],
            ],
            "env": cert["env"],
            "status": 0,
            "stdout_sha256": old.digest(version),
        }
        and b"host: x86_64-unknown-linux-gnu" in version
        and not gzip.decompress(z.read("notifier-preflight/stderr.gz")),
        "native notification or driver qualification failed",
    )


def read(path, pos, head, run, job, registered, observer_source, calibrators, meters):
    with zipfile.ZipFile(path) as z:
        ns = z.namelist()
        need(
            len(ns) == len(set(ns)) <= 25000
            and all(
                not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts for n in ns
            )
            and "failure.txt" not in ns,
            "failed, ambiguous or unsafe original",
        )
        reg = get(z, "position.json")
        meter = get(z, "meter-ready.json")
        contact_proof = get(z, "prerequisite.json")
        protocol.admit(contact_proof, registered)
        need(
            reg
            == dict(
                run=run,
                head=head,
                runner=job["runner_name"],
                boot=meter["boot"],
                position=pos,
                order=list(protocol.ARMS[pos]),
                separate_native_role="E" if pos == "01" else "O",
                plan=protocol.digest(HERE / "PLAN.md"),
                contact=registered,
                command=list(protocol.CARGO),
            ),
            "unregistered position/worker",
        )
        need(
            meter["observer"] == protocol.OBS
            and meter["calibrator"] == protocol.CAL
            and meter["boot"] != registered["boot"],
            "reused or foreign meter",
        )
        floors = get(z, "resource/resources.json")
        need(
            floors["exit"] == 0
            and not floors["refusal"]
            and all(
                floors["minimum"][k] >= n << 30
                for k, n in (("work", 4), ("receipts", 6), ("effective", 8))
            ),
            "resource gate refused",
        )
        old.replay_controls.PACKAGING, old.replay_controls.OBSERVER = calibrators, meters
        actual_cal = old.replay_controls.calibration(z, reg["boot"])
        physical_meter = old.hardware.verify(z, actual_cal, meter)
        need(
            physical_meter["binary_sha256"] == old.digest(z.read("observers/plain")),
            "native counter differs",
        )
        fixture = kernel.reopen_fixtures(z, observer_source)
        binding = get(z, "kernel-qualification.json")
        need(
            fixture["schema"] == 3
            and fixture["qualified"]
            and fixture["boot"] == reg["boot"]
            and binding
            == dict(
                source=kernel.HEAD,
                schema=3,
                boot=reg["boot"],
                observer=fixture["observer_sha256"],
                fixtures=old.digest(z.read("kernel-fixtures/group-v2/qualified.json")),
            ),
            "wrong structural observer",
        )
        observer = get(z, "kernel-fixtures/group-v2/host.json")["identities"]["observe"]
        reader = kernel.decoder(kernel.package(observer_source))
        sdk_pair = old.sdk_pair(z)
        refs = {}
        envs = {}
        bodies = {}
        layouts = {}
        training = {}
        placements = {}
        commands = {}
        counts = {}
        storage_reports = {}
        for arm in ("Eon", "Con"):
            files = sdk_pair[arm[0]]["files"]
            cert, root = old.active(z, "clean-reference-" + arm, arm, files)
            need(
                "LD_PRELOAD" not in cert["env"]
                and not any(k.startswith("OHM_QA_PACK_") for k in cert["env"]),
                "loader interception in actual Cargo graph",
            )
            envs[arm] = cert
            for phase in old.REFS:
                pre = "clean-reference-" + arm + "/" + phase
                refs[arm, phase] = old.read_phase(
                    z, pre, phase, "clean", "reference", arm, cert, root, bodies
                )
                need(refs[arm, phase]["graph"] == protocol.GRAPH, "different complete empty graph")
            need(
                refs[arm, "clean-A"]["cli"] != refs[arm, "clean-B"]["cli"],
                "true historical edit did not change native product",
            )
        need(envs["Eon"]["env"] == envs["Con"]["env"], "different matched environments")
        need(
            old.digest(z.read("kernel-fixtures/observe.elf")) == binding["observer"]
            and observer["resolved"] == str(root / "repair-kernel-tools/observe")
            and fixture["stock_wild_sha256"] == sdk_pair["C"]["files"][ev.WILD][0],
            "structural observer or Wild differs from physical fixtures",
        )
        notifier_version(z, root, envs["Con"], sdk_pair["C"]["files"])
        compiled = get(z, "tools/tool.json")
        binary = z.read("tools/table-notify")
        need(
            compiled["source"] == protocol.digest(protocol.FROZEN / "notify.c")
            and compiled["elf"] == old.digest(binary)
            and compiled["argv"][:6]
            == ["/usr/bin/cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror"]
            and PurePosixPath(compiled["argv"][-3]).parts[-4:]
            == ("enrolled", "scripts", "ctfe-repair-encode", "notify.c")
            and compiled["argv"][-2:] == ["-o", str(root / "logs/tools/table-notify")]
            and len(compiled["argv"]) == 9
            and binary[:6] == b"\x7fELF\x02\x01"
            and re.fullmatch(r"[0-9a-f]{64}", compiled["compiler"]),
            "unbound native fault supervisor",
        )
        need(
            {
                m: checked_notifier_counter(
                    z, root, root / "home/.rustup/toolchains/ohm", envs["Con"]["env"], m
                )
                for m in ("P", "B")
            }
            == get(z, "notifier-counter-calibration.json"),
            "missing nested measurement calibration",
        )
        for phase in old.REFS:
            a, b = (refs[arm, phase]["native"] for arm in ("Eon", "Con"))
            need(
                old.behavior(a) == old.behavior(b)
                and all(a[k][f] == b[k][f] for k in ("cli", "reader") for f in ("loads", "executable")),
                "cross-role executable or native outcome differs",
            )
        expected_clocks = {}
        expected_traces = []
        for role, traced in [
            (reg["separate_native_role"], True),
            *((m, False) for m in protocol.ARMS[pos]),
        ]:
            arm = "Eon" if role == "E" else "Con"
            top = ("structural-" if traced else "return-") + role
            cert, path = old.active(z, top, arm, sdk_pair[arm[0]]["files"])
            need(cert == envs[arm] and root == path, "run moved between compared paths")
            history = {}
            layout = {}
            for phase in old.PHASES:
                pre = top + "/" + phase
                if phase == "repair":
                    obs, clock, pl, cmd, allocation = observation(
                        z,
                        top,
                        role,
                        traced,
                        cert,
                        root,
                        sdk_pair[arm[0]]["files"],
                        refs[arm, "clean-edited"],
                        bodies,
                        reader,
                        observer,
                    )
                    if traced:
                        expected_traces.append(pre + "/positive.tsv.gz")
                    else:
                        expected_clocks[role] = pre + "/clock.json"
                        counts[role] = clock
                        placements[role] = pl
                        commands[role] = cmd
                        storage_reports[role] = allocation
                else:
                    obs = old.read_phase(z, pre, phase, "ordinary", "return", arm, cert, root, bodies)
                    if phase == "unchanged":
                        need(
                            obs["source"] == get(z, top + "/comment/source.json"),
                            "source changed on unchanged",
                        )
                    if phase != "invalid":
                        ref = refs[arm, obs["reference"]]
                        need(
                            old.behavior(ref["native"]) == old.behavior(obs["native"])
                            and all(ref[k] == obs[k] for k in ("graph", "cli", "reader")),
                            "failed clean/visit native equivalence",
                        )
                history[phase] = [obs.get(k) for k in ("status", "graph", "dirty", "cli", "reader")]
                if phase != "invalid":
                    layout[phase] = contact.placement(
                        list(
                            map(
                                json.loads,
                                gzip.decompress(z.read(pre + "/cargo.stdout.gz")).splitlines(),
                            )
                        ),
                        root / "work",
                    )
            clean = contact.placement(
                list(
                    map(
                        json.loads,
                        gzip.decompress(
                            z.read("clean-reference-" + arm + "/clean-edited/cargo.stdout.gz")
                        ).splitlines(),
                    )
                ),
                root / "work",
            )
            need(
                layout["repair"] == layout["unchanged"] == clean
                and training.setdefault(arm, history) == history
                and layouts.setdefault(arm, layout) == layout,
                "different true native/physical history",
            )
        need(
            {n for n in ns if n.endswith("/positive.tsv.gz")} == set(expected_traces)
            and {
                n
                for n in ns
                if n.startswith(("return-", "clean-reference-", "structural-"))
                and n.endswith("/clock.json")
            }
            == set(expected_clocks.values()),
            "changed structural or counted observation scope",
        )
        need(commands["P"] == commands["B"], "different authenticated compiler argv")
        checks = {k: ev.comparison(placements[k], placements["B"], contact.REG) for k in ("P", "O")}
        checks["ordinary_parent_objects"] = storage.parent_objects(
            placements["E"], placements["O"], contact.REG
        )
        contrast = protocol.contrasts(
            {arm: protocol.measured(counts[arm]) for arm in protocol.ARMS[pos]}
        )
        need(
            get(z, "completed.json")
            == dict(
                complete=True,
                issues=[],
                order=list(protocol.ARMS[pos]),
                source="registered-four-role",
                comparisons=checks,
                contrasts=contrast,
            ),
            "different reported result",
        )
        return {
            **reg,
            "job": job["id"],
            "attempt": job["run_attempt"],
            "complete": True,
            "issues": [],
            "calibration": True,
            "products": True,
            "publication": True,
            "repairs": counts,
            "allocation": storage_reports,
            "native_comparisons": checks,
        }


def paired_official(directory, run, head, media, observer_source, calibrators, meters, registered):
    need(
        set(media) == set(protocol.ARMS) and all(Path(p).is_file() for p in media.values()),
        "two complete media required",
    )
    r, j, a = [
        json.loads((directory / (n + ".json")).read_bytes()) for n in ("run", "jobs", "artifacts")
    ]
    repo = "astral-experiments/ohm"
    need(
        (
            r["id"],
            r["head_sha"],
            r["head_branch"],
            r["run_attempt"],
            r["path"],
            r["event"],
            r["conclusion"],
            r["repository"]["full_name"],
            r["head_repository"]["full_name"],
        )
        == (
            run,
            head,
            "charlie/qa-ctfe-repair-postsync-20261101",
            1,
            ".github/workflows/ci.yml",
            "workflow_dispatch",
            "success",
            repo,
            repo,
        ),
        "unregistered whole run",
    )
    need(
        j["total_count"] == len(j["jobs"]) == a["total_count"] == len(a["artifacts"]) == 2,
        "missing native host or original",
    )
    roles = {}
    extra = {}
    for pos in protocol.ARMS:
        name = "ctfe-repair-notify-pmu-" + pos
        (job,) = [item for item in j["jobs"] if item["name"] == "Full repair counter " + pos]
        (file,) = [item for item in a["artifacts"] if item["name"] == name]
        need(
            (job["head_sha"], job["run_id"], job["run_attempt"], job["labels"], job["conclusion"])
            == (head, run, 1, ["namespace-profile-ubuntu-24-04-16"], "success")
            and all(
                any(s["name"] == q and s["conclusion"] == "success" for s in job["steps"])
                for q in (
                    "Reopen the prerequisite and both source SDKs",
                    "Separate native observation and four ordinary repair measurements",
                )
            )
            and file["workflow_run"]["id"] == run
            and file["workflow_run"]["head_sha"] == head
            and not file["expired"]
            and file["size_in_bytes"] == media[pos].stat().st_size
            and 0 < file["size_in_bytes"] < 512 << 20
            and file["digest"] == "sha256:" + protocol.digest(media[pos])
            and file["archive_download_url"]
            == f"https://api.github.com/repos/{repo}/actions/artifacts/{file['id']}/zip",
            "unbound new hardware result",
        )
        row = read(media[pos], pos, head, run, job, registered, observer_source, calibrators, meters)
        extra[pos] = {
            "archive": {"id": file["id"], "sha256": file["digest"], "bytes": file["size_in_bytes"]},
            "retained_allocation": row.pop("allocation"),
            "native_comparisons": row.pop("native_comparisons"),
        }
        roles[pos] = row
    return {
        **protocol.paired(
            roles,
            registered,
            set(json.loads((HERE / "boot-exclusions.json").read_bytes())) | contact.OLD_BOOTS,
        ),
        "source_contact": registered,
        "physical": extra,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--official", required=True, type=Path)
    ap.add_argument("--run", required=True, type=int)
    ap.add_argument("--head", required=True)
    ap.add_argument("--observer-source", required=True, type=Path)
    ap.add_argument("--calibrators", required=True, type=Path)
    ap.add_argument("--meters", required=True, type=Path)
    ap.add_argument("--contact-original", required=True, type=Path)
    ap.add_argument("--contact-official", required=True, type=Path)
    ap.add_argument("zip01", type=Path)
    ap.add_argument("zip02", type=Path)
    args = ap.parse_args()
    stamped = json.loads((HERE / "contact-admission.json").read_bytes())
    proof = protocol.certificate(
        args.contact_official, args.contact_original, args.observer_source, stamped
    )
    print(
        json.dumps(
            paired_official(
                args.official,
                args.run,
                args.head,
                {"01": args.zip01, "02": args.zip02},
                args.observer_source,
                args.calibrators,
                args.meters,
                proof,
            ),
            indent=2,
            sort_keys=True,
        )
    )
