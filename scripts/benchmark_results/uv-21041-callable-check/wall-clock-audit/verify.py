"""Recalculate displayed-Cargo and external intervals from the original 24 pairs."""
import argparse
import hashlib
import json
import re
import statistics
import tarfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
MANIFEST = "eb84befb7a94f3433d9489dd4f9ff341092d3031a6afdeb5646548af85b58d38"
CHECK = ["/tmp/uv-workflow-search/sdk/bin/cargo", "check", "-p", "uv-client", "--locked", "--offline", "-j8"]
STEP = 10_000_000  # The signed Cargo truncates subsecond nanoseconds to centiseconds.
POLL = 50_000_000  # Intended maximum timeout polling sleep, excluding scheduler oversleep.
STEMS = {"uv-cache", "uv-client", "uv-configuration", "uv-distribution-types", "uv-install-wheel",
         "uv-metadata", "uv-pypi-types", "uv-torch"}


def require(ok, msg):
    if not ok:
        raise ValueError(msg)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_archive(filename, checksum):
    with filename.open("rb") as f:
        require(hashlib.file_digest(f,"sha256").hexdigest()==checksum, "archive byte identity")


def visit(records, prefix):
    clock = json.loads(records[prefix+"wall/ordinary.json"])
    lines = records[prefix+"wall/cargo.stderr"].splitlines()
    require(len(lines) == 9, "unexpected native stderr")
    checks = [re.fullmatch(rb"    Checking (uv-[a-z-]+) v[^ ]+ \(/tmp/uv-workflow-search/uv/crates/\1\)", x)
              for x in lines[:-1]]
    require(all(checks) and {x[1].decode() for x in checks} == STEMS, "real eight crates")
    finished = re.fullmatch(rb"    Finished `dev` profile \[unoptimized \+ debuginfo\] target\(s\) in (\d+)\.(\d{2})s",
                            lines[-1])
    require(finished, "signed Cargo completion line")
    cargo = (100*int(finished[1])+int(finished[2]))*STEP
    outer = clock["ns"]
    require(clock["argv"] == clock["invoked"] == CHECK and clock["mode"] == "native" and clock["exit"] == 0 and
            outer == clock["end_ns"]-clock["start_ns"] and 0 < cargo <= outer, "enclosing native clock")
    counter = json.loads(records[prefix+"clock/whole-clock.json"])
    require(counter["event_errno"] == counter["code"] == 0 and counter["enabled"] == counter["running"] > 0 and
            counter["instructions"] > 0 and counter["stop"] > counter["start"], "independent whole-PMU visit")
    return {"outer_ns":outer, "cargo_display_floor_ns":cargo, "start_ns":clock["start_ns"],"end_ns":clock["end_ns"],
            "other_pmu_visit_wall_ns":counter["stop"]-counter["start"],"boot":clock["boot"],"cpus":clock["cpus"]}


