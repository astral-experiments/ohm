"""Qualify the antecedent and summarize one complete, independently registered twelve-boot cohort."""
import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import admission

SCREEN = json.loads((HERE / "qualified-screen.json").read_bytes())
POSITIONS = tuple(f"{n:02}" for n in range(1, 13))
ARMS = admission.ARMS
PHASES = admission.VISITS
PRIMARY = {"return-A": ("return-A",), "return-B": ("return-B",), "return_sum": ("return-A", "return-B")}
GROUPS = {p: (p,) for p in PHASES} | PRIMARY | {
    "first_switch_and_return_A": ("first-B", "return-A"),
    "cold_through_return_B": PHASES[:4], "all_five_successful": PHASES[:5], "all_seven": PHASES,
}
need = admission.need


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def order(pos):
    need(pos in POSITIONS, "unknown enrolled position")
    return ARMS if int(pos) % 2 else tuple(reversed(ARMS))


def eligible_instructions(clock, expected):
    need(all(type(clock[k]) is int for k in ("instructions","code","event_errno","enabled","running","start","stop","user_us","system_us")) and
         clock["instructions"] > 0 and clock["user_us"]>=0 and clock["system_us"]>=0 and clock["code"] == expected and
         clock["event_errno"] == 0 and 0 < clock["running"] <= clock["enabled"] and
         1000 * clock["running"] >= 995 * clock["enabled"] and clock["start"] < clock["stop"],
         "failed raw whole-Cargo hardware counter")


def screen_original(raw, pos):
    spec = SCREEN["positions"][pos]
    need(raw.seek(0, 2) == spec["size"], "wrong pilot length")
    raw.seek(0)
    need(hashlib.file_digest(raw, "sha256").hexdigest() == spec["sha256"], "wrong original pilot SHA")
    raw.seek(0)
    with zipfile.ZipFile(raw) as z:
        need(sha(z.read("complete.json")) == spec["complete_sha256"] and
             sha(z.read("independent-pilot.json")) == spec["worker_sha256"], "wrong hosted pilot readback")
        en = json.loads(z.read("enrollment.json"))
        proof = json.loads(z.read("independent-pilot.json"))
        end = json.loads(z.read("complete.json"))
        need(en["run"] == proof["run"] == SCREEN["run"] and en["head"] == proof["head"] == end["head"] == SCREEN["head"] and
             en["boot"] == proof["boot"] == end["boot"] == spec["boot"] and
             en["position"] == proof["position"] == end["position"] == pos and end["qualified"] and
             en["order"] == proof["order"] == end["order"] == spec["order"], "wrong completed pilot")
        for arm in ARMS:
            for phase in ("return-A", "return-B"):
                clock = json.loads(z.read(f"history/{arm}/{phase}/clock.json"))
                eligible_instructions(clock, 0)
                need(proof["observations"][arm][phase]["raw_clock"] == clock and
                     spec["return_instructions"][arm][phase] == clock["instructions"], "pilot return count differs")
        for phases in PRIMARY.values():
            counts = [sum(spec["return_instructions"][arm][p] for p in phases) for arm in ARMS]
            need(counts[0] > 2 * counts[1], "pilot did not qualify a new cohort")


def screen(directory=None):
    def api(path):
        return json.loads(subprocess.check_output(["gh", "api", f"repos/{admission.REPO}/actions/{path}"]))
    run = SCREEN["run"]
    if directory is None:
        meta = api(f"runs/{run}")
        need((meta["id"], meta["head_branch"], meta["head_sha"], meta["run_attempt"], meta["conclusion"]) ==
             (run, SCREEN["branch"], SCREEN["head"], 1, "success"), "wrong official prior pilot")
    for pos, spec in SCREEN["positions"].items():
        if directory is not None:
            with (directory / f'{run}-{spec["artifact"]}.zip').open("rb") as raw:
                screen_original(raw, pos)
            continue
        job, artifact = api(f'jobs/{spec["job"]}'), api(f'artifacts/{spec["artifact"]}')
        need((job["run_id"], job["head_sha"], job["name"], job["conclusion"]) ==
             (run, SCREEN["head"], "Integration F whole-Cargo kernel pilot " + pos, "success") and
             (artifact["workflow_run"]["id"], artifact["workflow_run"]["head_sha"], artifact["name"], artifact["digest"],
              artifact["size_in_bytes"], artifact["expired"]) ==
             (run, SCREEN["head"], "ruff-integration-kernel-pilot-" + pos, "sha256:" + spec["sha256"], spec["size"], False),
             "wrong official boot or archived original")
        with tempfile.TemporaryFile() as raw:
            subprocess.run(["gh", "api", f'repos/{admission.REPO}/actions/artifacts/{spec["artifact"]}/zip'],
                           stdout=raw, timeout=600, check=True)
            screen_original(raw, pos)
    return sha((HERE / "qualified-screen.json").read_bytes())


def distribution(pairs):
    ratios = sorted(Fraction(a,b) for a,b in pairs)
    need(len(ratios)==12, "full twelve-position denominator required")
    exact = lambda r: [r.numerator, r.denominator]
    return {"median": exact((ratios[5]+ratios[6])/2), "rank2": exact(ratios[1]), "rank11": exact(ratios[10]),
            "strict_wins": sum(x > 1 for x in ratios), "strict_above_two": sum(x > 2 for x in ratios)}


