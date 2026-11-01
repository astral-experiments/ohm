"""Record and independently reopen fixed-period hardware instruction leaves for the signed rustcs."""

from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import common as c
import leaf_charge
import leaf_events
import leaf_symbols

PERIOD = 2_000_003
LIMIT = 100 << 20
ORIGINAL = "95a85547bbcf69295514b795bd76d249f98ad6fdb782f2e7160ab96c0a604fe7"
SDK_NAMES = ("bin/rustc", "lib/librustc_driver-b03bf00bec23bb9a.so", "lib/libLLVM.so.23.1-rust-1.99.0-beta")
LLVM = Path(SDK_NAMES[-1]).name
SUPPORT = Path("scripts/notebook-fanout-ceiling/sampling.py")


def support(checkout):
    checkout = Path(checkout).resolve(strict=True)
    p = checkout / SUPPORT
    c.need(
        c.git(checkout, "rev-parse", "HEAD").decode().strip() == c.SAMPLER and c.sha(p) == ORIGINAL,
        "different original sampler/forwarder",
    )
    spec = importlib.util.spec_from_file_location("frozen_notebook_sampler", p)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def image_inputs(module, sdk):
    return {n: module.identity(sdk / n) for n in SDK_NAMES}


def arguments(perf, python, source, folder, native, event="instructions:u", period=PERIOD):
    return [
        str(v)
        for v in (
            perf,
            "record",
            "-B",
            "-N",
            "-T",
            "-P",
            "--clockid",
            "mono",
            "-e",
            event,
            "-c",
            period,
            "-m",
            "256",
            "--max-size",
            "100M",
            "-o",
            folder / "perf.data",
            "--",
            python,
            "-IB",
            source,
            "forward",
            folder,
            *native,
        )
    ]


def record(folder, carrier, native, cwd, env):
    c.need(shutil.disk_usage(folder.parent).free >= 6 << 30, "sample receipt storage floor")
    return capture(folder, carrier, native, cwd, env, "instructions:u", PERIOD)


def capture(folder, carrier, native, cwd, env, event, period):
    """Only record() is used by the enrolled worker. The software fixture explicitly calls capture()."""
    folder.mkdir()
    c.save(folder / "target-environment.json", {"env": env, "cwd": str(cwd)})
    argv = arguments(
        carrier["perf"]["path"], carrier["python"], carrier["forward"], folder, native, event, period
    )
    with (folder / "perf.stdout").open("xb") as stdout, (folder / "perf.stderr").open("xb") as stderr:
        proc = subprocess.run(argv, env=env, cwd=cwd, stdout=stdout, stderr=stderr, timeout=1200)
    c.save(folder / "command.json", {"argv": argv, "exit": proc.returncode})
    path = folder / "perf.data"
    c.need(
        proc.returncode == 0
        and path.is_file()
        and 0 < path.stat().st_size < LIMIT
        and not re.search(
            rb"lost [1-9]\d*|throttl|failed|denied|size limit|maximum size reached",
            (folder / "perf.stderr").read_bytes(),
            re.I,
        ),
        "sample refused by perf or exceeded its bound",
    )
    c.save(folder / "original.json", {"bytes": path.stat().st_size, "sha256": c.sha(path)})
    return subprocess.CompletedProcess(
        native, proc.returncode, (folder / "stdout").read_bytes(), (folder / "stderr").read_bytes()
    )


