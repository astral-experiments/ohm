"""Bind a host to its registered block and source without changing the measured command."""
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import support

def check(env,boot,permit):
    phase=env["COHORT"];block=int(env["BLOCK"]);position=int(env["POSITION"])
    assert phase==permit["phase"] and phase in {"primary","independent"}
    assert permit["blocks"]==list(range(1,7)) and block in permit["blocks"]
    assert position in (1,2) and permit["position_orders"]==["PC","CP"]
    assert env["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and env["GITHUB_REF_NAME"]==support.REG["ref"]
    assert env["GITHUB_RUN_ATTEMPT"]=="1" and env["GITHUB_EVENT_NAME"]=="workflow_dispatch"
    assert boot not in set(permit["other_used_boots"])|set(support.REG["screen"]["excluded_boot_ids"])
    assert support.file_sha(HERE/"PLAN.md")==permit["confirmation_plan"]=="a8b56745c858d9c6ca9df86c8ac6b7ddfe3ea5f1afaed786fd7516c88d9f1d2b"
    data=support.opened(HERE/"screen.json"); official=support.opened(HERE/"screen-originals.json")
    assert permit["screen_report"]==support.file_sha(HERE/"screen.json") and permit["screen_originals"]==support.file_sha(HERE/"screen-originals.json")
    assert official["run"]==41179486810 and official["head"]=="1e287c8b68836f27c98860e8a9e9d205851936e4" and official["conclusion"]=="success"
    assert data["primary"]=="repeat" and data["eligible_to_propose_larger_confirmation"] and len(data["positions"])==2
    for row in data["positions"]:
        c=row["counts"]
        assert row["boot"] in permit["other_used_boots"]
        assert Fraction(c["P"]["repeat"],c["C"]["repeat"])==Fraction(row["ratios"]["repeat"]["exact"])>=Fraction(9,5)
    if phase=="independent":
        primary=support.opened(HERE/"primary.json")
        assert support.file_sha(HERE/"primary.json")==permit["accepted_primary"]
        assert primary["phase"]=="primary" and primary["qualifies"] and len(primary["positions"])==12
        assert all(h["boot"] in permit["other_used_boots"] for h in primary["positions"])
    return {"phase":phase,"block":block,"position":position,"order":permit["position_orders"][position-1],
            "run":int(env["GITHUB_RUN_ID"]),"head":env["GITHUB_SHA"],"boot":boot,
            "input_plan":permit["confirmation_plan"],"clearance":support.AUTHORIZED_CLEARANCE_SHA256}
if __name__=="__main__":
    commit=subprocess.check_output(["git","-C",HERE,"rev-parse","HEAD"],text=True).strip()
    assert commit==os.environ["GITHUB_SHA"]
    out=Path(sys.argv[1]);assert not out.exists()
    cell=check(os.environ,Path("/proc/sys/kernel/random/boot_id").read_text().strip(),support.gate(HERE.parent/"clearance.json"))
    with out.open("x") as f:f.write(json.dumps(cell,indent=2,sort_keys=True)+"\n")
