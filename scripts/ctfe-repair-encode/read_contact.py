"""Independently reopen one authenticated, unscored source-bound native contact."""

import argparse
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "ctfe-crossover-pilot")]
import archive
import contact
import contact_kernel as kernel
import evidence as ev
import reopen as old

get = old.dataset


def captured_calls(z, pre, mode, sdk, selected, owners, inventory):
    cprefix = pre + "/calls/"
    members = [i for i in z.infolist() if i.filename.startswith(cprefix) and not i.is_dir()]
    ev.need(
        3 < len(members) < 160 and sum(i.file_size for i in members) < 24 << 20,
        "unbounded native call ledger",
    )
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        for i in members:
            name = i.filename.removeprefix(cprefix)
            ev.need(
                i.file_size < 2 << 20
                and (
                    name in ("config", "owners", "driver.reference", "adopted", "notify.status")
                    or re.fullmatch(
                        r"(?:rustc|cargo|wild)-[1-9]\d*\.(?:cmdline|maps|mmap|events|image)", name
                    )
                ),
                "unsafe notifier input",
            )
            (scratch / name).write_bytes(z.read(i))
        return contact.listener(scratch, mode, sdk, selected, owners, inventory)


def positive_ledger(z, name):
    member = z.getinfo(name)
    ev.need(0 < member.file_size <= 8 << 20, "unbounded compressed process history")
    with gzip.GzipFile(fileobj=io.BytesIO(z.read(member))) as stream:
        raw = stream.read((32 << 20) + 1)
    ev.need(0 < len(raw) <= 32 << 20, "unbounded expanded process history")
    return raw


