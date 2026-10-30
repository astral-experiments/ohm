"""Native P/C test-build screen and independent confirmation, gated by a signed -20 pilot."""

import argparse
import collections
import hashlib
import io
import json
import os
import zipfile

from pathlib import Path
from cohort import ENDPOINTS, fingerprint_sources, summarize
from dyld import check as check_dyld
from execs import ExecTrace
from measure import select
from native_inputs import run_archive_check
from study import ARCHIVE_SHA, CHILD, ORDERS, PARENT, check_host, load, need, run, save, sha
from verbs import A, ARGS, B, NEW_TEST, installed

SIGNED_RUN = 41051991519
SIGNED_HEAD = "8fb888395d94179bf969f60e5667df473b16b17c"
SIGNED_ARTIFACT = 12974444729
SIGNED_SHA = "d91085ee544c70231dc3e18a2d9c3db8f2a02b6f5a53270a8bb853f19b108447"
STEPS = [("cold", "old"), ("edit", "new"), ("repeat-1", "new"), ("repeat-2", "new")]
NEGATIVE = [("invalid", "invalid"), ("repair", "new")]


def admitted(root):
    base = os.environ["GITHUB_REPOSITORY"]
    need(base == "astral-experiments/ohm", "foreign packaging repository")
    api = ["gh", "api", f"repos/{base}/actions"]
    info = json.loads(run([*api[:-1], api[-1] + f"/runs/{SIGNED_RUN}"]))
    need(info["conclusion"] == "success" and info["event"] == "workflow_dispatch" and
         info["head_sha"] == SIGNED_HEAD and info["path"] == ".github/workflows/ci.yml", "wrong signed baseline run")
    body = run([*api[:-1], api[-1] + f"/artifacts/{SIGNED_ARTIFACT}/zip"], timeout=240)
    need(hashlib.sha256(body).hexdigest() == SIGNED_SHA, "wrong raw pilot bytes")
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        test = json.loads(z.read("signed-verbs/test/result.json"))
        check = json.loads(z.read("signed-verbs/check/result.json"))
        release = json.loads(z.read("release.json"))
    need(test["source"] == check["source"] == [A,B] and release["archive"] == ARCHIVE_SHA, "unenrolled pilot")
    for k in ("repeat-1", "repeat-2"):
        t = test["physical"][k]
        need(t["full"] == ["ruff_python_ast", "zmij"] and t["link_only"] == [] and len(t["linkers"]) == 1
             and t["linkers"][0]["stock"] and not any(check["physical"][k][n] for n in ("full", "link_only", "linkers")),
             "the signed opportunity changed")
    need(all(all(v.values()) for v in test["clean_comparisons"].values()), "wrong signed native bytes or inventory")
    save(root / "receipts/accepted-verbs-pilot.json", {"run": SIGNED_RUN, "head": SIGNED_HEAD,
         "archive": SIGNED_SHA, "eligible": ["test"], "check_repeat_compilers": 0})


def signature(row):
    n = row["native"]
    return {"full": n["full"], "link_only": n["link_only"], "links": [[x["name"], x["sha"], x["stock"]] for x in n["linkers"]]}


def assert_product(row, clean):
    need(row["product"] == clean[row["state"]], "actual test executable, code, inventory or suite differs from independent clean")


def verify_trace(root, out, *, negative=True):
    trace = ExecTrace()
    baselines, clean = {}, {}
    try:
        trace.ready()
        for role in ("P","C"):
            check_dyld(root, role, select(root, role), out / role / "dyld")
            clean[role] = {}
            for state in ("old","new"):
                row = installed("test",root,role,out/role/("empty-"+state),[("clean",state)],trace)["clean"]
                clean[role][state] = row["product"]
            old, new = [clean[role][state] for state in ("old","new")]
            need(old["raw"] != new["raw"] and set(new["tests"])-set(old["tests"]) == {NEW_TEST} and
                 set(old["tests"]) < set(new["tests"]) and (len(old["tests"]),len(new["tests"])) == (53,54), "wrong edited executable")
            rows = installed("test", root, role, out/role/"actual", STEPS + (NEGATIVE if negative else []), trace)
            for phase, row in rows.items():
                if phase != "invalid":
                    assert_product(row, clean[role])
                if phase in ENDPOINTS:
                    need(row["fresh_zmij"] == (role=="C") and row["marker"]["hard"] == (role=="P")
                         and row["marker"]["recheck"] == (role=="C"), "wrong source cause")
            baselines[role] = rows
            if negative:
                run_archive_check(root, role, trace, label=out.parent.name + "-test-" + role)
    finally:
        trace.close()
    need(clean["P"] == clean["C"], "compiler arms emitted different test programs")
    for phase in ENDPOINTS:
        parent = signature(baselines["P"][phase])
        child = signature(baselines["C"][phase])
        need(parent["full"] == ["ruff_python_ast", "zmij"] and parent["link_only"] == [] and len(parent["links"]) == 1,
             "unconfirmed baseline on direct parent")
        need(child["full"].count("zmij") == 0 and not (collections.Counter(child["full"])-collections.Counter(parent["full"]))
             and len(child["links"]) <= 1 and not child["link_only"], "unexpected candidate compiler or linker")
        if phase == "edit":
            need(child["full"] == ["ruff_python_ast"] and len(child["links"]) == 1, "real edit failed to rebuild and relink")
    save(out/"verified.json",{"clean":clean,"physical":{r:{p:signature(row) for p,row in rows.items()} for r,rows in baselines.items()}})
    return baselines, clean


