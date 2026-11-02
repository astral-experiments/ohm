"""Replay all eight blocking-wall pairs and both hardware counters from the retained native samples."""
from fractions import Fraction
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import re
import runpy
import statistics
import struct
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
OBS = HERE / "samples.tar.xz"
ARGS = ["/tmp/ohm-over18-named-test/sdk/bin/cargo", "build", "--locked", "--offline", "-j8", "-p", "uv-cli"]
NAMES = {"build_script_build", "uv_python", "uv_cli"}
ORDER = ["PC", "CP", "CP", "PC", "CP", "PC", "PC", "CP"]
def digest(data):
    return hashlib.sha256(data).hexdigest()
def hash_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()
def require(value, msg):
    if not value:
        raise ValueError(msg)
def replay(raw, members, origin):
    def doc(name): return json.loads(raw[name])
    guard = doc("result.json")
    require(digest(raw["result.json"]) == origin["result_sha256"], "original scored result")
    require(guard["registration"] == origin["protocol_sha256"] and set(guard["rows"]) == set("12345678"), "registered panel")
    require(doc("calibration.json")["host"]["boot"] == origin["boot"] and digest(raw["calibration.json"]) == origin["calibration_sha256"], "physical calibration")
    cal = doc("calibration.json")
    require(len(cal["inherited"]) == 28 and len(set(cal["host"]["cpus"])) == 8 and cal["registration"] == origin["protocol_sha256"], "three physical calibrations")
    require(all(any(Path(path).name == name and seal == matched for path,matched in members.items()) for name,seal in cal["inherited"].items()), "original inherited PMU calibration series")
    require(cal["clock"] in members.values() and cal["thread"] in members.values(), "original time and thread-scope calibrations")
    decode = runpy.run_path(str(HERE / "exec_events.py"))["decode"]
    outcomes = {}
    rosters = {}
    for role, sdk in origin["compilers"].items():
        for hold in (1, 2):
            seed = f"opening-{role}-{hold}/"
            enrolled = doc(seed + "opening.json")
            require((enrolled["role"],enrolled["hold"],enrolled["seed"]) == (role,hold,members[seed+"seed.json"]), "independent enrollment")
            require(doc(seed + "sdk.json")["source"] == sdk["source"], "actual opening rustc")
            for state in ("A","B"):
                linked = doc(seed+"anchor-"+state+"/linked.json")
                require(linked["execute"]["return"] == 0 and linked["state"] == state and linked["arm"] == role, "linked consumer")
                require(linked["execute"]["stdout"] == origin["linked_stdout"][state], "seven authentic CLI outcomes")
                trace = doc(seed+state+"-kernel/process/observed-rustcs.json")
                ev = decode(doc(seed+state+"-kernel/process/kernel-events.json"))
                targets = trace["targets"]
                require(trace["cargo"] == ARGS and trace["other_rustc_queries"] == [] and ev["root"] == trace["root"] and ev["exits"][ev["root"]] == 0, "opening Cargo/exit/SDK probes")
                require(set(targets) == (NAMES if state == "B" else NAMES - {"uv_cli"}), "ordinary A/B kernel roster")
                for name, rec in targets.items():
                    require(ev["exits"][rec["pid"]] == 0 and any(x["pid"] == rec["pid"] and x.get("argv") == rec["argv"] and x["file"] == rec["inode"] for x in ev["images"]), "opening PID and executable")
                if state == "B": rosters[role,hold] = {name:rec["argv"] for name,rec in targets.items()}
    ratios = []
    for pair, order in enumerate(ORDER, 1):
        hold = 1 if pair<=4 else 2
        row = {}
        for pos, code in enumerate(order, 1):
            role = {"C":"candidate","P":"parent"}[code]
            where = f"pair-{pair:02d}/{pos}-{role}/"
            bound = guard["rows"][str(pair)][role]
            enrollment = f"opening-{role}-{hold}/seed.json"
            for mode in ("ordinary","whole-instructions","rustcs"):
                q = where + mode + "/"
                accepted = bound[mode]
                require(accepted == doc(q+"accepted.json") and (accepted["role"],accepted["hold"],accepted["number"],accepted["position"],accepted["mode"]) == (role,hold,pair,pos,mode), "arm/order")
                require(accepted["seed"] == members[enrollment] and accepted["outputs"] == members[q+"native-products.json"] and accepted["observed"] == members[q+"all-outputs.json"], "same native seed, products and equality receipt")
                require(accepted["source"] == origin["compilers"][role]["source"], "wrong compiler source")
                products = doc(q+"all-outputs.json")
                require(products["all_products"] == origin["native_opening"]["native_products"] == 1794 and products["source_state"] == "B" and not products["across_independent_cold_seeds"], "full same-seed products")
                require(set(products["archives"]) == {"uv_python", "uv_cli"}, "both native archive checks")
                sample = accepted["sample"]
                if mode == "ordinary":
                    rec = doc(q+"native/record.json")
                    require(rec["argv"] == ARGS and rec["exit"] == 0 and rec["end_monotonic_ns"] - rec["start_monotonic_ns"] == rec["wall_ns"] > 0, "ordinary Cargo blocking wait")
                    require(rec["stderr"] == digest(raw[q+"native/stderr"]) and rec["stdout"] == digest(raw[q+"native/stdout"]), "native stdout/stderr")
                    line, = re.findall(rb"Finished .+? in ([0-9.]+)s", raw[q+"native/stderr"])
                    require(sample == dict(rec,cargo_finished_seconds=float(line)), "ordinary clock or Cargo finish")
                    row[role] = {"wall_ns":rec["wall_ns"],"cargo_seconds":float(line),"wait4":rec["wait4"]}
                elif mode == "whole-instructions":
                    counter = doc(q+"native/instructions.json")
                    require(sample == counter and counter["code"] == counter["event_errno"] == 0 and counter["enabled"] == counter["running"] > 0 and counter["instructions"] > 0, "whole-tree hardware counter")
                    row[role]["whole"] = counter["instructions"]
                else:
                    scoped = doc(q+"native/per-rustc.json")
                    events = decode(doc(q+"native/kernel-events.json"))
                    require(scoped["root"] == events["root"] and events["exits"][events["root"]] == 0, "scoped Cargo exit")
                    require(scoped["targets"] == sample and set(sample) == NAMES and len({r["pid"] for r in sample.values()}) == 3, "three compiler processes")
                    for name, value in sample.items():
                        count, enabled, running, event = struct.unpack("<QQQQ",bytes.fromhex(value["raw_hex"]))
                        require((count,enabled,running,event) == (value["instructions"],value["time_enabled_ns"],value["time_running_ns"],value["event_id"]) and count > 0 and enabled == running > 0, "compiler hardware event")
                        require(value["argv"] == rosters[role,hold][name] and events["exits"][value["pid"]] == 0, "same first-edit compiler arguments")
                        require(any(x["pid"] == value["pid"] and x.get("argv") == value["argv"] and x["file"] == value["file"] for x in events["images"]), "actual compiler PID/argv/file")
                        row[role][name] = count
        outcomes[str(pair)] = row
        ratios.append(Fraction(row["candidate"]["wall_ns"],row["parent"]["wall_ns"]))
    hold_medians = [statistics.median(ratios[:4]),statistics.median(ratios[4:])]
    below = sum(r < Fraction(11,10) for r in ratios)
    p = sum(math.comb(8,i) for i in range(below,9))/256
    admitted = all(r < Fraction(105,100) for r in hold_medians) and below >= 7 and p <= 0.05
    require(([float(x) for x in ratios],[float(r) for r in hold_medians],below,p,admitted) ==
            (guard["candidate_over_parent"],guard["hold_medians"],guard["strictly_below_1p10"],guard["sign_one_sided"],guard["admitted"]), "registered decision")
    return {"admitted":admitted,"hold_medians":[float(x) for x in hold_medians],"below_1p10":below,"one_sided_sign":p,"pairs":outcomes}
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--original",type=Path,help="also verify every member of the original GitHub service ZIP")
    args=parser.parse_args()
    for row in (HERE/"SHA256SUMS").read_text().splitlines():
        seal, name = row.split("  ");require(hash_file(HERE/name)==seal,"packet "+name)
    origin=json.loads((HERE/"origin.json").read_text())
    complete_index=gzip.decompress((HERE/"member-sha256.json.gz").read_bytes())
    require(digest(complete_index) == origin["all_member_sha256"], "complete service member index")
    members=json.loads(complete_index)
    require(len(members) == origin["original_members"] == 1380 and hash_file(HERE/"exec_events.py") == origin["kernel_decoder_sha256"], "original member and decoder identity")
    with tarfile.open(OBS,"r:xz") as t:
        raw={row.name:t.extractfile(row).read() for row in t if row.isfile()}
    require(all(members[k]==digest(v) for k,v in raw.items()),"original sampled members")
    result=replay(raw,members,origin)
    published=json.loads((HERE/"panel.json").read_text())
    for r in published["rows"]:
        got=result["pairs"][str(r["pair"])]
        for role in ("parent","candidate"):
            g=got[role];p=r[role]
            require((g["wall_ns"],g["cargo_seconds"],g["wait4"],g["whole"])==(p["wall_ns"],p["cargo_seconds"],p["wait4"],p["whole_userspace_retired_instructions"]),"published native samples")
            require(all(g[n]==p["rustc_thread_groups"][n]["instructions"] for n in NAMES),"published scoped samples")
    if args.original:
        require(hash_file(args.original)==origin["original"]["sha256"] and args.original.stat().st_size==origin["original"]["bytes"],"authorized service archive")
        with zipfile.ZipFile(args.original) as z:
            names=[i.filename for i in z.infolist() if not i.is_dir()]
            require(len(names)==len(set(names))==len(members) and set(names)==set(members),"complete native member roster")
            for n in names:
                with z.open(n) as f:require(hashlib.file_digest(f,"sha256").hexdigest()==members[n],"original "+n)
    print(json.dumps(result,indent=2,sort_keys=True))
if __name__ == "__main__":main()