def check_repair(z, top, mode, cert, root, bodies, reference, reader, notifier_sha):
    pre = top + "/repair"
    w = Path(root) / "work"
    where = Path(root) / "logs" / pre
    sdk = Path(cert["sdk"])
    observer = get(z, "kernel-fixtures/group-v2/host.json")["identities"]["observe"]
    ev.need(
        observer["resolved"] == str(root / "repair-kernel-tools/observe")
        and get(z, pre + "/observer-before.json")
        == get(z, pre + "/observer-after.json")
        == kernel.signature(observer),
        "different executable observed this repair",
    )
    cmd = get(z, pre + "/cargo.json.gz")
    visit = get(z, pre + "/visit.json")
    expected_launch = contact.launch(mode, where, sdk, old.CARGO)
    ev.need(
        get(z, pre + "/intent.json")
        == dict(launch=expected_launch, env=cert["env"], cwd=str(root / "ruff")),
        "altered launch intent",
    )
    ev.need(
        old.source_state(get(z, pre + "/source.json"), "repair", "return") == ("B", "clean-edited")
        and cmd["expected"] == visit["status"] == 0
        and cmd["cwd"] == str(root / "ruff")
        and cmd["env"] == cert["env"]
        and cmd["stdin_sha256"] == old.digest(b"")
        and cmd["observer_argv"] == expected_launch
        and visit["phase"] == "repair"
        and visit["instructions"] is None
        and visit["observer"] == ("kernel-v3" if mode == "O" else "kernel-v3-seccomp"),
        "incorrect source, command or unscored observer",
    )
    raw = old.replay_native.raw(z, pre, "cargo.stdout.gz")
    error = old.replay_native.raw(z, pre, "cargo.stderr.gz")
    roster = old.metrics.cargo_messages(raw, error, cmd, 0, cmd["cwd"])
    ev.need(
        roster == get(z, pre + "/roster.json.gz")
        and old.compact(roster["members"]) == visit["graph"] == reference["graph"]
        and old.compact(roster["dirty"]) == visit["dirty"]
        and sorted([r["name"], r["kind"][0]] for r in roster["dirty"]) == contact.REG["physical_units"],
        "wrong dirty or complete Cargo graph",
    )
    actual = old.replay_native.native_verdict(z, pre, "B")
    old.typed_inputs(z, pre, raw, root)
    for k in ("cli", "reader"):
        old.verified_body(z, k, actual[k], bodies)
        ev.need(
            actual[k]["whole"] == visit[k] == reference[k], "complete native product differs from its empty"
        )
    ev.need(old.behavior(actual) == old.behavior(reference["native"]), "changed native/typed behavior")
    ledger = get(z, pre + "/path-inodes.json.gz")
    totals = get(z, pre + "/storage.json")
    ev.need(
        old.metrics.allocation(ledger, totals, get(z, pre + "/allocation-readers.json"))
        == visit["allocated"]
        and totals["all_inodes"] > 1000
        and min(totals["roots"].values()) > 0
        and not totals["failed_sessions"],
        "failed post-repair physical census",
    )
    old_files = cert["files"]
    expected = {name: old_files[member] for name, member in {**contact.ROLES, "driver": ev.DRIVER}.items()}
    ev.need(
        get(z, pre + "/physical-before.json") == get(z, pre + "/physical-after.json") == expected,
        "foreign/replaced SDK",
    )
    before, after, pl = [get(z, pre + "/" + n + ".json.gz") for n in ("before", "after", "placements")]
    selected = contact.REG["selected"]
    owners = selected + contact.REG["other"]
    ev.need(
        len(owners) == 16
        and set(before["owners"]) == set(pl) == set(owners)
        and before["owners"] == after["owners"],
        "incorrect donor roots",
    )
    cprefix = pre + "/calls/"
    members = [i for i in z.infolist() if i.filename.startswith(cprefix) and not i.is_dir()]
    images = None
    if mode == "O":
        ev.need(not members, "notifier ran on ordinary control")
        for owner, row in pl.items():
            (fresh,) = set(after["sessions"][owner]) - set(before["sessions"][owner])
            ev.need(
                row["final"] == fresh
                and row["packed_pair"] == (owner in selected)
                and set(after["sessions"][owner][fresh]) == set(ev.FILES if owner in selected else ev.RAWS),
                "unexpected ordinary publication",
            )
    else:
        ev.need(
            40 < len(members) < 160 and sum(x.file_size for x in members) < 24 << 20,
            "unexpected notifier footprint",
        )
        images, events = captured_calls(
            z,
            pre,
            mode,
            sdk,
            [before["owners"][o] for o in selected],
            [before["owners"][o] for o in owners],
            old_files,
        )
        physical = ev.routes(before, after, images, events, selected, mode == "B", all_owners=owners)
        ev.need(
            physical == {o: {k: r[k] for k in ("final", "donor", "packed_pair")} for o, r in pl.items()},
            "different file open/publication",
        )
        expected_output = ev.roster(images, events, contact.REG, old.CARGO, before["owners"])
    catalog = get(z, pre + "/exec-before.json")
    ev.need(catalog == get(z, pre + "/exec-after.json"), "changed native tools")
    proxy = Path(cert["env"]["PATH"].split(":")[0]) / "cargo"
    proxy_cert = get(z, "sdk/proxy.json")
    ev.need(
        catalog[str(proxy)][1] == [proxy_cert["sha256"], *proxy_cert["paths"][str(proxy)]]
        and (mode == "O" or catalog[expected_launch[3]][1][0] == notifier_sha),
        "wrong proxy or notifier",
    )
    topo = kernel.topology(
        reader,
        positive_ledger(z, pre + "/positive.tsv.gz"),
        catalog,
        old_files,
        sdk,
        Path(cert["env"]["PATH"].split(":")[0]),
        old.CARGO,
        contact.REG["physical_units"],
        root / "ruff",
        notifier=expected_launch[expected_launch.index("--") + 1 :] if mode != "O" else None,
        captured=images,
    )
    ev.need(
        topo == get(z, pre + "/topology.json.gz")
        and (mode == "O" or topo["wild_output"] == expected_output),
        "different physical topology",
    )
    link = get(z, pre + "/link.json")
    ev.need(topo["wild_output"] == link["wild_output"], "foreign linker output")
    archive.publication(
        get(z, top + "/invalid/path-inodes.json.gz"),
        ledger,
        before,
        after,
        pl,
        link,
        actual["cli"]["whole"],
        w,
    )
    return topo["compilers"], pl, visit


