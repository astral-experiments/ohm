"""One unscored ordinary/pass/block contact on the registered Ruff edit."""

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
import contact
import contact_kernel as kernel
import evidence as ev
from run import p, enrolled, REG, GRAPH


def contents(where):
    return [json.loads(line) for line in gzip.open(where / "cargo.stdout.gz", "rb")]


def physical_members(sdk, inventory):
    members = {
        name: [ev.sha(sdk / member), *p.b.numbers(sdk / member)]
        for name, member in {**contact.ROLES, "driver": ev.DRIVER}.items()
    }
    ev.need(
        all(
            members[k] == inventory[member] for k, member in {**contact.ROLES, "driver": ev.DRIVER}.items()
        ),
        "replaced SDK input",
    )
    return members


def repair(mode, where, sdk, env, files, refs, issues, reader):
    where.mkdir()
    ev.need(
        shutil.disk_usage(p.WORK).free > 2 << 30 and shutil.disk_usage(p.OUT).free > 5 << 30,
        "insufficient contact capacity",
    )
    old = json.loads((where.parent / "invalid/failed.json").read_bytes())
    p.original.failed_session.before_repair(p.WORK, old, where / "grace.json")
    p.routes.advance(p.kit.TREE, p.kit.NAMES, "repair", "return")
    p.save(
        where / "source.json",
        p.routes.snapshot(p.kit.TREE, p.kit.REVS, p.kit.TREES, p.kit.NAMES, "repair", "return"),
    )
    selected = REG["selected"]
    owners = selected + REG["other"]
    before = ev.sessions(p.WORK, owners)
    p.publish(where / "before.json.gz", before)
    paths = [before["owners"][o] for o in selected]
    all_paths = [before["owners"][o] for o in owners]
    calls = where / "calls"
    if mode != "O":
        calls.mkdir()
        (calls / "config").write_text(ev.config(mode, paths))
        (calls / "owners").write_text("".join(x + "\n" for x in all_paths))
    cmd = contact.launch(mode, where, sdk, p.original.CARGO)
    p.save(where / "physical-before.json", physical_members(sdk, files))
    catalog_args = (sdk, p.b.PROXIES, cmd[3] if mode != "O" else None)
    catalog = kernel.catalog(*catalog_args)
    p.save(where / "exec-before.json", catalog)
    p.save(where / "intent.json", dict(launch=cmd, env=env, cwd=str(p.kit.TREE)))
    observer = Path(cmd[0])
    observer_file = [ev.sha(observer), *p.b.numbers(observer)]
    p.save(where / "observer-before.json", observer_file)
    timed_out = False
    try:
        with subprocess.Popen(
            cmd,
            cwd=p.kit.TREE,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as proc:
            try:
                stdout, stderr = proc.communicate(b"", timeout=2400)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.kill()  # The source-bound positive observer uses PTRACE_O_EXITKILL.
                stdout, stderr = proc.communicate()
            c = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    finally:
        raw = where / "positive.tsv"
        if raw.exists():
            p.original.processes.compact(raw, where / "positive.tsv.gz")
    for k, body in (("stdout", c.stdout), ("stderr", c.stderr)):
        (where / ("cargo." + k + ".gz")).write_bytes(gzip.compress(body, compresslevel=2, mtime=0))
    p.publish(
        where / "cargo.json.gz",
        dict(
            argv=p.original.CARGO,
            observer_argv=cmd,
            cwd=str(p.kit.TREE),
            env=env,
            expected=0,
            exit=c.returncode,
            stdin_sha256=p.original.digest(b""),
            stdout_sha256=p.original.digest(c.stdout),
            stderr_sha256=p.original.digest(c.stderr),
        ),
    )
    p.save(where / "physical-after.json", physical_members(sdk, files))
    after_observer = [ev.sha(observer), *p.b.numbers(observer)]
    p.save(where / "observer-after.json", after_observer)
    ev.need(observer_file == after_observer, "kernel observer replaced")
    ev.need(
        not timed_out and c.returncode == 0,
        ("contact refused; original streams retained", mode, c.returncode, c.stderr[-600:]),
    )
    fresh = kernel.catalog(*catalog_args)
    p.save(where / "exec-after.json", fresh)
    ev.need(fresh == catalog, "native tool inputs changed during command")
    messages = contents(where)
    ev.need(
        messages[-1] == {"reason": "build-finished", "success": True}
        and not any(m.get("message", {}).get("level") == "error" for m in messages),
        "Cargo did not complete a healthy repair",
    )
    ev.need(not p.original.failed_session.observed(p.WORK), "incomplete repaired session")
    after = ev.sessions(p.WORK, owners)
    p.publish(where / "after.json.gz", after)
    events = images = None
    if mode != "O":
        images, events = contact.listener(calls, mode, sdk, paths, all_paths, files)
    topo = kernel.topology(
        reader,
        gzip.decompress((where / "positive.tsv.gz").read_bytes()),
        catalog,
        files,
        sdk,
        p.b.PROXIES,
        p.original.CARGO,
        REG["physical_units"],
        p.kit.TREE,
        notifier=cmd[cmd.index("--") + 1 :] if mode != "O" else None,
        captured=images,
    )
    p.publish(where / "topology.json.gz", topo)
    if mode != "O":
        ev.need(
            ev.roster(images, events, REG, p.original.CARGO, before["owners"]) == topo["wild_output"],
            "wrong enrolled writer or linker",
        )
        pl = ev.certify(before, after, images, events, selected, mode == "B", all_owners=owners)
    else:
        pl = {}
        for o in owners:
            (one,) = set(after["sessions"][o]) - set(before["sessions"][o])
            d = Path(before["owners"][o]) / one
            packed = o in selected
            ev.need(
                set(after["sessions"][o][one]) == set(ev.FILES if packed else ev.RAWS),
                "wrong ordinary fresh representation",
            )
            pl[o] = dict(
                final=one,
                packed_pair=packed,
                tables=[ev.table(d, i, packed) for i in range(2)],
                objects=ev.objects(d),
            )
    p.publish(where / "placements.json.gz", pl)
    rows, dirty = p.original.historical.roster(messages)
    p.publish(where / "roster.json.gz", dict(members=rows, dirty=dirty))
    ev.need(
        rows == refs["Con", "clean-edited"][0]
        and sorted([x["name"], x["kind"][0]] for x in dirty) == REG["physical_units"],
        "unexpected dirty graph",
    )
    storage = p.original.disk.allocated(p.WORK / "target", p.WORK / "build", where, failed_sessions=())
    products, native = p.original.native.observed(
        messages, "B", p.kit.REVS["B"], env, p.ROOT, p.kit.TREE, p.WORK, where
    )
    p.product_check(native, products, refs["Con", "clean-edited"][1], where, issues)
    wild = Path(topo["wild_output"])
    ev.need(
        wild.is_absolute()
        and wild.resolve() == wild
        and wild.is_relative_to(p.WORK)
        and wild.samefile(native["cli"])
        and ev.sha(wild) == products["cli"]["whole"],
        "Wild did not produce this CLI",
    )
    p.save(
        where / "link.json",
        {
            "wild_output": str(wild),
            "file": ev.ident(wild),
            "cargo": str(native["cli"]),
            "returned": ev.ident(native["cli"]),
        },
    )
    p.save(
        where / "visit.json",
        dict(
            phase="repair",
            status=0,
            observer="kernel-v3" if mode == "O" else "kernel-v3-seccomp",
            instructions=None,
            allocated=storage["allocated"],
            graph=p.original.historical.commit(rows),
            dirty=p.original.historical.commit(dirty),
            cli=products["cli"]["whole"],
            reader=products["reader"]["whole"],
        ),
    )
    ev.need(not issues, "changed native source/empty parity")
    return topo, pl


def native_preflight(env, files):
    where = p.OUT / "notifier-preflight"
    where.mkdir()
    owner = where / "empty-owner"
    owner.mkdir()
    calls = where / "calls"
    calls.mkdir()
    paths = [str(owner)]
    (calls / "config").write_text(ev.config("P", paths))
    (calls / "owners").write_text(str(owner) + "\n")
    sdk = p.b.SDK
    args = [str(sdk / "bin/rustc"), "-vV"]
    argv = [
        str(p.OUT / "tools/table-notify"),
        str(calls),
        str(sdk),
        str(calls / "notify.status"),
        "--",
        *args,
    ]
    c = subprocess.run(argv, env=env, cwd=where, input=b"", capture_output=True, timeout=30)
    for key, data in (("stdout", c.stdout), ("stderr", c.stderr)):
        (where / (key + ".gz")).write_bytes(gzip.compress(data, mtime=0))
    p.save(
        where / "result.json",
        dict(argv=argv, env=env, status=c.returncode, stdout_sha256=p.original.digest(c.stdout)),
    )
    ev.need(
        c.returncode == 0 and b"host: x86_64-unknown-linux-gnu" in c.stdout and not c.stderr,
        "runner notifier unavailable",
    )
    images, events = contact.listener(calls, "P", sdk, paths, paths, files)
    (image,) = images.values()
    ev.need(
        image["role"] == "rustc" and image["argv"] == args and not events, "preflight did not map actual C"
    )


def run():
    ev.need(shutil.disk_usage(p.OUT).free > 20 << 30, "insufficient worker capacity")
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    ev.need(boot not in contact.OLD_BOOTS, "reused boot")
    ev.need("QA_EVIDENCE_B3SUM" not in os.environ, "unregistered hashing tool")
    os.environ["QA_EVIDENCE_B3SUM"] = "/usr/bin/b3sum"
    tools = p.OUT / "tools"
    tools.mkdir()
    src = HERE / "notify.c"
    binary = tools / "table-notify"
    argv = ["/usr/bin/cc", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", str(src), "-o", str(binary)]
    subprocess.run(argv, check=True)
    p.save(
        tools / "tool.json",
        dict(
            argv=argv,
            source=ev.sha(src),
            elf=ev.sha(binary),
            compiler=ev.sha(Path(argv[0]).resolve()),
        ),
    )
    p.save(
        p.OUT / "contact-enrollment.json",
        dict(
            run=os.environ["GITHUB_RUN_ID"],
            head=os.environ["GITHUB_SHA"],
            boot=boot,
            order=list(contact.ORDER),
            command=p.original.CARGO,
            plan=ev.sha(HERE / "PLAN.md"),
            registration=ev.sha(HERE / "owners.json"),
        ),
    )
    rows = {r: json.loads((p.OUT / "sdk" / (r + ".json")).read_bytes())["files"] for r in ("E", "C")}
    start = p.OUT / "initial"
    start.mkdir()
    env = p.subjects.activate("Con", rows, start)
    observer_source = Path(os.environ["GITHUB_WORKSPACE"]) / "observer-source"
    group = kernel.qualify(
        observer_source, p.ROOT / "repair-kernel-tools", p.OUT / "kernel-fixtures", p.b.SDK / ev.WILD, boot
    )
    p.save(
        p.OUT / "kernel-qualification.json",
        dict(
            source=kernel.HEAD,
            schema=3,
            boot=boot,
            observer=group["observer_sha256"],
            fixtures=ev.sha(p.OUT / "kernel-fixtures/group-v2/qualified.json"),
        ),
    )
    reader = kernel.decoder(kernel.package(observer_source))
    native_preflight(env, rows["C"])
    p.b.fresh_outputs()
    p.b.prepare_inputs(p.kit, env)
    subprocess.run([sys.executable, "-IB", p.HERE / "test_routes.py", p.kit.TREE], check=True)
    p.original.historical.calibration()
    refs = {}
    issues = []
    layouts = {}
    result = {}
    orders = {}
    phases = {}
    p.history("Con", "clean", "reference", rows, refs, issues, None)
    base = p.OUT / "clean-reference-Con"
    for state in p.REFS:
        layouts[state] = contact.placement(contents(base / state), p.WORK)
    ev.need(
        refs["Con", "clean-A"][1]["cli"]["whole"] != refs["Con", "clean-B"][1]["cli"]["whole"],
        "unchanged A/B native product",
    )
    ev.need(p.original.historical.commit(refs["Con", "clean-B"][0]) == GRAPH, "foreign full graph")
    for mode in contact.ORDER:
        group = p.OUT / ("return-" + mode)
        group.mkdir()
        ev.need(
            p.subjects.activate("Con", rows, group) == env
            and "LD_PRELOAD" not in env
            and not any(x.startswith("OHM_QA_PACK_") for x in env),
            "different or contaminated Cargo environment",
        )
        p.b.fresh_outputs()
        p.routes.begin(p.kit.TREE, p.kit.REVS, p.kit.NAMES)
        for phase in p.FULL[:-1]:
            p.visit("Con", "ordinary", "return", phase, env, group / phase, refs, issues, None)
        top, result[mode] = repair(mode, group / "repair", p.b.SDK, env, rows["C"], refs, issues, reader)
        orders[mode] = top["compilers"]
        active = {}
        for phase in p.FULL:
            if phase == "invalid":
                continue
            active[phase] = contact.placement(contents(group / phase), p.WORK)
        ev.need(
            active["repair"] == active["unchanged"] == layouts["clean-edited"],
            "ordinary registry or other product roots changed",
        )
        if phases:
            ev.need(active == phases, "changed physical unit placements across contacts")
        else:
            phases = active
        ev.need(orders[mode] == orders["O"], "changed full Rust commands across contacts")
    baseline = ev.comparison(result["O"], result["B"], REG)
    passive = ev.comparison(result["P"], result["B"], REG)
    p.save(
        p.OUT / "contact.json",
        dict(
            qualified=True,
            score=None,
            unscored=True,
            ordinary_vs_blocked=baseline,
            pass_vs_blocked=passive,
            phase_placements={k: contact.digest(v) for k, v in phases.items()},
            issues=issues,
        ),
    )


if __name__ == "__main__":
    try:
        enrolled()
        if sys.argv[1:2] == ["acquire"]:
            p.subjects.acquire(Path(sys.argv[2]))
        elif sys.argv[1:] == ["contact"]:
            run()
        else:
            raise ValueError("expected acquire SOURCE or contact")
    except BaseException:
        if p.OUT.is_dir():
            (p.OUT / "failure.txt").write_text(traceback.format_exc())
        raise