def summarize(workers, run, head):
    need(run not in (admission.RUN, SCREEN["run"], 41229888294, 41219513694, 41219530573) and
         type(run) is int and run > 0 and re.fullmatch(r"[0-9a-f]{40}", head) and
         set(workers) == set(POSITIONS), "wrong experiment or incomplete 12-position denominator")
    prior = json.loads((HERE / "excluded-boots.json").read_bytes())
    need(len(prior) == len(set(prior)) == 41 and all(x["boot"] in prior for x in SCREEN["positions"].values()),
         "missing exclusions for independent boot selection")
    used = set(prior)
    screen_digest = sha((HERE / "qualified-screen.json").read_bytes())
    plan = sha((HERE / "PLAN.md").read_bytes())
    counts = {k: [] for k in GROUPS}
    detail = {}
    hardware = None
    for pos in POSITIONS:
        w = workers[pos]
        need(w["position"] == pos and w["run"] == run and w["head"] == head and tuple(w["order"]) == order(pos) and
             w["screen"] == screen_digest and w["registration"] == plan and w["structural"] == admission.SHA and
             w["boot"] not in used and w["boot"] == w["calibration"]["boot"] and
             re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}",w["boot"]), "foreign/duplicate boot, source, schedule or original")
        used.add(w["boot"])
        machine = {k:w["calibration"][k] for k in ("cpu","pmu","abi","observer","calibrator","cells")}
        need(machine["cells"]==28 and (hardware is None or machine==hardware),"unmatched hardware or calibration")
        hardware = machine
        observations = w["observations"]
        need(set(observations)==set(ARMS) and all(set(x)==set(PHASES) for x in observations.values()),"incomplete or extra phases")
        phase_table = {}
        for phase in PHASES:
            item = {}
            for arm in ARMS:
                v = observations[arm][phase]
                raw = v["raw_clock"]
                eligible_instructions(raw, 101 if phase=="invalid" else 0)
                need(v["instructions"]==raw["instructions"] and v["exit"]==raw["code"] and type(v["allocated"]) is int and v["allocated"]>0 and
                     (phase=="invalid" or v["passed"]==96 and len(v["elf"])==3), "missing real verdict, ELF or changed counter")
                item[arm] = {k:raw[k] for k in ("instructions","code","user_us","system_us","enabled","running","start","stop")}
                item[arm].update(allocated=v["allocated"],typed=v["typed"],dirty=v["dirty"])
            phase_table[phase]=item
        pairs = {}
        for key, phases in GROUPS.items():
            pair = [sum(phase_table[v][arm]["instructions"] for v in phases) for arm in ARMS]
            counts[key].append(pair); pairs[key]=pair
        detail[pos]={"boot":w["boot"],"order":w["order"],"raw_instruction_pairs":pairs,
                     "all_phases":phase_table,"native_elf_sha256s":w["unique_clean_elfs"],"filesystem":w["host_filesystem"]}
    distributions={k:distribution(rows) for k,rows in counts.items()}
    passed=all(Fraction(*distributions[k]["rank2"])>2 for k in PRIMARY)
    order_effects={}
    for first in ARMS:
        positions=[p for p in POSITIONS if order(p)[0]==first]
        for key in PRIMARY:
            ratios=sorted(Fraction(*detail[p]["raw_instruction_pairs"][key]) for p in positions)
            midpoint=(ratios[2]+ratios[3])/2
            order_effects.setdefault(first,{})[key] = {"positions":positions,"median":[midpoint.numerator,midpoint.denominator]}
    # Exact continuous-median confidence for the second/eleventh sample order statistic.
    miss=Fraction(2*sum(math.comb(12,k) for k in (0,1)), 2**12)
    return {"run":run,"head":head,"positions":detail,"hardware":hardware,"included_boots":12,"pilot_boots_included":0,
            "endpoint":"Foff/Fon whole-Cargo retired user instructions","distributions":distributions,"co_primary":list(PRIMARY),
            "descriptive_order_strata":order_effects,
            "all_three_lower_bounds_strictly_above_two":passed,"individual_coverage":str(1-miss),
            "family_coverage_at_least":str(1-3*miss),"ranks":[2,11]}


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest="mode",required=True)
    a=subs.add_parser("screen");a.add_argument("--original-directory",type=Path)
    a=subs.add_parser("score");a.add_argument("--run",type=int,required=True);a.add_argument("--head",required=True);a.add_argument("directory",type=Path)
    args=parser.parse_args()
    if args.mode=="screen":print(screen(args.original_directory))
    else:
        import read_original
        files=sorted(args.directory.glob("worker-*.json"))
        need({p.name for p in files}=={f"worker-{x}.json" for x in POSITIONS},"incomplete or extra original workers")
        raw={p.stem.split("-")[-1]:json.loads(p.read_bytes()) for p in files}
        receipts={p:json.loads((args.directory/f"receipt-{p}.json").read_bytes()) for p in POSITIONS}
        need(all(receipts[p]["empty_native_sha256"]==sha((args.directory/f"empty-native-{p}.json").read_bytes()) for p in POSITIONS),
             "missing or substituted independent native-link witness")
        final=json.loads((args.directory/"terminal-catalog.json").read_bytes())
        print(json.dumps(read_original.check_result(raw,receipts,final,args.run,args.head),sort_keys=True,separators=(",",":")))