def calibrate(out, tools, sdk, source):
    m = support(source)
    chosen = Path(os.environ["OHM_DIAGNOSTIC_PERF"]).resolve(strict=True)
    with chosen.open("rb") as f:
        c.need(f.read(4) == b"\x7fELF", "expected physical Linux perf executable")
    folder = out / "leaf-calibration"
    folder.mkdir()
    package = subprocess.check_output(["dpkg-query", "-S", str(chosen)], text=True).strip()
    c.need(
        re.fullmatch(r"linux-tools-[0-9][^\s:]*: " + re.escape(str(chosen)), package),
        "unrecognized packaged perf ELF",
    )
    kit = {
        "perf": m.identity(chosen),
        "perf_package": package,
        "perf_version": subprocess.check_output([chosen, "version", "--build-options"], text=True),
        "python": str(Path(sys.executable).resolve()),
        "forward": str(Path(m.__file__).resolve()),
        "source": c.SAMPLER,
        "sender_sha256": ORIGINAL,
        "loop": m.identity(tools / "loop"),
        "sdk": image_inputs(m, sdk),
    }
    c.save(folder / "tools.json", kit)
    marker = out.parent
    paths = [tools / "roles" / n for n in m.ROLES]
    for label, mode, copies in (("child", "1", "1"), ("thread", "thread", "2"), ("empty", "0", "0")):
        sub = folder / label
        sub.mkdir()
        trace = sub / "trace"
        trace.mkdir()
        # The empty case uses /bin/true and still exercises forwarding and the ordinary tree meter.
        cmd = [str(tools / "loop"), mode, "80000000", copies] if label != "empty" else ["/bin/true"]
        native = [tools / "tree", trace, "tree", *paths, *cmd]
        result = record(
            sub / "record", kit, native, marker, {"PATH": "/usr/bin:/bin", "HOME": str(marker), "LC_ALL": "C"}
        )
        c.need(result.returncode == 0, "calibration process failed")
    # Calibrate before launching expensive work. Reopen all three original media again in final receipt.
    from reopen import Directory

    check_calibration(Directory(out), out.parent, tools / "loop", m, kit)
    return kit


def read_capped(z, name, limit=LIMIT):
    with z.open(name) as f:
        b = f.read(limit + 1)
    c.need(len(b) <= limit, "oversized original leaf record: " + name)
    return b


def js(z, name):
    return json.loads(read_capped(z, name, 2 << 20))


def reopen_capture(z, root, label, kit, native, cwd, env):
    folder = root / "logs" / label
    c.need(
        js(z, label + "/target-environment.json") == {"env": env, "cwd": str(cwd)},
        "native environment changed before compiler",
    )
    diff = js(z, label + "/sampler-environment-diff.json")
    c.need(
        set(diff) == {"changed", "missing", "extra"}
        and all(isinstance(v, list) and all(isinstance(k, str) for k in v) for v in diff.values()),
        "missing original forwarding receipt",
    )
    recorded = js(z, label + "/command.json")
    expected = arguments(kit["perf"]["path"], kit["python"], kit["forward"], folder, native)
    c.need(recorded == {"argv": expected, "exit": 0}, "different sampled command or native exit")
    c.need(
        not read_capped(z, label + "/perf.stdout", 1 << 20)
        and not re.search(
            rb"lost [1-9]\d*|throttl|failed|denied|size limit|maximum size reached",
            read_capped(z, label + "/perf.stderr", 1 << 20),
            re.I,
        ),
        "perf acquisition diagnostics",
    )
    b = read_capped(z, label + "/perf.data")
    digest = hashlib.sha256(b).hexdigest()
    c.need(
        0 < len(b) < LIMIT and js(z, label + "/original.json") == {"bytes": len(b), "sha256": digest},
        "raw perf size/SHA",
    )
    # -P and -T must put the actual hardware period, time, TGID/TID and IP in every record.
    result = leaf_events.read(b, "retired", PERIOD, explicit_period=True)
    return result, digest


def groups(lines):
    items = [line.split("\t") for line in lines.decode().splitlines()]
    roots = [int(v[1]) for v in items if v[0] == "root"]
    c.need(len(roots) == 1, "nonunique traced root")
    tg = {}
    births = {}
    for k, *rest in items:
        if k == "task":
            tid, pid = map(int, rest[:2])
            c.need(tid not in tg, "duplicate task identity")
            tg[tid] = pid
        elif k == "spawn":
            parent, child = map(int, rest[:2])
            c.need(child not in births, "duplicate birth")
            births[child] = parent
    c.need(set(tg) == set(births) | set(roots), "task closure")
    return roots[0], tg