def analyze(panel, prefix, records):
    control, candidate = panel["roles"]
    rows = []
    previous = 0
    host = None
    for i,order in enumerate(panel["orders"]):
        visits = {}
        for role in order:
            row = visit(records,f"{prefix}/uv-client/pair-{i}-{role}/")
            require(previous < row["start_ns"] < row["end_ns"], "original pair or order")
            previous = row["end_ns"]
            if host is None:
                host = (row["boot"], row["cpus"])
            require((row["boot"],row["cpus"]) == host,"affinity or boot")
            visits[role] = row
        a,t = visits[control], visits[candidate]
        aa,tt = a["outer_ns"],t["outer_ns"]
        sa,st = a["cargo_display_floor_ns"],t["cargo_display_floor_ns"]
        rows.append({
            "pair":i,"order":order,"control_ns":aa,"treatment_ns":tt,"control_cargo_floor_ns":sa,"treatment_cargo_floor_ns":st,
            "external_ratio":aa/tt,"cargo_display_ratio":sa/st,
            "inner_ratio_low":sa/(st+STEP),"inner_ratio_high":(sa+STEP)/st,
            "poll50_full_ratio_low":(aa-POLL)/tt,"poll50_full_ratio_high":aa/(tt-POLL),
            "poll50_wall_gain_min_ms":(aa-tt-POLL)/1e6,
            "certified_full_ratio_low":sa/tt,"certified_full_ratio_high":aa/st,
            "separate_pmu_wall_ratio":a["other_pmu_visit_wall_ns"]/t["other_pmu_visit_wall_ns"],
            "cargo_floor_gap_to_two_ms":(st-sa/2)/1e6,
            "outer_gap_to_two_ms":(tt-aa/2)/1e6})
    require(len(rows)==8 and sum(row["order"][0]==control for row in rows)==4,"eight counterbalanced pairs")
    numeric = [k for k in rows[0] if k not in ("pair","order")]
    return {"median":{k:statistics.median([r[k] for r in rows]) for k in numeric},
            "min":{k:min(r[k] for r in rows) for k in numeric},
            "max":{k:max(r[k] for r in rows) for k in numeric},
            "certified_full_wins":sum(r["certified_full_ratio_low"]>1 for r in rows),
            "poll50_full_wins":sum(r["poll50_full_ratio_low"]>1 for r in rows),"pairs":rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original",nargs=2,metavar=("PANEL","ZIP"),action="append",default=[])
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--json",action="store_true")
    args=parser.parse_args()
    raw=(ROOT/"manifest.json").read_bytes()
    require(digest(raw)==MANIFEST,"sealed provenance")
    manifest=json.loads(raw)
    read_archive(ROOT/"records.tar.xz", manifest["archive_sha256"])
    with tarfile.open(ROOT/"records.tar.xz","r:xz") as bundle:
        members=bundle.getmembers()
        require(len(members)==144 and all(m.isfile() and 0<m.size<8192 for m in members),"selected evidence count/type/size")
        records={m.name:bundle.extractfile(m).read() for m in members}
    require({k:digest(v) for k,v in records.items()}==manifest["members"],"original member checksums")
    for label,filename in args.original:
        panel=manifest["panels"][label]
        path=Path(filename)
        require(path.stat().st_size==panel["original"]["size_in_bytes"],"service size")
        read_archive(path,panel["original"]["digest"].removeprefix("sha256:"))
        with ZipFile(path) as original:
            require(len(original.namelist())==len(set(original.namelist())),"service ZIP duplicate")
            for key,data in records.items():
                owner,member=key.split("/",1)
                if owner==label: require(original.read(member)==data,"selected bytes versus service ZIP")
    out={name:analyze(panel,name,records) for name,panel in manifest["panels"].items()}
    if args.self_test:
        key=next(iter(r for r in records if r.endswith("/wall/cargo.stderr")))
        bad=dict(records);bad[key]=records[key]+b"    Finished in 0.00s\n"
        try:
            visit(bad,key.removesuffix("wall/cargo.stderr"))
        except ValueError:
            pass
        else:
            raise RuntimeError("duplicate completion accepted")
        name="production"
        panel=dict(manifest["panels"][name]); panel["orders"]=[o[::-1] for o in panel["orders"]]
        try:
            analyze(panel,name,records)
        except ValueError:
            pass
        else:
            raise RuntimeError("reversed physical chronology accepted")
    if args.json:
        print(json.dumps(out,indent=2,sort_keys=True))
    else:
        for name,panel in out.items():
            m=panel["median"]
            print(f"{name}: outer {m['external_ratio']:.5f}, Cargo {m['cargo_display_ratio']:.5f}, "
                  f"full CLI median in [{m['certified_full_ratio_low']:.5f}, {m['certified_full_ratio_high']:.5f}], "
                  f"{panel['certified_full_wins']}/8 certified directional wins")


if __name__=="__main__":
    main()
