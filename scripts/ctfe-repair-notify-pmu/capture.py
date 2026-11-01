"""One actual repair. Everything besides the direct Cargo user event runs outside the measured process tree."""

import gzip
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import protocol
import storage

sys.path.insert(1, str(protocol.FROZEN))
import run_contact as original
from run_contact import p, ev, contact, kernel, REG


def put_calls(calls, mode, selected, owners):
    calls.mkdir()
    (calls / "config").write_text(ev.config(mode, selected))
    (calls / "owners").write_text("".join(o + "\n" for o in owners))


def invoke(where, env, cmd, traced=False):
    p.save(where / "intent.json", dict(launch=cmd, env=env, cwd=str(p.kit.TREE)))
    try:
        cp = subprocess.run(cmd, cwd=p.kit.TREE, env=env, input=b"", capture_output=True, timeout=2400)
    except subprocess.TimeoutExpired as err:
        cp = subprocess.CompletedProcess(cmd, -9, err.stdout or b"", err.stderr or b"")
        p.save(where / "timeout.json", {"seconds": 2400, "refused": True})
    for name, data in (("stdout", cp.stdout), ("stderr", cp.stderr)):
        (where / ("cargo." + name + ".gz")).write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
    p.publish(
        where / "cargo.json.gz",
        dict(
            argv=p.original.CARGO,
            observer_argv=cmd,
            cwd=str(p.kit.TREE),
            env=env,
            expected=0,
            exit=cp.returncode,
            stdin_sha256=p.original.digest(b""),
            stdout_sha256=p.original.digest(cp.stdout),
            stderr_sha256=p.original.digest(cp.stderr),
        ),
    )
    if traced and (where / "positive.tsv").exists():
        p.original.processes.compact(where / "positive.tsv", where / "positive.tsv.gz")
    ev.need(cp.returncode == 0, ("native repair refused", cp.returncode, cp.stderr[-800:]))
    messages = list(map(json.loads, cp.stdout.splitlines()))
    ev.need(
        messages[-1] == {"reason": "build-finished", "success": True}
        and not any(m.get("message", {}).get("level") == "error" for m in messages),
        "invalid repair compile",
    )
    return messages


def ordinary_files(before, after, selected, packed):
    placements = {}
    for owner, parent in before["owners"].items():
        (one,) = set(after["sessions"][owner]) - set(before["sessions"][owner])
        q = Path(parent) / one
        is_packed = packed and owner in selected
        ev.need(
            set(after["sessions"][owner][one]) == set(ev.FILES if is_packed else ev.RAWS),
            "unexpected physical table form",
        )
        placements[owner] = dict(
            final=one,
            packed_pair=is_packed,
            tables=[ev.table(q, i, is_packed) for i in range(2)],
            objects=ev.objects(q),
        )
    return placements


def cli_alias(work, ledger, cli):
    """Find the physical linker-output alias without attributing unobserved processes to a metered control."""
    row = ledger[str(cli.relative_to(work))]
    a = [
        work / k
        for k, v in ledger.items()
        if v == row and Path(k).parts[-2:] == ("out", "ruff") and Path(k).parts[0] in ("target", "build")
    ]
    ev.need(
        len(a) == 1 and a[0].resolve() == a[0] and a[0].samefile(cli),
        "no unique physical Ruff output alias",
    )
    return a[0]