def check_calibration(z, root, local_loop, m, kit):
    c.need(c.sha(local_loop) == kit["loop"]["sha256"], "wrong genuine calibration program")
    sites = m.loop_sites(local_loop)
    image = kit["loop"]
    m.verify_mapping(image)
    expected_starts = set(sites["main"] + sites["count_instructions"])
    with leaf_symbols.Symbols(local_loop) as elf:
        # Disassembler reports virtual address, mmap reports physical file offset. PIE is not assumed.
        known = {elf.offset(v) for v in expected_starts}
    out = {}
    for label, mode, copies in (("child", "1", "1"), ("thread", "thread", "2"), ("empty", "0", "0")):
        base = "leaf-calibration/" + label
        trace = root / "logs" / base / "trace"
        tools = root / "counter-kit/bin"
        native = [tools / "tree", trace, "tree", *[tools / "roles" / r for r in m.ROLES]]
        native += [tools / "loop", mode, "80000000", copies] if label != "empty" else ["/bin/true"]
        records, raw_hash = reopen_capture(
            z,
            root,
            base + "/record",
            kit,
            native,
            root,
            {"PATH": "/usr/bin:/bin", "HOME": str(root), "LC_ALL": "C"},
        )
        tasks = read_capped(z, base + "/trace/tasks.tsv", 4 << 20)
        rootpid, tg = groups(tasks)
        term = {
            int(v[1])
            for line in tasks.decode().splitlines()
            if (v := line.split("\t"))[0] == "exit" and v[2:] == ["0", "0"]
        }
        c.need(term == set(tg), "unclosed/failed native calibration task")
        execs = [
            row.split("\t") for row in read_capped(z, base + "/trace/exec.tsv", 1 << 20).decode().splitlines()
        ]
        expected_image = image["path"] if label != "empty" else "/usr/bin/true"
        # /bin is an Ubuntu usrmerge alias; the kernel /proc/exe is its resolved system path.
        c.need(
            len(execs) == (2 if label == "child" else 1)
            and all(e[6] == expected_image and int(e[1]) in tg for e in execs),
            "different actual calibration executable",
        )
        for e in execs:
            if label != "empty":
                c.need([int(e[4]), int(e[5])] == [image["dev"], image["ino"]], "foreign hot loop inode")
        first_args = read_capped(z, base + "/trace/args-0001", 8192).split(b"\0")
        c.need(
            first_args[-1] == b"" and [x.decode() for x in first_args[:-1]] == list(map(str, native[7:])),
            "different actual calibration argv",
        )
        out[label] = calibration_case(records, rootpid, tg, image, known, label, raw_hash)
    return out


def calibration_case(records, rootpid, tg, image, known, label, raw_hash):
    rows, maps, _, _, _, _ = records
    hot = Counter()
    kernel = Counter()
    other = Counter()
    per_thread = Counter()
    for time, pid, tid, ip, weight, cmode in rows:
        if tid not in tg:
            continue  # perf's own CLI/captured forwarding script is outside the tree.
        c.need(tg[tid] == pid, "wrong calibrated TID")
        if label == "child" and not (tid == pid and pid != rootpid):
            continue
        if label == "thread" and not (tid != pid and pid == rootpid):
            continue
        per_thread[tid] += weight
        if cmode == 1:
            kernel[tid] += weight
            continue
        found = [
            x
            for x in maps
            if x.pid == pid
            and x.when <= time
            and x.low <= ip < x.high
            and x.perm & 4
            and x.path == image["path"]
        ]
        if found:
            c.need(
                len(found) == 1
                and (found[0].dev, found[0].ino)
                == ((os.major(image["mapping_dev"]), os.minor(image["mapping_dev"])), image["mapping_ino"]),
                "calibration failed file mapping",
            )
            if found[0].offset + ip - found[0].low in known:
                hot[tid] += weight
            else:
                other[tid] += weight
    if label == "empty":
        c.need(not hot, "empty calibration unexpectedly observed enrolled hot code")
    else:
        c.need(
            len(hot) == (1 if label == "child" else 2)
            and set(kernel) <= set(hot)
            and all(
                120_000_000 <= w <= 192_000_000 and kernel[tid] * 20 <= per_thread[tid]
                for tid, w in hot.items()
            ),
            "incorrect native child/thread loop instruction sample coverage",
        )
    return {
        "raw_sha256": raw_hash,
        "hot": {str(k): v for k, v in sorted(hot.items())},
        "skid": {str(k): v for k, v in sorted(kernel.items())},
        "other_loop": {str(k): v for k, v in sorted(other.items())},
    }


def zflags(argv, root):
    result = []
    prefix = str(root / "work/target") + "/"
    for i, v in enumerate(argv):
        if v == "-Z":
            arg = argv[i + 1]
            if arg.startswith("temps-dir="):
                c.need(
                    arg.removeprefix("temps-dir=").startswith(prefix), "foreign linker temporary directory"
                )
                arg = "temps-dir=<registered target>"
            result.append("-Z " + arg)
        elif v.startswith("-Z"):
            result.append(v)
    return result


