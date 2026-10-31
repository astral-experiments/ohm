"""Sample unmodified GNU compiler invocations off the plain measurement lane."""

from collections import Counter, defaultdict
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PERIOD = 2_000_003
ROLES = ("rustc", "cc", "collect2", "wild")
TARGETS = ("ty_python_core", "ty_python_semantic")
DRIVER = "librustc_driver-b03bf00bec23bb9a.so"
LLVM = "libLLVM.so.23.1-rust-1.99.0-beta"
PIN = {
    DRIVER: "dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3",
    LLVM: "43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def save(path, obj):
    with path.open("x") as f:
        json.dump(obj, f, separators=(",", ":"), sort_keys=True)
        f.write("\n")


def load(path):
    return json.loads(path.read_bytes())


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def identity(path):
    path = Path(path).resolve(strict=True)
    st = path.stat()
    return dict(
        path=str(path), dev=st.st_dev, ino=st.st_ino, size=st.st_size, sha256=sha(path)
    )


def raw_report(fp):
    """Read actual PERF_RECORD_SAMPLE identities and MMAP2/FORK/EXEC sideband from the native stream."""

    def take(n):
        s = fp.read(n)
        require(len(s) == n, "short perf.data")
        return s

    magic, head, unit, attr, nattrs, start, length = struct.unpack("<8s6Q", take(56))
    require(
        magic == b"PERFILE2"
        and 56 <= head <= attr < start <= 4 << 20
        and 100 <= unit <= 512
        and nattrs == unit
        and attr + nattrs <= start,
        ("unsupported native event file", head, attr, nattrs, start),
    )
    take(attr - 56)
    payload = take(unit)
    typ, size, cfg, period, mask, readfmt, flags = struct.unpack_from("<II5Q", payload)
    # Require actual user hardware instructions, callchains + user stack/registers, inheritance and identities.
    needed = 1 | 2 | 4 | 32 | 256 | 4096 | 8192
    require(
        (typ, cfg, period) == (0, 1, PERIOD)
        and mask & needed == needed
        and flags & 2
        and flags & (1 << 5)
        and flags & (1 << 6)
        and flags & (1 << 18)
        and not flags & ((1 << 4) | (1 << 10))
        and 96 <= size <= unit - 16,
        ("wrong native instructions/stack scope", typ, cfg, period, mask, flags),
    )
    require(
        struct.unpack_from("<I", payload, 88)[0] == 4096 and readfmt & 16,
        "wrong DWARF stack size or unsupported loss accounting",
    )
    regs = struct.unpack_from("<Q", payload, 80)[0].bit_count()
    require(
        regs
        and not mask
        & ~(1 | 2 | 4 | 8 | 32 | 64 | 128 | 256 | 512 | 4096 | 8192 | 65536),
        "unsupported native sample fields",
    )
    take(start - attr - nattrs)
    events, maps, execs = Counter(), defaultdict(list), defaultdict(list)
    samples = Counter()
    seen = 0
    tail = 8 * sum(bool(mask & bit) for bit in (2, 4, 64, 512, 128, 65536))
    while seen < length:
        kind, misc, n = struct.unpack("<IHH", take(8))
        require(n >= 8 and seen + n <= length, "invalid perf record size")
        data = take(n - 8)
        seen += n
        events[kind] += 1
        require(kind not in {2, 5, 6, 13}, ("lost or throttled perf records", kind))
        if kind == 9:
            require(misc & 7 == 2, ("non-user sample", misc))
            pos = 8 if mask & 65536 else 0
            ip, pid, tid, when = struct.unpack_from("<QIIQ", data, pos)
            pos += 24 + 8 * sum(bool(mask & bit) for bit in (8, 64, 512, 128))
            (weight,) = struct.unpack_from("<Q", data, pos)
            require(
                weight == PERIOD and when and tid and pid,
                "wrong observed hardware period or identity",
            )
            (slots,) = struct.unpack_from("<Q", data, pos + 8)
            pos += 16 + 8 * slots
            (abi,) = struct.unpack_from("<Q", data, pos)
            pos += 8
            require(abi in (0, 2), "unexpected sampled register ABI")
            if abi:
                pos += 8 * regs
            (captured,) = struct.unpack_from("<Q", data, pos)
            pos += 8
            require(
                captured <= 4096
                and pos + captured + (8 if captured else 0) == len(data),
                "truncated user stack or register record",
            )
            if captured:
                require(
                    struct.unpack_from("<Q", data, pos + captured)[0] <= captured,
                    "invalid stack payload extent",
                )
            samples[(pid, tid, when, ip, weight)] += 1
        elif kind == 10:
            pid, tid, addr, size, off = struct.unpack_from("<II3Q", data)
            (prot,) = struct.unpack_from("<I", data, 56)
            if prot & 4:
                path = (
                    data[64 : len(data) - tail]
                    .split(b"\0", 1)[0]
                    .decode(errors="surrogateescape")
                )
                # We require the file/inode form for selected DSOs, even when a build ID is unavailable.
                dev = ino = 0
                if not misc & (1 << 14):
                    major, minor, ino = struct.unpack_from("<IIQ", data, 32)
                    dev = os.makedev(major, minor)
                maps[pid].append((addr, addr + size, off, dev, ino, path))
        elif kind == 3 and misc & (1 << 13):
            pid, tid = struct.unpack_from("<II", data)
            name = (
                data[8 : len(data) - tail].split(b"\0", 1)[0].decode(errors="replace")
            )
            (when,) = struct.unpack_from("<Q", data, len(data) - tail + 8)
            execs[pid].append((when, tid, name))
    require(
        samples and events[10] and events[3], "missing samples, MMAP2 or exec records"
    )
    return samples, maps, execs, {str(k): v for k, v in events.items()}


@contextmanager
def original(folder):
    """Verify all original bytes, including feature tables beyond the sampled data section."""
    sealed = load(folder / "sampling-raw.json")
    with subprocess.Popen(
        ["zstd", "-qdc", folder / "perf.data.zst"], stdout=subprocess.PIPE
    ) as proc:
        h = hashlib.sha256()

        class Stream:
            length = 0

            def read(self, n):
                data = proc.stdout.read(n)
                self.length += len(data)
                h.update(data)
                return data

        stream = Stream()
        try:
            yield stream
            while stream.read(1 << 20):
                pass
            require(
                proc.wait() == 0
                and stream.length == sealed["bytes"]
                and h.hexdigest() == sealed["raw_sha256"],
                "native data decompression, size or logical SHA failed",
            )
        finally:
            if proc.poll() is None:
                proc.stdout.close()
                proc.kill()


def rows(folder):
    table = []
    count = 0
    with gzip.open(folder / "samples.jsonl.gz", "rt") as f:
        for line in f:
            key, *values = json.loads(line)
            if key == "symbol":
                number, dso, name = values
                require(
                    number == len(table)
                    and isinstance(dso, str)
                    and isinstance(name, str),
                    "invalid symbol table",
                )
                table.append((dso, name))
            elif key == "sample":
                pid, tid, when, ip, period, leaf, stack = values
                require(
                    0 <= leaf < len(table)
                    and all(0 <= s < len(table) for _, s in stack),
                    "invalid sampled symbol id",
                )
                count += 1
                yield (pid, tid, when, ip, period), table[leaf], [
                    (p, *table[s]) for p, s in stack
                ]
            else:
                require(
                    key == "done" and values == [count, len(table)] and not f.read(1),
                    "malformed sample seal",
                )
                return
    raise ValueError("incomplete perf script output")


def acquire(folder, tools, paths, cmd, cwd, env, perf):
    require(
        shutil.disk_usage(folder.parent).free > 6 * 2**30,
        "insufficient private disk for bounded sample",
    )
    folder.mkdir()
    trace = folder / "trace"
    trace.mkdir()
    native = list(
        map(str, [tools / "tree", trace, "tree", *[paths[n] for n in ROLES], *cmd])
    )
    # A separate FD-forwarding process keeps perf warnings out of Cargo stdout/stderr and preserves env.
    prefix = [
        str(perf),
        "record",
        "-N",
        "-T",
        "-P",
        "--clockid",
        "mono",
        "-e",
        "instructions:u",
        "-c",
        str(PERIOD),
        "--call-graph",
        "dwarf,4096",
        "-m",
        "256",
        "-o",
        str(folder / "perf.data"),
        "--",
    ]
    launch = [
        *prefix,
        sys.executable,
        "-IB",
        str(Path(__file__).resolve()),
        "forward",
        str(folder),
        *native,
    ]
    with (folder / "perf.stdout").open("xb") as so, (folder / "perf.stderr").open(
        "xb"
    ) as se:
        p = subprocess.run(launch, cwd=cwd, env=env, stdout=so, stderr=se, timeout=900)
    save(folder / "sampler-invocation.json", dict(outer=launch, status=p.returncode))
    save(
        folder / "invocation.json",
        dict(argv=list(map(str, cmd)), native=native, status=p.returncode),
    )
    for name in ("stdout", "stderr"):
        src = folder / name
        if src.is_file():
            with src.open("rb") as i, gzip.open(
                folder / (name + ".gz"), "xb", compresslevel=1
            ) as o:
                shutil.copyfileobj(i, o)
            src.unlink()
    require(
        p.returncode == 0
        and not re.search(
            rb"(?:lost [1-9]\d*|throttl|failed|denied)",
            (folder / "perf.stderr").read_bytes(),
            re.I,
        ),
        ("perf capture failed", folder, p.returncode),
    )
    return gzip.decompress((folder / "stdout.gz").read_bytes())


def decode(folder, perf):
    raw = folder / "perf.data"
    # Keep the compressed original if symbolization fails. Do not delete the native mmap data until success.
    packed = folder / "perf.data.zst"
    subprocess.run(["zstd", "-q", "-T2", "-2", raw, "-o", packed], check=True)
    save(
        folder / "sampling-raw.json",
        dict(
            raw_sha256=sha(raw),
            bytes=raw.stat().st_size,
            zstd_sha256=sha(packed),
            callback_sha256=sha(HERE / "sample_events.py"),
        ),
    )
    env = {
        **os.environ,
        "OHM_SAMPLE_ROWS": str(folder / "samples.jsonl.gz"),
        "DEBUGINFOD_URLS": "",
        "LC_ALL": "C",
    }
    with (folder / "decode.stdout").open("xb") as so, (folder / "decode.stderr").open(
        "xb"
    ) as se:
        proc = subprocess.run(
            [perf, "script", "--demangle", "-i", raw, "-s", HERE / "sample_events.py"],
            cwd=folder,
            env=env,
            stdout=so,
            stderr=se,
            timeout=900,
        )
    require(
        proc.returncode == 0 and (folder / "samples.jsonl.gz").is_file(),
        ("stack decode failed", folder),
    )
    raw.unlink()


def task_groups(folder):
    groups = {}
    parents = {}
    root = None
    for line in (folder / "trace/tasks.tsv").read_text().splitlines():
        k, *values = line.split("\t")
        v = list(map(int, values))
        if k == "root":
            root = v[0]
        elif k == "task":
            groups[v[0]] = v[1]
        elif k == "spawn":
            parents[v[1]] = v[0]
    require(
        root and set(groups) == set(parents) | {root}, "incomplete observed task IDs"
    )
    return root, groups, parents


def target_image(mapping, address, named):
    hits = [
        x
        for x in mapping
        if x[0] <= address < x[1] and (x[3], x[4]) == (named["dev"], named["ino"])
    ]
    if not hits:
        return None
    require(
        len({(p[0], p[2], p[5]) for p in hits}) == 1
        and Path(hits[0][5]).name == Path(named["path"]).name,
        ("ambiguous underlying sampled ELF", hits),
    )
    return address - hits[0][0] + hits[0][2]


def joined(folder):
    with original(folder) as fp:
        native, maps, execs, records = raw_report(fp)

    def iterator():
        for key, leaf, stack in rows(folder):
            require(native[key] > 0, ("decoded sample absent from raw", key))
            native[key] -= 1
            yield key, leaf, stack
        require(not any(native.values()), "perf script omitted hardware samples")

    return iterator(), maps, execs, records


def loop_sites(binary):
    """Disassemble the actual enrolled loop so child and thread hits name the two counted instructions."""
    asm = subprocess.check_output(
        ["objdump", "-d", "-w", "--no-show-raw-insn", binary], text=True
    )
    hits = {}
    for head, tail, symbol in re.findall(
        r"(?m)^\s*([0-9a-f]+):\s+dec[qwl]?\s+%\w+\s*\n\s*([0-9a-f]+):\s+jne\s+\1\s+<(main|count_instructions)(?:\+[^>]*)?>",
        asm,
    ):
        require(symbol not in hits, "multiple matched hot loops for " + symbol)
        hits[symbol] = [int(head, 16), int(tail, 16)]
    require(
        set(hits) == {"main", "count_instructions"},
        ("unrecognized native hot loop", hits),
    )
    return hits


def expensive(folder, target, label, sites):
    samples, maps, _, records = joined(folder)
    root, groups, _ = task_groups(folder)
    hot = Counter()
    stacks = Counter()
    for (pid, tid, _, ip, w), (dso, sym), stack in samples:
        if tid not in groups:
            continue
        require(groups[tid] == pid, "wrong calibration task group")
        if not (
            (label == "child" and tid == pid and pid != root)
            or (label == "thread" and tid != pid and pid == root)
        ):
            continue
        addr = target_image(maps.get(pid, ()), ip, target)
        if addr is None or addr not in sites.get(sym, ()):
            continue
        require(
            Path(dso).name == Path(target["path"]).name,
            "calibration DSO contradicted mapping",
        )
        hot[tid] += w
        if len(stack) >= 2 and any(f[2] for f in stack if f[0] != ip):
            stacks[tid] += w
    need = 1 if label == "child" else 2
    require(
        len(hot) == need
        and all(
            0.75 * 160_000_000 <= value <= 1.20 * 160_000_000
            and stacks[tid] >= 0.60 * value
            for tid, value in hot.items()
        ),
        ("sampling/calibration or known stack failed", label, hot, stacks),
    )
    return dict(
        expected_per_hot_tid=160_000_000,
        hot_periods={str(k): v for k, v in hot.items()},
        resolved_callchain_periods={str(k): v for k, v in stacks.items()},
        raw_record_counts=records,
    )


def verify_calibration(out):
    folder = out / "sampling-calibration"
    manifest = load(folder / "tools.json")
    binary = out / "counter-programs" / "loop"
    require(sha(binary) == manifest["loop"]["sha256"], "different calibration program")
    sites = loop_sites(binary)
    result = {
        label: expensive(folder / label, manifest["loop"], label, sites)
        for label in ("child", "thread")
    }
    require(
        result == load(folder / "qualified.json"),
        "original calibration results do not reopen",
    )
    return result


def prepare(root, tools, out):
    perf = Path(os.environ["OHM_DIAGNOSTIC_PERF"]).resolve(strict=True)
    with perf.open("rb") as f:
        require(
            perf.is_absolute() and f.read(4) == b"\x7fELF",
            "OHM_DIAGNOSTIC_PERF must name the real perf ELF",
        )
    folder = out / "sampling-calibration"
    folder.mkdir()
    build = subprocess.check_output([perf, "version", "--build-options"], text=True)
    require(
        re.search(r"libpython:\s*\[\s*on\s*\]", build)
        and re.search(r"(?:libdw-dwarf-unwind|libunwind):\s*\[\s*on\s*\]", build),
        "perf lacks Python or DWARF unwinding",
    )
    save(
        folder / "tools.json",
        dict(perf=identity(perf), options=build, loop=identity(tools / "loop")),
    )
    paths = {n: tools / "roles" / n for n in ROLES}
    result = {}
    for label, mode, copies in (("child", "1", "1"), ("thread", "thread", "2")):
        sub = folder / label
        acquire(
            sub,
            tools,
            paths,
            [str(tools / "loop"), mode, "80000000", copies],
            root,
            {"PATH": "/usr/bin:/bin", "HOME": str(root), "LC_ALL": "C"},
            perf,
        )
        decode(sub, perf)
        result[label] = expensive(
            sub, identity(tools / "loop"), label, loop_sites(tools / "loop")
        )
    save(folder / "qualified.json", result)
    verify_calibration(out)
    return perf


def record(folder, tools, paths, cargo_cli, src, env, perf):
    require(
        folder.name in ("edited", "restored") and folder.parent.name == "T",
        "sampling outside designated edits",
    )
    return acquire(folder, tools, paths, cargo_cli, src, env, perf)


# Match the defining path, not a type parameter in a different function's mangled name.
PHASES = (
    (
        "incremental graph validation",
        r"rustc_query_system::dep_graph::|rustc_dep_graph::",
    ),
    (
        "incremental persistence",
        r"rustc_incremental::|rustc_query_impl::(?:on_disk_cache|plumbing::on_disk)",
    ),
    ("metadata encoding", r"rustc_metadata::rmeta::encoder::"),
    ("metadata decoding", r"rustc_metadata::(?:rmeta::decoder|creader|locator)::"),
    (
        "type and trait analysis",
        r"rustc_(?:hir_typeck|trait_selection|next_trait_solver|borrowck|hir_analysis|infer)::",
    ),
    ("monomorphization and partitioning", r"rustc_monomorphize::"),
    ("Rust code generation", r"rustc_(?:codegen_ssa|codegen_llvm|codegen_gcc)::"),
    ("stable hashing", r"rustc_(?:stable_hash|data_structures::stable_hasher)::"),
    ("query dispatch", r"rustc_query_(?:impl|system)::"),
)


def family(image, symbol):
    if not symbol or symbol in ("[unknown]", "unknown"):
        return None
    if image == LLVM:
        return "LLVM"
    name = re.sub(r"\[[0-9a-f]{4,32}\]", "", symbol).lstrip("<")
    return next((label for label, pattern in PHASES if re.match(pattern, name)), None)


def proof_inputs(folder, counted):
    ids = load(folder / "sampling-images.json")
    with gzip.open(folder.parent.parent / "sdk/complete-release.json.gz", "rt") as f:
        registered = json.load(f)
    for name, h in PIN.items():
        v = ids[name]
        orig = registered["lib/" + name]
        require(
            v["sha256"] == orig["sha256"] == h
            and Path(v["path"]).name == name
            and all(v[k] == orig[k] for k in ("dev", "ino", "size")),
            ("unexpected signed compiler DSO", name),
        )
    call = load(folder / "invocation.json")
    outer = load(folder / "sampler-invocation.json")
    native = call["native"]
    require(
        call["status"] == outer["status"] == 0
        and native[2] == "tree"
        and outer["outer"][-len(native) :] == native,
        "record did not wrap the genuine tree collector",
    )
    edges = [
        s.split("\t") for s in (folder / "trace/exec.tsv").read_text().splitlines()
    ]
    subject = {}
    for name in TARGETS:
        v = counted["compilers"][name]
        pid, serial = v["pid"], v["serial"]
        matching = [e for e in edges if int(e[1]) == pid]
        require(
            len(matching) == 1
            and matching[0][:4] == [str(serial), str(pid), "1", "1"]
            and matching[0][6] == native[3],
            (name, "nonunique selected image"),
        )
        args = (folder / "trace" / f"args-{serial:04d}").read_bytes().split(b"\0")
        require(
            args.count(b"--crate-name") == 1
            and args[args.index(b"--crate-name") + 1] == name.encode()
            and b"-Zthreads=8" in args
            and b"--emit=dep-info,metadata,link" in args
            and not any(b"self-profile" in s for s in args),
            (name, "changed ordinary compiler argv"),
        )
        subject[pid] = name
    return ids, subject


def breakdown(folder, counted):
    ids, subject = proof_inputs(folder, counted)
    _, groups, parents = task_groups(folder)
    samples, maps, execs, record_counts = joined(folder)
    inodes = {(f["dev"], f["ino"]) for f in ids.values()}
    selected = {
        pid: [v for v in maps[pid] if (v[3], v[4]) in inodes] for pid in subject
    }
    epochs = {}
    for pid, name in subject.items():
        require(
            {Path(f[5]).name for f in selected[pid]} == set(PIN),
            (name, "missing original executable MMAP2/inode"),
        )
        times = [
            when
            for when, tid, program in execs[pid]
            if tid == pid and program == "rustc"
        ]
        require(
            len(times) == 1, (name, "missing unique kernel exec marker", execs[pid])
        )
        epochs[pid] = times[0]
        eligible = set()
        for t in groups:
            u = t
            while u in parents and u != pid:
                u = parents[u]
            if u == pid:
                eligible.add(t)
        require(
            len(eligible) == counted["compilers"][name]["tasks"]
            and all(groups[t] == pid for t in eligible),
            (name, "scope contains unpriced child process or missing thread"),
        )
    total = Counter()
    known = Counter()
    unwind = Counter()
    leaves = defaultdict(Counter)
    stacks = defaultdict(Counter)
    funcs = defaultdict(Counter)
    tids = defaultdict(set)

    def frame(pid, ip, dso, sym):
        advertised = Path(dso).name
        image = next(
            (
                n
                for n, obj in ids.items()
                if target_image(selected[pid], ip, obj) is not None
            ),
            None,
        )
        require(
            not (image or advertised in PIN) or advertised == image,
            (
                "symbol DSO differs from kernel IP mapping",
                pid,
                hex(ip),
                advertised,
                image,
            ),
        )
        return image, sym

    for (pid, tid, when, ip, weight), leaf, chain in samples:
        if pid not in subject or when < epochs[pid]:
            continue
        name = subject[pid]
        require(groups.get(tid) == pid, ("wrong kernel sample owner", pid, tid))
        tids[name].add(tid)
        total[name] += weight
        image, sym = frame(pid, ip, *leaf)
        if image and sym not in ("", "[unknown]", "unknown"):
            known[name] += weight
            funcs[name][(image, sym)] += weight
        leaf_label = family(image, sym) if image else None
        leaves[name][leaf_label or "other or unresolved"] += weight
        if len(chain) > 1 and chain[0][0] != ip and chain[-1][0] == ip:
            chain.reverse()
        labels = []
        if chain and chain[0][0] == ip:
            for pa, d, s in chain:
                img, fn = frame(pid, pa, d, s)
                if img:
                    labels.append(family(img, fn))
            if any(
                pa != ip and s not in ("", "[unknown]", "unknown") for pa, _, s in chain
            ):
                unwind[name] += weight
        label = leaf_label or next((s for s in labels if s), None)
        stacks[name][label or "other or unresolved"] += weight
    out = {}
    for name in TARGETS:
        orig = counted["compilers"][name]["instructions"]
        mass = total[name]
        require(
            0.90 * orig <= mass <= 1.10 * orig
            and known[name] >= 0.70 * mass
            and unwind[name] >= 0.70 * mass
            and len(tids[name]) >= 2
            and mass >= 200 * PERIOD,
            (
                name,
                "sample amount, signed symbol, unwind or thread coverage",
                orig,
                mass,
                known[name],
                unwind[name],
            ),
        )
        require(
            sum(leaves[name].values()) == sum(stacks[name].values()) == mass,
            "overlapping phase attribution",
        )
        out[name] = dict(
            inclusive_instructions=orig,
            sampled_periods=mass,
            sample_count=mass // PERIOD,
            represented_threads=len(tids[name]),
            signed_named_leaf_periods=known[name],
            oriented_resolved_stack_periods=unwind[name],
            exclusive_leaf_periods=dict(leaves[name]),
            nearest_named_stack_periods=dict(stacks[name]),
            top_signed_leaf_functions=[[*k, v] for k, v in funcs[name].most_common(40)],
        )
    return dict(
        scope="diagnostic weighted periods; no performance comparison",
        event="instructions:u",
        period=PERIOD,
        thresholds=dict(
            count_ratio=[0.9, 1.1],
            minimum_named_signed_leaf=0.70,
            minimum_oriented_multiframe=0.70,
        ),
        raw_record_counts=record_counts,
        roles=out,
    )


def verify(folder, counted):
    """Reopen compressed native data, original ownership, typed argv and all decoded sample identities."""
    stored = load(folder / "sampling-raw.json")
    packed = folder / "perf.data.zst"
    require(
        sha(packed) == stored["zstd_sha256"]
        and sha(HERE / "sample_events.py") == stored["callback_sha256"]
        and sha(folder / "samples.jsonl.gz")
        == load(folder / "decoded-seal.json")["decoded_sha256"],
        "changed native or decoded sample evidence",
    )
    result = breakdown(folder, counted)
    if (folder / "sampling-summary.json").exists():
        require(
            result == load(folder / "sampling-summary.json"),
            "changed reported phase weights",
        )
    return result


def summarize(folder, counted, perf):
    native = load(folder / "invocation.json")["native"]
    lib = Path(native[3]).resolve(strict=True).parent.parent / "lib"
    save(folder / "sampling-images.json", {n: identity(lib / n) for n in PIN})
    decode(folder, perf)
    save(
        folder / "decoded-seal.json",
        dict(decoded_sha256=sha(folder / "samples.jsonl.gz")),
    )
    result = verify(folder, counted)
    save(folder / "sampling-summary.json", result)
    return result


if __name__ == "__main__" and sys.argv[1:2] == ["forward"]:
    path = Path(sys.argv[2])
    args = sys.argv[3:]
    with (path / "stdout").open("xb") as so, (path / "stderr").open("xb") as se:
        os.dup2(so.fileno(), 1)
        os.dup2(se.fileno(), 2)
    os.execv(args[0], args)