def execute(root, mode):
    out = root / "receipts" / ("test-" + mode)
    out.mkdir()
    pilot = load(root / "receipts/accepted-verbs-pilot.json")
    need(pilot["eligible"] == ["test"] and pilot["archive"] == SIGNED_SHA and (root/"receipts/observer.json").is_file(),
         "signed pilot and physical observer required")
    reg = {"command":ARGS["test"], "primary":"first unchanged test build after historical edit B",
           "secondary":["edited test build", "second unchanged test build"],
           "old": A, "new": B, "compilers": [PARENT, CHILD], "order": ORDERS[mode], "pilot_sha": SIGNED_SHA,
           "paired": "independent private Cargo/target/build for each installation",
           "admission": "both pilot ratios above two; separate balanced n=12 lower median bound above two and p<=.05",
           "correctness": "identical complete Mach-O, 53/54 inventories and full suite and layout verdicts; actual edit must link",
           "harness": fingerprint_sources()}
    if mode == "confirm":
        prior = load(root / "receipts/test-screen/result.json")
        need(prior["accept"] and prior["harness"]==reg["harness"], "no qualifying separate two-pair screen")
    save(out / "registered.json", reg)
    before, refs = verify_trace(root, out / "native-before")
    pairs = []
    for n, order in enumerate(ORDERS[mode],1):
        both = {}
        for role in order:
            check_host(root, 7)
            rows = installed("test",root,role,out/f"pair-{n:02}"/role,STEPS,None,timed=True)
            for key, row in rows.items():
                assert_product(row, refs[role])
                need(row["dirty"] == before[role][key]["dirty"] and row["roster"] == before[role][key]["roster"]
                     and row["roster"] == before["P"][key]["roster"] and row["native"] is None,
                     "timed Cargo changed its workload")
            both[role] = rows
        pairs.append(both)
    after, after_refs = verify_trace(root, out/"native-after", negative=False)
    need(refs == after_refs, "independent test binary reference drift")
    for role in "PC":
        for key in ENDPOINTS:
            need(signature(before[role][key]) == signature(after[role][key]), "physical collector changed at terminal flank")
    cal = load(root/"receipts/calibration/result.json")
    wall = summarize(pairs, ORDERS[mode])
    result = {"mode":mode,"registration":sha(out/"registered.json"),"harness":reg["harness"],"wall":wall,
              "retired_instruction_scope":cal["retired_instruction_scope"]}
    if cal["tree_CPU_calibrated"]:
        for pair in pairs:
            for rows in pair.values():
                for phase in ENDPOINTS:
                    m = rows[phase]["cargo"]
                    m["cpu"] = m["user"] + m["system"]
        result["cpu_seconds"] = summarize(pairs, ORDERS[mode], "cpu")
    if cal["retired_instruction_scope"]=="whole-tree-calibrated":
        result["instructions"]=summarize(pairs, ORDERS[mode], "instructions")
    primary = wall["repeat-1"]
    result["accept"] = (min(primary["ratios_P_over_C"]) > 2 if mode=="screen" else
                        primary["median_CI_96.14pct"][0] > 2 and primary["one_sided_balanced_sharp_2x_p"] <= 0.05)
    save(out/"result.json",result)
    print(mode,"first unchanged median ratio",primary["median_ratio"],"accepted",result["accept"],flush=True)


if __name__=="__main__":
    import sys
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("admit","screen","confirm"))
    parser.add_argument("root",type=Path)
    args=parser.parse_args()
    root=args.root.resolve(strict=True)
    if args.mode=="admit":
        admitted(root)
    else:
        execute(root,args.mode)