def check(path, run, head, observer_source):
    with zipfile.ZipFile(path) as z:
        ns = z.namelist()
        ev.need(
            len(ns) == len(set(ns))
            and all(not PurePosixPath(n).is_absolute() and ".." not in PurePosixPath(n).parts for n in ns)
            and "failure.txt" not in ns
            and not any(
                n.endswith(("/clock.json", "kernel.tsv.gz", "/pack-gate.so", "/observers/plain"))
                for n in ns
            ),
            "failed, measured, ambiguous or foreign result",
        )
        reg = get(z, "contact-enrollment.json")
        boot = reg["boot"]
        ev.need(
            reg
            == dict(
                run=str(run),
                head=head,
                boot=boot,
                order=list(contact.ORDER),
                command=old.CARGO,
                plan=ev.sha(HERE / "PLAN.md"),
                registration=ev.sha(HERE / "owners.json"),
            )
            and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot)
            and boot not in contact.OLD_BOOTS,
            "unbound/reused contact",
        )
        support = get(z, "resource/resources.json")
        floor = support["minimum"]
        ev.need(
            support["exit"] == 0
            and support["refusal"] is None
            and floor["work"] >= 4 << 30
            and floor["receipts"] >= 6 << 30
            and floor["effective"] >= 8 << 30,
            "real resource floor refused",
        )
        ev.need(
            {n for n in ns if n.endswith("/positive.tsv.gz")}
            == {"return-" + m + "/repair/positive.tsv.gz" for m in contact.ORDER},
            "altered observer scope",
        )
        files = old.sdk_pair(z)["C"]["files"]
        cert, root = old.active(z, "clean-reference-Con", "Con", files)
        ev.need(
            "LD_PRELOAD" not in cert["env"] and not any(k.startswith("OHM_QA_PACK_") for k in cert["env"]),
            "loader-modified environment",
        )
        fixture = kernel.reopen_fixtures(z, observer_source)
        reader = kernel.decoder(kernel.package(observer_source))
        binding = get(z, "kernel-qualification.json")
        ev.need(
            binding
            == dict(
                source=kernel.HEAD,
                schema=3,
                boot=boot,
                observer=fixture["observer_sha256"],
                fixtures=old.digest(z.read("kernel-fixtures/group-v2/qualified.json")),
            )
            and fixture["qualified"]
            and fixture["schema"] == 3
            and fixture["boot"] == boot
            and fixture["stock_wild_sha256"] == files[ev.WILD][0]
            and old.digest(z.read("kernel-fixtures/observe.elf")) == binding["observer"],
            "unrelated or missing schema-3 observer qualification",
        )
        tool = get(z, "tools/tool.json")
        src = Path(tool["argv"][-3])
        executable = z.read("tools/table-notify")
        ev.need(
            src.is_absolute()
            and src.parts[-4:] == ("enrolled", "scripts", "ctfe-repair-encode", "notify.c")
            and tool["argv"]
            == [
                "/usr/bin/cc",
                "-std=gnu11",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(src),
                "-o",
                str(root / "logs/tools/table-notify"),
            ]
            and tool["source"] == ev.sha(HERE / "notify.c")
            and tool["elf"] == old.digest(executable)
            and executable[:6] == b"\x7fELF\x02\x01"
            and re.fullmatch("[0-9a-f]{64}", tool["compiler"]),
            "unbound notifier",
        )
        first_dir = str(root / "logs/notifier-preflight/empty-owner")
        images, events = captured_calls(
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
        bodies = {}
        refs = {}
        checked = {}
        placements = {}
        topologies = {}
        visits = {}
        clean = {}

        def layout(prefix):
            return contact.placement(
                list(map(json.loads, gzip.decompress(z.read(prefix + "/cargo.stdout.gz")).splitlines())),
                Path(root / "work"),
            )

        for phase in old.REFS:
            pre = "clean-reference-Con/" + phase
            refs[phase] = old.read_phase(z, pre, phase, "clean", "reference", "Con", cert, root, bodies)
            ev.need(
                refs[phase]["graph"] == "f5909e1cbd4832369f783bdbd733e54562bcce15e44592b8ec15793e9996c660",
                "foreign full Ruff graph",
            )
            clean[phase] = layout(pre)
        ev.need(refs["clean-A"]["cli"] != refs["clean-B"]["cli"], "true edit retained same CLI")
        for mode in contact.ORDER:
            top = "return-" + mode
            active, path = old.active(z, top, "Con", files)
            ev.need(active == cert and path == root, "changed paths/SDK/context")
            visits[mode] = {}
            placements[mode] = {}
            for phase in old.PHASES:
                pre = top + "/" + phase
                if phase == "repair":
                    topologies[mode], checked[mode], obs = check_repair(
                        z, top, mode, cert, root, bodies, refs["clean-edited"], reader, tool["elf"]
                    )
                else:
                    obs = old.read_phase(z, pre, phase, "ordinary", "return", "Con", cert, root, bodies)
                    if phase == "unchanged":
                        ev.need(
                            obs["source"] == get(z, top + "/comment/source.json"),
                            "source changed on repeat",
                        )
                    if phase != "invalid":
                        wanted = refs[obs["reference"]]
                        ev.need(
                            old.behavior(obs["native"]) == old.behavior(wanted["native"])
                            and all(obs[k] == wanted[k] for k in ("graph", "reader", "cli")),
                            "training or repaired outcomes differ from same-path empty",
                        )
                visits[mode][phase] = [obs[k] for k in ("status", "graph", "dirty", "cli", "reader")]
                if phase != "invalid":
                    placements[mode][phase] = layout(pre)
            ev.need(
                placements[mode]["repair"] == placements[mode]["unchanged"] == clean["clean-edited"],
                "registry or source output moved",
            )
        ev.need(
            visits["O"] == visits["P"] == visits["B"]
            and placements["O"] == placements["P"] == placements["B"]
            and topologies["O"] == topologies["P"] == topologies["B"],
            "unmatched native commands or physical/semantic graph",
        )
        result = dict(
            qualified=True,
            score=None,
            unscored=True,
            ordinary_vs_blocked=ev.comparison(checked["O"], checked["B"], contact.REG),
            pass_vs_blocked=ev.comparison(checked["P"], checked["B"], contact.REG),
            phase_placements={k: contact.digest(v) for k, v in placements["O"].items()},
            issues=[],
        )
        ev.need(get(z, "contact.json") == result, "incorrect terminal")
        return dict(boot=boot, run=run, head=head, source=old.SOURCES["C"], **result)


def official(directory, path, run, head, observer_source):
    r, j, a = [json.loads((directory / (n + ".json")).read_bytes()) for n in ("run", "jobs", "artifacts")]
    ev.need(
        (r["id"], r["head_sha"], r["head_branch"], r["run_attempt"], r["path"], r["event"], r["conclusion"])
        == (
            run,
            head,
            "charlie/qa-ctfe-repair-encode-20261101",
            1,
            ".github/workflows/ci.yml",
            "workflow_dispatch",
            "success",
        )
        and r["repository"]["full_name"] == r["head_repository"]["full_name"] == "astral-experiments/ohm",
        "wrong official source",
    )
    ev.need(
        j["total_count"] == len(j["jobs"]) == a["total_count"] == len(a["artifacts"]) == 1,
        "unexpected workers/media",
    )
    job = j["jobs"][0]
    file = a["artifacts"][0]
    ev.need(
        (job["name"], job["head_sha"], job["run_id"], job["run_attempt"], job["conclusion"], job["labels"])
        == (
            "Verify native table-notification contact",
            head,
            run,
            1,
            "success",
            ["namespace-profile-ubuntu-24-04-16"],
        )
        and all(
            any(s["name"] == step and s["conclusion"] == "success" for s in job["steps"])
            for step in (
                "Authenticate the source-built candidate SDK",
                "Run the unscored ordinary and notified repairs",
            )
        )
        and (
            file["name"],
            file["workflow_run"]["head_sha"],
            file["workflow_run"]["id"],
            file["expired"],
            file["size_in_bytes"],
            file["digest"],
        )
        == ("ctfe-repair-contact", head, run, False, path.stat().st_size, "sha256:" + ev.sha(path)),
        "wrong native job or original archive",
    )
    return check(path, run, head, observer_source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", required=True, type=Path)
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--head", required=True)
    parser.add_argument("--observer-source", required=True, type=Path)
    parser.add_argument("archive", type=Path)
    a = parser.parse_args()
    print(
        json.dumps(
            official(a.official, a.archive, a.run, a.head, a.observer_source), sort_keys=True, indent=2
        )
    )
