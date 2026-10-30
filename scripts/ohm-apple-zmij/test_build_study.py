"""Native P/C test-build screen and independent confirmation, gated by a signed -20 pilot."""

import argparse
import collections
import gzip
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
from macho_paths import canonical, compare as compare_macho
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


def clean_image(root, prefix, reference):
    record = load(prefix / "verified.json")
    with gzip.open(prefix / "stdout.gz", "rb") as f:
        artifacts = [json.loads(line) for line in f]
    executables = [r["executable"] for r in artifacts if r.get("executable") and
                   r["target"]["name"] == "ruff_python_ast" and r["profile"]["test"]]
    need(len(executables) == 1, "ambiguous actual test executable")
    path = executables[0]
    links = [link["argv"] for link in record["native"]["linkers"]
             if [v for k,v in zip(link["argv"],link["argv"][1:]) if k == "-o"] == [path]]
    need(len(links) == 1, "ambiguous actual test linker")
    original = reference["raw"]
    data = gzip.decompress((root / "receipts/test-executables" / (original + ".macho.gz")).read_bytes())
    need(hashlib.sha256(data).hexdigest()==original, "clean native file changed")
    return data, path, links[0]


def compare_clean(root, out, refs, state):
    arms = {role: clean_image(root, out / role / ("empty-" + state) / "clean", refs[role][state]) for role in "PC"}
    same_fields = ("text","tests","verdicts")
    need(all(refs["P"][state][key] == refs["C"][state][key] for key in same_fields), "different executable code or test behavior")
    return compare_macho(arms,incremental=True)


def verify_installation(root, role, out, timed, anchors):
    """Build empty A and B after the last clock, before changing the compiler driver."""
    selected = load(out / "selected-driver.json")
    trace = ExecTrace()
    try:
        trace.ready()
        for state, phases in (("old", ("cold",)), ("new", ENDPOINTS)):
            where = out / "reference" / ("empty-" + state)
            row = installed("test", root, role, where, [("clean", state)], trace)["clean"]
            need(load(where / "selected-driver.json") == selected, "different driver installation for the clean reference")
            clean = row["product"]
            for phase in phases:
                need(timed[phase]["state"] == state and timed[phase]["product"] == clean,
                     "timed executable differs from same-installation clean build")
            data, proof = canonical(*clean_image(root, where/"clean", clean))
            key = hashlib.sha256(data).hexdigest()
            need(key == anchors[state]["canonical_sha256"] and proof["paths"] == anchors[state][role]["paths"] and
                 proof["base"] == anchors[state][role]["base"], "different clean executable between installations")
            save(where/"checked.json", {"compared":list(phases), "canonical_sha256":key, "driver":selected, "proof":proof})
    finally:
        trace.close()


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
    cross = {state:compare_clean(root,out,clean,state) for state in ("old","new")}
    for phase in ENDPOINTS:
        parent = signature(baselines["P"][phase])
        child = signature(baselines["C"][phase])
        need(parent["full"] == ["ruff_python_ast", "zmij"] and parent["link_only"] == [] and len(parent["links"]) == 1,
             "unconfirmed baseline on direct parent")
        need(child["full"].count("zmij") == 0 and not (collections.Counter(child["full"])-collections.Counter(parent["full"]))
             and len(child["links"]) <= 1 and not child["link_only"], "unexpected candidate compiler or linker")
        if phase == "edit":
            need(child["full"] == ["ruff_python_ast"] and len(child["links"]) == 1, "real edit failed to rebuild and relink")
    save(out/"verified.json",{"clean":clean,"cross_compiler":cross,
         "physical":{r:{p:signature(row) for p,row in rows.items()} for r,rows in baselines.items()}})
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
           "correctness": "every complete timed Mach-O must equal a separately empty native build of the same source and exact driver installation including ctime, executed after the last clock; native reference files must agree across installations and compilers after replacing only verified linker N_OSO Cargo namespaces and recomputing independently validated ad-hoc page hashes; identical 53/54 complete suite records; actual edit must link",
           "harness": fingerprint_sources()}
    if mode == "confirm":
        prior = load(root / "receipts/test-screen/result.json")
        need(prior["accept"] and prior["harness"]==reg["harness"], "no qualifying separate two-pair screen")
    save(out / "registered.json", reg)
    before, _ = verify_trace(root, out / "native-before")
    anchors = load(out / "native-before/verified.json")["cross_compiler"]
    pairs = []
    for n, order in enumerate(ORDERS[mode],1):
        both = {}
        for role in order:
            check_host(root, 7)
            installation = out/f"pair-{n:02}"/role
            rows = installed("test",root,role,installation,STEPS,None,timed=True)
            verify_installation(root, role, installation, rows, anchors)
            for key, row in rows.items():
                need(row["dirty"] == before[role][key]["dirty"] and row["roster"] == before[role][key]["roster"]
                     and row["roster"] == before["P"][key]["roster"] and row["native"] is None,
                     "timed Cargo changed its workload")
            both[role] = rows
        pairs.append(both)
    after, _ = verify_trace(root, out/"native-after", negative=False)
    terminal = load(out/"native-after/verified.json")["cross_compiler"]
    for state in ("old","new"):
        need(anchors[state]["canonical_sha256"] == terminal[state]["canonical_sha256"] and
             all(anchors[state][role]["paths"] == terminal[state][role]["paths"] for role in "PC"),
             "independent clean test executable drift")
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