def expected_owner(o, root, args):
    (kind,) = o["kind"]
    key = o["target"] + "/" + kind
    c.need(
        o["mode"] == "full"
        and o["profile"]["opt_level"] == "1"
        and o["profile"]["debuginfo"] == "line-tables-only",
        "different source compilation scope",
    )
    x = {
        "name": o["target"],
        "kind": o["kind"],
        "source": str(Path(o["src"]).relative_to(root / "ruff")),
        "package_version": o["package"].rsplit("#", 1)[1],
        "features": o["features"],
        "profile": o["profile"],
        "zflags": zflags(args, root),
    }
    return key, x


def reopen(z, temp, root, sdk, selectors, owners, sampler_source, symbol_sdk):
    m = support(sampler_source)
    kit = js(z, "leaf-calibration/tools.json")
    c.need(
        kit["source"] == c.SAMPLER
        and kit["sender_sha256"] == ORIGINAL
        and Path(kit["python"]).is_absolute()
        and Path(kit["forward"]).is_absolute()
        and Path(kit["forward"]).parts[-len(SUPPORT.parts) - 1 :] == ("sampler-source", *SUPPORT.parts),
        "sampler source/forward path",
    )
    c.need(
        re.fullmatch(r"linux-tools-[0-9][^\s:]*: " + re.escape(kit["perf"]["path"]), kit["perf_package"])
        and kit["perf_version"].startswith("perf version "),
        "unqualified perf",
    )
    m.verify_mapping(kit["perf"])
    c.need(
        kit["loop"]["path"] == str(root / "counter-kit/bin/loop") and set(kit["sdk"]) == set(SDK_NAMES),
        "unexpected mapped participant set",
    )
    cal = check_calibration(z, root, temp / "counter-programs/loop", m, kit)
    canon = root / "home/.rustup/toolchains/ohm"
    reg = {}
    tabs = {}
    for name in SDK_NAMES:
        witness = kit["sdk"][name]
        m.verify_mapping(witness)
        c.need(
            (witness["path"], witness["sha256"], witness["dev"], witness["ino"], witness["size"])
            == (str(canon / name), sdk[name][0], sdk[name][1], sdk[name][2], sdk[name][4]),
            "wrong physical signed compiler/symbol input",
        )
        local = symbol_sdk / name
        c.need(
            local.is_file()
            and not local.is_symlink()
            and local.stat().st_size == sdk[name][4]
            and c.sha(local) == sdk[name][0],
            "different offline symbol bytes",
        )
        reg[witness["path"]] = (
            (os.major(witness["mapping_dev"]), os.minor(witness["mapping_dev"])),
            witness["mapping_ino"],
            Path(name).name,
        )
        if name.startswith("lib/"):
            tabs[Path(name).name] = leaf_symbols.Symbols(local)
    try:
        out = classify(z, root, owners, selectors, reg, tabs, kit)
    finally:
        for table in tabs.values():
            table.close()
    return {
        "unit": "fixed-period retired userspace instruction observations",
        "disjoint_origins": "per selected TGID, exclusive actual leaf IP",
        "sampling_calibration": cal,
        **out,
    }


def coverage(charged, budget):
    mass = charged["weighted_observations"]
    named = charged["physical_sized_functions_weight"]
    c.need(
        charged["samples"] > 0
        and mass == charged["samples"] * PERIOD
        and 0 <= named <= mass
        and charged["phase"].get("kernel skid", 0) * 20 <= mass,
        "invalid per-owner sample mass/skid",
    )
    if budget >= 2_000_000_000:
        c.need(
            charged["samples"] >= 200
            and len(charged["sampled_tids"]) >= 2
            and 10 * named >= 6 * mass
            and abs(mass - budget) * 10 <= budget,
            "large compiler sample or signed-symbol coverage refused",
        )


