"""Profile an unmodified ordinary ty_ide compiler and retain its pre/post native products."""
from collections import Counter, defaultdict
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess as sp

import perf_tools as perf
import semantic_pcs

HERE = Path(__file__).resolve().parent
REF = json.loads((HERE / "reference.json").read_bytes())
PERIOD = 1_000_003


def record(path, raw, env, command):
    # perf modifies its own environment. Restore the complete original Cargo
    # environment immediately before the exec-stop observer starts Cargo.
    restore = ["/usr/bin/env", "-i", *(k + "=" + v for k, v in sorted(env.items()))]
    return perf.record(path, raw, [*restore, *command], PERIOD)


def prepare(w, env, observer):
    w.guard()
    case = w.proof / "pc-calibration"
    case.mkdir()
    perf.ROOT, perf.B, perf.KITS = w.root, case, HERE
    path = perf.prepare_perf()
    source = w.root / "pc-burn.c"
    source.write_text("#include <stdint.h>\nint main(void) { volatile uint64_t s=1; for(uint64_t i=0;i<10000000;i++) s=s*33+i; return s==0; }\n")
    burn = w.root / "pc-burn"
    sp.run(["cc", "-O1", source, "-o", burn], check=True)
    raw = w.root / "calibration.perf"
    sp.run(record(path, raw, env, [observer, case, burn, "calibrate"]), env=env, check=True, timeout=90)
    assert perf.decode(path, raw, case) >= 10
    w.put(case / "complete.json", {"period": PERIOD, "raw": w.hf(raw), "observer": w.hf(observer)})
    return path


def identity(path):
    stat = path.stat()
    with path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    return {"bytes": stat.st_size, "sha256": digest, "dev": stat.st_dev, "ino": stat.st_ino, "mtime_ns": stat.st_mtime_ns}


def keep(w, path, entry):
    if entry["bytes"] > 128 * 2**20:
        return "over registered 128 MiB member limit"
    directory = w.proof / "ty-ide-bodies"
    directory.mkdir(exist_ok=True)
    dest = directory / (entry["sha256"] + ".zst")
    if not dest.exists():
        w.guard()
        if sum(p.stat().st_size for p in directory.glob("*.zst")) > 320 * 2**20:
            return "over registered 320 MiB compressed artifact budget"
        with dest.open("xb") as f:
            sp.run(["zstd", "-q", "-3", "-c", path], stdout=f, check=True)
    return dest.name


def products(w, td, artifacts, incremental):
    """Record physical ty_ide rlib/rmeta and prior/session contents outside all counters."""
    member, = (a for a in artifacts if a["target"]["name"] == "ty_ide")
    outputs = {}
    for name in member["filenames"]:
        path = Path(name)
        entry = identity(path)
        entry["body"] = keep(w, path, entry)
        outputs[str(path)] = entry
    assert sorted(Path(x).suffix for x in outputs) == [".rlib", ".rmeta"]
    sessions = {}
    if incremental is not None:
        assert incremental.is_dir()
        for dep_graph in sorted(incremental.glob("ty_ide-*/s-*/dep-graph.bin")):
            session = {}
            for path in sorted(dep_graph.parent.iterdir()):
                if path.is_file() and not path.is_symlink() and path.suffix in (".o", ".bin"):
                    entry = identity(path)
                    if path.name in ("dep-graph.bin", "work-products.bin"):
                        entry["body"] = keep(w, path, entry)
                    session[path.name] = entry
            sessions[str(dep_graph.parent)] = session
        assert sessions, "no actual ty_ide incremental session"
    w.put(td / "ty-ide-products.json", {"outputs": outputs, "sessions": sessions})


def processes(w, where):
    rust = w.sdk / "bin/rustc"
    wild = w.sdk / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    identities = {(p.stat().st_dev, p.stat().st_ino): p.name for p in (rust, wild)}
    images, counts, tids = {}, Counter(), defaultdict(set)
    unclocked = defaultdict(list)
    for line in (where / "epochs.tsv").read_text().splitlines():
        fields = line.split()
        if fields[0] == "I":
            n, pid, tid, start = map(int, fields[1:5])
            cells = (where / f"{n:05}.nul").read_bytes().decode().split("\0")
            assert cells.pop() == "" and int(cells[0]) == pid
            dev, ino = map(int, cells[1:3])
            executable = identities.get((dev, ino))
            argv = cells[4:]
            if executable == "rustc" and "--crate-name" in argv:
                owner = argv[argv.index("--crate-name") + 1]
            elif executable == "ld.bfd":
                owner = executable
            else:
                continue
            images[n] = dict(name=owner, reason=fields[5], pid=pid, epoch=n, start_ns=start, argv=argv)
        elif fields[0] == "C":
            n, pid, tid, count, enabled, running = map(int, fields[1:])
            assert enabled == running, "multiplexed user-count interval"
            if count and not enabled:
                unclocked[n].append({"tid": tid, "instructions": count})
            counts[n] += count
            tids[n].add(tid)
    native = Counter(v["name"] for v in images.values() if v["reason"] == "exec")
    assert native == Counter({"ty_project": 1, "ty_ide": 1, "ty_server": 1, "e2e": 1, "ld.bfd": 1}), native
    for n, v in images.items():
        v.update(threads=sorted(tids[n]), instructions=counts[n], unclocked=unclocked[n])
    return list(images.values())