def physical(scope, where, env, files, refs, issues, reader, *, structural):
    where.mkdir()
    role = "Eon" if scope == "E" else "Con"
    sdk = p.b.SDK
    failed = json.loads((where.parent / "invalid/failed.json").read_bytes())
    p.original.failed_session.before_repair(p.WORK, failed, where / "grace.json")
    p.routes.advance(p.kit.TREE, p.kit.NAMES, "repair", "return")
    p.save(
        where / "source.json",
        p.routes.snapshot(p.kit.TREE, p.kit.REVS, p.kit.TREES, p.kit.NAMES, "repair", "return"),
    )
    selected = REG["selected"]
    owners = selected + REG["other"]
    before = ev.sessions(p.WORK, owners)
    p.publish(where / "before.json.gz", before)
    sel = [before["owners"][o] for o in selected]
    all_ = [before["owners"][o] for o in owners]
    if not structural and scope in ("P", "B"):
        put_calls(where / "calls", scope, sel, all_)
    physical = original.physical_members(sdk, files)
    p.save(where / "physical-before.json", physical)
    if structural:
        ev.need(scope in ("E", "O"), "unexpected uncounted repair kind")
        cmd = contact.launch("O", where, sdk, p.original.CARGO)
        cat = kernel.catalog(sdk, p.b.PROXIES, None)
        p.save(where / "exec-before.json", cat)
        identity = [ev.sha(Path(cmd[0])), *p.b.numbers(Path(cmd[0]))]
        p.save(where / "observer-before.json", identity)
    else:
        cmd = protocol.launches(scope, p.ROOT, where, sdk)
    messages = invoke(where, env, cmd, traced=structural)
    after_files = original.physical_members(sdk, files)
    p.save(where / "physical-after.json", after_files)
    ev.need(
        after_files == physical and not p.original.failed_session.observed(p.WORK),
        "SDK changed or unfinished repair",
    )
    after = ev.sessions(p.WORK, owners)
    p.publish(where / "after.json.gz", after)
    observed_wild = None
    if structural:
        cat_after = kernel.catalog(sdk, p.b.PROXIES, None)
        id_after = [ev.sha(Path(cmd[0])), *p.b.numbers(Path(cmd[0]))]
        p.save(where / "exec-after.json", cat_after)
        p.save(where / "observer-after.json", id_after)
        ev.need(cat == cat_after and identity == id_after, "replaced observer or image")
        raw = gzip.decompress((where / "positive.tsv.gz").read_bytes())
        top = kernel.topology(
            reader,
            raw,
            cat,
            files,
            sdk,
            p.b.PROXIES,
            p.original.CARGO,
            REG["physical_units"],
            p.kit.TREE,
        )
        p.publish(where / "topology.json.gz", top)
        p.save(where / "completion.json", protocol.completion(raw))
        observed_wild = Path(top["wild_output"])
    if scope in ("P", "B"):
        images, events = contact.listener(where / "calls", scope, sdk, sel, all_, files)
        observed_wild = Path(ev.roster(images, events, REG, p.original.CARGO, before["owners"]))
        p.publish(where / "physical-compilers.json.gz", ev.compiler_commands(images))
        placements = ev.certify(before, after, images, events, selected, scope == "B", all_owners=owners)
    else:
        placements = ordinary_files(before, after, selected, scope == "O")
    p.publish(where / "placements.json.gz", placements)
    rows, dirty = p.original.historical.roster(messages)
    p.publish(where / "roster.json.gz", dict(members=rows, dirty=dirty))
    ev.need(
        rows == refs[role, "clean-edited"][0]
        and p.original.historical.commit(rows) == protocol.GRAPH
        and sorted([r["name"], r["kind"][0]] for r in dirty) == REG["physical_units"],
        "incorrect actual repaired graph",
    )
    disk = p.original.disk.allocated(p.WORK / "target", p.WORK / "build", where, failed_sessions=())
    ledger = read_gz(where / "path-inodes.json.gz")
    products, paths = p.original.native.observed(
        messages, "B", p.kit.REVS["B"], env, p.ROOT, p.kit.TREE, p.WORK, where
    )
    p.product_check(paths, products, refs[role, "clean-edited"][1], where, issues)
    cli = paths["cli"]
    output = cli_alias(p.WORK, ledger, cli)
    ev.need(
        observed_wild is None or observed_wild == output, "observed Wild wrote different physical ELF"
    )
    link = {
        "wild_output": str(output),
        "file": ev.ident(output),
        "cargo": str(cli),
        "returned": ev.ident(cli),
    }
    p.save(where / "link.json", link)
    p.save(
        where / "link-source.json",
        {
            "basis": (
                "output inode and actual Wild argv" if observed_wild else "post-command inode aliases"
            )
        },
    )
    import archive

    prior = read_gz(where.parent / "invalid/path-inodes.json.gz")
    archive.publication(prior, ledger, before, after, placements, link, products["cli"]["whole"], p.WORK)
    totals = json.loads((where.parent / "invalid/storage.json").read_bytes())
    p.publish(
        where / "allocation-consequences.json.gz",
        dict(
            prior=storage.allocation(prior, totals["allocated"]),
            repaired=storage.allocation(ledger, disk["allocated"]),
            fresh=storage.owners(placements, scope, REG),
        ),
    )
    clock = None if structural else json.loads((where / "clock.json").read_bytes())
    score = None if clock is None else protocol.measured(clock)
    p.save(
        where / "visit.json",
        dict(
            phase="repair",
            status=0,
            observer=(
                "kernel-v3" if structural else "pmu" if scope in ("E", "O") else "notifier-outside-pmu"
            ),
            instructions=score,
            allocated=disk["allocated"],
            graph=p.original.historical.commit(rows),
            dirty=p.original.historical.commit(dirty),
            cli=products["cli"]["whole"],
            reader=products["reader"]["whole"],
        ),
    )
    ev.need(not issues, "repair differs from independent clean")
    return clock, placements


def read_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)