def classify(z, root, owners, selectors, reg, tabs, kit):
    prefix = "attributed/A"
    inv = js(z, prefix + "/invocation.json")
    env = js(z, "execution-environment.json")["env"]
    rec, raw_hash = reopen_capture(z, root, prefix + "/leaves", kit, inv["argv"], root / "ruff", env)
    # Cross-check the forwarded stdout and diagnostics against the independently verified Cargo ledger.
    import gzip

    for name in ("stdout", "stderr"):
        c.need(
            read_capped(z, prefix + "/leaves/" + name, 16 << 20)
            == gzip.decompress(read_capped(z, prefix + "/cargo." + name + ".gz", 16 << 20)),
            "different original forwarded Cargo stream",
        )
    rows, maps, execs, forks, exits, kinds = rec
    actual_rustc = selectors["rustc"][2]
    c.need(actual_rustc in reg, "unenrolled native rustc")
    canonical = {o["pid"] for o in owners}
    rowroot, tg = groups(read_capped(z, prefix + "/trace/tasks.tsv", 4 << 20))
    installed = {m.pid for m in maps if m.path == actual_rustc}
    c.need(
        canonical == installed and len(canonical) == len(owners) == 20,
        "extra or missing actual signed compiler mapping",
    )
    # Require the authentic Cargo process tree to remain in PERF until its final task.
    # Early truncation drops even a quiet last owner and must invalidate this contact.
    final = {(p, ti) for _, p, _, ti, _ in exits}
    c.need(
        all((p, ti) in final for ti, p in tg.items()) and tg[rowroot] == rowroot,
        "incomplete perf lifetime for the traced Cargo tree",
    )
    suffix = sorted(c.read(c.HERE / "first-a-owners.json"), key=lambda x: (x["name"], x["kind"]))
    roster = []
    data = []
    known = {}
    base_images = {k: v for k, v in reg.items() if v[-1] in tabs}
    for o in owners:
        name = prefix + "/trace/args-%04d" % o["serial"]
        rawargs = read_capped(z, name, 1 << 20)
        args = rawargs.decode().split("\0")
        c.need(
            args.pop() == "" and args[0] == actual_rustc and not any("self-profile" in a for a in args),
            "wrong physical full-compiler argv",
        )
        key, descriptor = expected_owner(o, root, args)
        roster.append(descriptor)
        owner = {"pid": o["pid"], "actual_image": actual_rustc, "key": key}
        c.need(
            key not in known and owner["pid"] in tg and tg[owner["pid"]] == owner["pid"],
            "different physical owner identity",
        )
        known[key] = owner
        _, used = leaf_events.epochs(rows, maps, execs, forks, exits, o["pid"], actual_rustc)
        observed = set()
        identities = {(v[0], v[1]): n for n, v in reg.items()}
        for m in used:
            image = identities.get((m.dev, m.ino))
            if image is not None or m.path in reg:
                c.need(image == m.path, "signed image pathname or physical MMAP2 changed")
                if m.perm & 4:
                    observed.add(image)
        c.need(observed == set(reg), "compiler missing signed rustc/LLVM/driver")
        charge = leaf_charge.charge(rec, owner, base_images, tabs, leaf_symbols.demangle, LLVM)
        c.need(
            all(tg.get(t) == owner["pid"] for t in charge["sampled_tids"]),
            "leaf outside independently traced rustc thread cohort",
        )
        coverage(charge, o["outside_cc"])
        charge.update(
            native_rustc_outside_cc=o["outside_cc"],
            native_task_subtree=o["tasks"],
            argv_sha256=hashlib.sha256(rawargs).hexdigest(),
            serial=o["serial"],
        )
        charge["top_named"] = [
            {
                "image": im,
                "function": fn[:500],
                "full_name_sha256": hashlib.sha256(fn.encode()).hexdigest(),
                "sample_weight": weight,
            }
            for im, fn, weight in charge.pop("named")[:15]
        ]
        data.append(charge)
    c.need(
        sorted(roster, key=lambda x: (x["name"], x["kind"])) == suffix,
        "unexpected first-A compile roster, source or options",
    )
    all_rows = leaf_charge.cohort(data, list(known.values()), set(known))
    measured = sum(x["outside_cc"] for x in owners)
    mass = sum(all_rows.values())
    c.need(measured > 0 and abs(mass - measured) * 20 <= measured, "20-owner sample drift exceeds 5%")
    return {
        "complete_original_sha256": raw_hash,
        "event_record_counts": {str(k): v for k, v in sorted(kinds.items())},
        "all_perf_samples_including_observer": len(rows),
        "all_native_compiler_budget": measured,
        "all_compiler_observed_sample_weight": mass,
        "aggregate_disjoint_leaves": all_rows,
        "owner_rows": data,
        "actual_savings_measured": False,
    }