def typed_argv(images):
    return {x["name"]: x["argv"] for x in images if x["reason"] == "exec" and x["name"] != "ld.bfd"}


def normalized(args):
    # Signed Cargo compilation_files.rs:626,1016. Exactly this component may
    # move across independent SDK installations. Preserve all source and unit
    # hashes; both absolute roots and the command prefix stay fixed.
    layout = re.compile(r"(/home/runner/work/_temp/ohm-foreign-join/(?:target/debug/build/workspaces/f44635c822fcb5f3|shared/debug/build/registries)/)v2-([a-f0-9]{16})(?=/)")
    shards = set()
    def replace(match):
        shards.add(match[2])
        return match[1] + "v2-{registered-compiler-namespace}"
    stable = {owner: [layout.sub(replace, arg) for arg in argv] for owner, argv in args.items()}
    assert len(shards) == 1 and len(stable) == 4
    return stable, next(iter(shards))


def inputs(w, td, artifacts):
    owner, = (v for v in processes(w, td/"tasks") if v["name"] == "ty_ide" and v["reason"] == "exec")
    extern = {}
    args = owner["argv"]
    for i, arg in enumerate(args):
        if arg == "--extern" and "=" in args[i + 1]:
            name, path = args[i+1].split("=", 1)
            assert name not in extern
            extern[name] = identity(Path(path))
    assert len(extern) > 10
    w.put(td/"actual-ty-ide-extern.json", extern)
    return owner


def preserve_profile(w, raw):
    cap = w.proof / "pc-readback"
    cap.mkdir()
    assert 0 < raw.stat().st_size < 256 * 2**20
    packed = cap / "perf.data.zst"
    with packed.open("xb") as f:
        sp.run(["zstd", "-q", "-3", "-c", raw], stdout=f, check=True)
    w.put(cap / "raw-identity.json", {"bytes": raw.stat().st_size, "sha256": w.hf(raw), "compressed": w.hf(packed)})


def close(w, path, raw, profiled, ordinary):
    primary = "ty_ide"
    measured = processes(w, profiled / "tasks")
    baseline = processes(w, ordinary / "tasks")
    w.put(profiled / "actual-processes.json", measured)
    w.put(ordinary / "actual-processes.json", baseline)
    actual = typed_argv(measured)
    assert actual == typed_argv(baseline), "different same-worker literal compiler argv"
    stable, shard = normalized(actual)
    registered, prior_shard = normalized(REF["argv"])
    assert stable == registered, "different source command or non-layout input"
    w.put(profiled/"cross-boot-layout.json", {"this": shard, "registered": prior_shard})
    assert not any(v["unclocked"] for v in measured+baseline if v["name"] == primary), "zero-time interval on the selected actual compiler"
    target, = (x for x in measured if x["name"] == primary)
    unprofiled, = (x for x in baseline if x["name"] == primary)
    assert abs(target["instructions"] / unprofiled["instructions"] - 1) < .03
    assert abs(target["instructions"] / REF["instructions"]["rustc:ty_ide"] - 1) < .05
    cap = w.proof / "pc-readback"
    assert cap.is_dir()
    (cap / "exec").mkdir()
    (cap / "exec/epochs.tsv").write_bytes((profiled / "tasks/epochs.tsv").read_bytes())
    w.put(cap / "owner-epochs.json", {primary: target})
    n = perf.decode(path, raw, cap)
    proc = sp.run([*perf.private_argv(path), "buildid-list", "--with-hits", "-i", raw], env=perf.clean_subprocess(), check=True, capture_output=True)
    (cap / "buildids.txt").write_bytes(proc.stdout)
    (cap / "buildids.stderr").write_bytes(proc.stderr)
    driver, = (w.sdk / "lib").glob("librustc_driver-*.so")
    driver_sha = w.hf(driver)
    assert driver_sha == "53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52"
    semantic_pcs.analyze(raw, cap, {"driver": {"path": str(driver.resolve()), "sha256": driver_sha}}, minimum=10_000)
    w.put(cap / "verified.json", {"all_samples": n, "owner": primary, "instructions": target["instructions"], "source": w.hf(HERE / "reference.json"), "symbols": w.hf(cap / "semantic.json")})
