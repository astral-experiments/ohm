"""Reopen the signed history, kernel samples and disjoint leaf locations independently."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

BASE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BASE), str(BASE / "signed23-replay")]
import controls
import owner_read
import pc_raw
import reopen
import semantic_pcs

TARGET = "ty_python_semantic"
SOURCE = "d57fd1515986dccecdcece8da85e651bfb4b81f9"
CARGO = "7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed"
STUDY = "b25442589d86ea709d9be177c54b815c878be945"


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(z, name):
    return json.loads(z.read(name))


def native_controls(z, ref):
    binding = read(z, "sdk.json")
    official = json.loads((BASE / "signed23-source.json").read_bytes())
    tools = read(z, "pc-sdk.json")
    terminal = read(z, "pc-complete.json")
    check(terminal["head"] == STUDY and terminal["native"] and terminal["boot"] == read(z, "worker.json")["boot"], "native worker")
    check(binding["asset"] == official["assets"]["archive"] and binding["provenance"] == official["provenance"] and len(binding["members"]) == 79, "signed release")
    cargo = binding["provenance"]["sources"]["cargo"]["revision"]
    rust = binding["provenance"]["sources"]["rust"]["revision"]
    check(cargo == CARGO == ref["cargo_source"] and rust == SOURCE == ref["source"], "release source")
    for name, row in tools.items():
        members = [info for path, info in binding["members"].items() if row["path"].endswith("/" + path)]
        check(len(members) == 1 and ref[name] == row["sha256"] == members[0][3], "physical release member " + name)
    stages = {p: read(z, "release23/" + p + "/phase.json") for p in reopen.PHASES}
    ordinary = controls.ordinary(z, stages)
    check(ordinary == ref["ordinary"], "physical edited and original historical verdict/roster")
    meta = {p: s["workspace_rmeta"] for p, s in stages.items() if p != "invalid"}
    check(meta["old"] == meta["old-unchanged"] and meta["edited"] == meta["new-unchanged"] == meta["repair"] and all(len(v) == 31 for v in meta.values()), "native output bodies")
    same = sorted(n for n, v in meta["edited"].items() if meta["clean"].get(n) == v)
    check(same == ref["empty_matches"], "whole independent metadata equivalence scope")
    schema = json.loads((BASE / "signed23-replay/compiler-schema.json").read_bytes())
    check(schema["rust"] == SOURCE, "metadata decoder source")
    definitions = reopen.witnesses(z, (schema["symbols"], schema["tables"]))
    check(definitions == ref["definitions"], "definition-level warm/independent-empty oracle")
    edit = {r["crate"]: r["argv"] for r in read(z, "release23/edited/rustcs.json")}
    repair = {r["crate"]: r["argv"] for r in read(z, "release23/repair/rustcs.json")}
    check(edit == repair and {k: owner_read.fingerprint(v) for k, v in edit.items()} == ref["normalized_argv"], "unchanged executed arguments")
    return tools, edit, {"source": rust, "cargo": cargo, "run_head": STUDY, "boot": terminal["boot"], "release_asset": binding["asset"],
        "roles_sha256": {k:v["sha256"] for k,v in tools.items()}, "ordinary": ordinary, "physical_empty_equal": same, "definitions": definitions}


def owners(z, edit, rustc):
    images = {}
    for member in z.namelist():
        path = Path(member)
        if path.parent != Path("profile/exec") or path.suffix != ".nul":
            continue
        data = z.read(member).split(b"\0")
        check(data.pop() == b"" and len(data) >= 5, "complete kernel exec")
        pid, dev, ino, exe, *argv = (s.decode() for s in data)
        images[int(path.stem)] = (int(pid), int(dev), int(ino), exe, argv)
    by_image = Counter()
    threads = defaultdict(set)
    times = defaultdict(list)
    for line in z.read("profile/exec/epochs.tsv").decode().splitlines():
        row = line.split()
        if row[0] == "I":
            serial, pid, tid, stamp = map(int, row[1:5])
            check(images[serial][0] == pid and row[5] in ("first", "exec"), "image history")
            times[pid].append((stamp, serial, row[5]))
        elif row[0] == "C":
            serial, pid, tid, count, enabled, running = map(int, row[1:])
            check(images[serial][0] == pid and enabled == running and (enabled or not count), "disjoint task counter")
            by_image[serial] += count
            threads[serial].add(tid)
        else:
            check(row[0] == "M", "unknown PMU record")
    out = {}
    for pid, epochs in times.items():
        check(epochs == sorted(epochs), "time-ordered image history")
        for start, serial, kind in epochs:
            _, dev, ino, path, argv = images[serial]
            if kind != "exec" or (dev, ino, path) != (rustc["device"], rustc["inode"], rustc["path"]) or "--out-dir" not in argv or "--crate-name" not in argv:
                continue
            name = argv[argv.index("--crate-name") + 1]
            check(name not in out and name in edit and edit[name] == argv and start == epochs[-1][0], "owned rustc exact argv/epoch")
            out[name] = {"pid": pid, "epoch": serial, "start_ns": start, "threads": sorted(threads[serial]), "instructions": by_image[serial],
                         "argv_sha256": sha(json.dumps(argv,separators=(",",":")).encode())}
    check(out == read(z, "profile/owner-epochs.json") and out.keys() == edit.keys(), "all twelve measured identities")
    return out


def score(z, tools, owner, local_driver=None):
    prefix = "profile/"
    def get(n):
        return read(z, prefix + n)
    summary = get("semantic.json")
    receipt = get("raw-identity.json")
    compressed = z.read(prefix + "perf.data.zst")
    check(sha(compressed) == receipt["compressed_sha256"], "compressed PMU stream")
    raw = subprocess.run(["zstd", "-q", "-dc"], input=compressed, stdout=subprocess.PIPE, check=True).stdout
    check(len(raw) == receipt["bytes"] and sha(raw) == receipt["sha256"], "original PERF_FILE")
    period, ips, kinds, _, _, skid = pc_raw.raw_records(raw)
    check(period == 1000003 and not any(kinds.get(k) for k in (2, 5, 6, 13)), "period/loss/throttle")
    frames, decoded = pc_raw.symbol_rows(io.BytesIO(z.read(prefix + "samples.ndjson.gz")))
    check(Counter(datum for datum, _, _ in decoded) == ips, "raw IP/PID/TID/time/event submultiset")
    own = Counter({val: n for val,n in ips.items() if val[0] == owner["pid"] and val[2] >= owner["start_ns"]})
    check(all(k[1] in owner["threads"] for k in own), "selected physical threads")
    n = own.total()
    check(n >= 5000 and abs(n * period / owner["instructions"] - 1) < .03, "per-process sampling coverage")
    maps = semantic_pcs.mappings(raw, owner["pid"])
    physical = summary["binaries"]
    mapids = {line.split(maxsplit=1)[1]:line.split(maxsplit=1)[0] for line in z.read(prefix+"buildids.txt").decode().splitlines() if len(line.split(maxsplit=1))==2}
    driver = tools["driver"]["path"]
    check(physical[driver]["sha256"] == tools["driver"]["sha256"], "mapped signed driver")
    auth = []
    for row in maps:
        name = row["name"]
        if name not in physical:
            continue
        obj = physical[name]
        inode = (row.get("major"), row.get("minor"), row.get("inode")) == (os.major(obj["device"]), os.minor(obj["device"]), obj["inode"])
        bid = obj["gnu_build_id"]
        if inode or (bid and (bid == row.get("buildid") or bid == mapids.get(name))):
            auth.append(row)
    expected = Counter()
    unresolved = Counter()
    for event, weight in own.items():
        ip = event[4]
        if event in skid:
            unresolved["kernel skid"] += weight
            continue
        pos = {(m["name"], m["off"] + ip - m["base"]) for m in auth if m["base"] <= ip < m["base"] + m["length"]}
        if len(pos) != 1:
            unresolved["unbound or ambiguous executable mapping"] += weight
            continue
        name, off = pos.pop()
        vas = {va+off-base for base,va,filesz,_ in physical[name]["segments"] if base <= off < base+filesz}
        if len(vas) != 1:
            unresolved["outside executable file bytes"] += weight
            continue
        expected[(ip,name,vas.pop())] += weight
    data = z.read(prefix+"leaf-placements.ndjson.gz")
    check(sha(data) == summary["leaf_placements_sha256"], "leaf range custody")
    leaves = [json.loads(s) for s in gzip.decompress(data).splitlines()]
    observed = Counter()
    dsos = Counter()
    cover = Counter()
    concrete = Counter()
    for r in leaves:
        ip,name,va,weight = r["ip"],r["dso"],r["va"],r["samples"]
        observed[ip,name,va] += weight
        check(all(start <= va < start + size and sym for start,size,sym in r["symbol_ranges"]), "bounded physical symbol")
        source = r["source_frames"]
        line = any(x["FileName"] and x["Line"] for x in source)
        category = "inline source" if line and len(source)>1 else "source line" if line else "bounded ELF symbol" if r["symbol_ranges"] else "unresolved symbol"
        check(category == r["resolution"], "source and symbol coverage")
        dsos[name] += weight
        cover[category] += weight
        syms = {v[2] for v in r["symbol_ranges"]}
        if len(syms) != 1:
            label = "[unresolved physical symbol]" if not syms else "[multiple ELF symbols at this PC]"
        else:
            label = next((s["FunctionName"] for s in source if s["FunctionName"] not in ("","??")), next(iter(syms)))
        concrete[(Path(name).name, label)] += weight
    check(observed == expected and unresolved == summary["unplaced"] and dsos == summary["source_dsos"] and cover == summary["coverage"], "reopened native mapping partition")
    check(sum(dsos.values()) + unresolved.total() == n == summary["samples"] and n*period == summary["represented_instructions"] and kinds[9] == summary["all_process_samples"], "complete selected denominator")
    if local_driver is not None:
        validated = semantic_pcs.file_info(local_driver)
        for key in ("sha256","bytes","gnu_build_id","segments","debug_sections"):
            check(validated[key] == physical[driver][key], "local signed driver " + key)
        vas = {r["va"] for r in leaves if r["dso"] == driver}
        ranges = semantic_pcs.symbol_ranges(local_driver, vas)
        for r in leaves:
            if r["dso"] == driver:
                check(sorted(ranges[r["va"]]) == sorted(map(tuple,r["symbol_ranges"])), "local signed .symtab membership")
    return {"hardware_instructions": owner["instructions"], "sample_period": period, "owner_samples": n, "represented_instructions": n*period,
        "all_process_samples": kinds[9], "coverage": cover, "unplaced": unresolved, "dsos": {Path(k).name:v for k,v in dsos.items()},
        "driver": {k:physical[driver][k] for k in ("sha256","gnu_build_id","bytes","debug_sections")},
        "top_exclusive_functions":[[so, label, weight] for (so,label),weight in concrete.most_common()],
        "raw_sha256": receipt["sha256"], "raw_bytes": receipt["bytes"], "coverage_denominator": "all samples after genuine target compiler exec in that kernel PID",
        "samples_frame_count":len(frames)}


def run(path, digest, driver=None):
    with path.open("rb") as f:
        check(hashlib.file_digest(f,"sha256").hexdigest() == digest, "archive transport SHA-256")
    ref = json.loads((BASE/"pc-reference.json").read_bytes())
    with zipfile.ZipFile(path) as z:
        check(len(z.namelist()) == len(set(z.namelist())) and z.testzip() is None, "ZIP members")
        tools, edit, native = native_controls(z, ref)
        target = owners(z, edit, tools["rustc"])[TARGET]
        return {"native":native, "target":target, "pc":score(z, tools, target, driver)}


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("archive",type=Path)
    ap.add_argument("sha256")
    ap.add_argument("output",type=Path)
    ap.add_argument("--driver",type=Path)
    ns=ap.parse_args()
    ns.output.write_text(json.dumps(run(ns.archive,ns.sha256,ns.driver),indent=2,sort_keys=True)+"\n")
