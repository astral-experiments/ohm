"""Verify the saved #21041 hardware measurements without a compiler, network, or installed packages."""
import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from math import comb
from pathlib import Path, PurePosixPath
from statistics import median
import struct
import subprocess
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
RUN = 41399090905
JOB = 125126764197
ARTIFACT = 13120249254
HEAD = "667cb67c64eb03973f95df51d68883c0d056e2ee"
ZIP_SHA = "a920d8c6d95a903e156f098055d2342466505927f9c42adc77878a2227dfbb76"
SOURCE = ["26210096e48c5c62ef4a5e8fd1aa612631b2f7d7", "f22825348d834ad9a8ef3934647181fb69f778ae"]
COMMAND = ["/tmp/uv-workflow-search/sdk/bin/cargo", "check", "-p", "uv-client", "--locked", "--offline", "-j8"]
CRATES = {"uv_cache", "uv_client", "uv_configuration", "uv_distribution_types", "uv_install_wheel", "uv_metadata", "uv_pypi_types", "uv_torch"}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sources(original, cli):
    origin = json.loads((HERE / "origin.json").read_bytes())
    need((origin["run_id"], origin["job_id"], origin["original"]["id"], origin["head"]) == (RUN, JOB, ARTIFACT, HEAD), "wrong Actions source")
    need(origin["original"]["digest"] == "sha256:" + ZIP_SHA and origin["original"]["size_in_bytes"] == 37771404, "wrong original artifact")
    p = HERE / "evidence.tar.xz"
    need(file_sha(p) == "3b12dccb19ea46cd737c139c3b936f891b5203bc7306acd0c6b7f09b23ec3898" == origin["checksums"]["selected_archive"] and p.stat().st_size == origin["selected_archive_bytes"], "changed portable archive")
    need(file_sha(HERE / "pair.json") == origin["checksums"]["native_sdk_lock"] == "08b0f933ed9dda4bc7079d63e81321e7c8ff279e321b47888da4408781ebdacf", "wrong source and SDK pair")
    need(file_sha(HERE / "study.json") == "64444f16eaa51531431911a76f8c459fd439b1600ae8bc8d7173a7ee9dbabcfc" == origin["checksums"]["packaged_study"], "changed protocol")
    if cli:
        def api(path):
            return json.loads(subprocess.check_output([cli, "api", "repos/astral-experiments/ohm/" + path]))
        r, j, a = api(f"actions/runs/{RUN}"), api(f"actions/jobs/{JOB}"), api(f"actions/artifacts/{ARTIFACT}")
        need(r["id"] == j["run_id"] == a["workflow_run"]["id"] == RUN and r["run_attempt"] == j["run_attempt"] == 1, "wrong service run")
        need(r["repository"]["id"] == r["head_repository"]["id"] == a["workflow_run"]["repository_id"] == 1319437234 and r["repository"]["private"], "wrong repository")
        need(r["head_sha"] == j["head_sha"] == a["workflow_run"]["head_sha"] == HEAD and r["head_branch"] == a["workflow_run"]["head_branch"] == origin["branch"], "wrong measured head")
        need(j["id"] == JOB and r["event"] == "workflow_dispatch" and r["conclusion"] == j["conclusion"] == "success", "unqualified completion")
        need(all(a[key] == value for key, value in origin["original"].items()), "wrong service artifact")
    members = {}
    with tarfile.open(p, "r:xz") as files:
        for f in files:
            name = PurePosixPath(f.name)
            need(f.isfile() and not name.is_absolute() and ".." not in name.parts and f.name not in members and f.size <= 2 << 20, "unbounded archived member")
            need(len(members) < 600, "too many members")
            data = files.extractfile(f).read(f.size + 1)
            need(len(data) == f.size, "truncated member")
            members[f.name] = data
    manifest = "".join(f"{k}\t{len(v)}\t{sha(v)}\n" for k, v in sorted(members.items())).encode()
    need(sha(manifest) == "1ce90229dbc726b7b0ee3538c24e4ec4ce46738c72770e3718de56f6be93e0c3" == origin["checksums"]["selected_exact_members"] and len(members) == origin["selected_file_count"] == 561, "wrong selected original bytes")
    need(sum(map(len, members.values())) == origin["selected_raw_bytes"] == 26904364, "wrong selected size")
    if original:
        need(original.stat().st_size == 37771404 and file_sha(original) == ZIP_SHA, "wrong full ZIP")
        with zipfile.ZipFile(original) as z:
            need(len(z.infolist()) == len(set(z.namelist())) == origin["n_original_members"] == 1478, "wrong original members")
            need(all(z.read(k) == v for k, v in members.items()), "subset is not byte-identical to the original")
    return origin, json.loads((HERE / "study.json").read_bytes()), members


def event_tree(raw):
    root = raw["root"]
    need(type(root) is int and root > 0 and raw["options"] == 0x10001e, "unexpected trace")
    born, exits, transferred, unresumed, images = {}, {}, {}, set(), []
    for pid, status, *args in raw["events"]:
        if status == "resume-ESRCH":
            need(not args, "invalid terminal stop")
            unresumed.add(pid)
            continue
        need(type(status) is int and 0 <= status < 1 << 24, "bad Linux wait status")
        if status & 255 != 127:
            need(not args and pid not in exits, "multiple terminal statuses")
            exits[pid] = -(status & 127) if status & 127 else status >> 8
            continue
        need((status >> 8) & 255 == 5, "unexpected stop signal")
        event, child = status >> 16, args[0]
        if event in (1, 2, 3):
            need(len(args) == 1 and child != root and child != pid and child not in born, "bad fork/clone")
            born[child] = pid
        else:
            need(event == 4 and len(args) == 2 and type(args[1]["exe"]) is str, "bad exec")
            images.append((pid, args[1]))
            if child != pid:
                need(child not in transferred, "duplicate exec handoff")
                transferred[child] = pid
    tree = {root, *born}
    need(tree == set(exits) | set(transferred) and unresumed <= tree and set(transferred.values()) <= tree, "incomplete trace")
    for node in born:
        seen = set()
        while node != root:
            need(node in born and node not in seen, "detached task")
            seen.add(node)
            node = born[node]
    need(images and images[0][0] == root and all(pid in tree for pid, _ in images), "wrong root exec")
    return images, exits


def counter(row):
    raw = bytes.fromhex(row["raw_hex"])
    need(len(raw) == 32, "short raw perf read")
    value, enabled, running, event = struct.unpack("<4Q", raw)
    need((value, enabled, running, event) == tuple(row[k] for k in ("instructions", "time_enabled_ns", "time_running_ns", "event_id")), "changed counter fields")
    need(value > 0 and event > 0 and enabled == running > 0, "multiplexed or invalid perf counter")
    return value


def counted(req, events, ids, perf, selectors):
    need(set(selectors) == CRATES and req["selectors"] == selectors and req["command"] == COMMAND, "wrong selected compiler names or argv")
    need(req["cwd"] == "/tmp/uv-workflow-search/uv" and req["compiler_path"] == "/tmp/uv-workflow-search/sdk/bin/rustc", "wrong working directory/compiler")
    images, exits = event_tree(events)
    root, im = images[0]
    need(root == perf["root"] and exits[root] == 0 and im["argv"] == COMMAND and im["exe"] == COMMAND[0] and im["file"] == ids["cargo_file"], "not the enrolled root cargo check")
    need(perf["scope"] == "retired userspace instructions in the selected process and its threads" and set(perf["targets"]) == CRATES, "wrong process scope")
    seen, event_ids, result = set(), set(), {}
    for pid, im in images:
        args = im.get("argv") or []
        if im["file"] != ids["rustc_file"] and PurePosixPath(im["exe"]).name != "rustc" and not (args and PurePosixPath(args[0]).name == "rustc"):
            continue
        need(im["file"] == ids["rustc_file"] and im["exe"] == req["compiler_path"] and args[0] == im["exe"] and exits[pid] == 0, "foreign or failed compiler")
        if args == [im["exe"], "-vV"]:
            continue
        name = args[args.index("--crate-name") + 1]
        need(name in selectors and name not in result and selectors[name] == args, "unexpected/missing compiler command")
        row = perf["targets"][name]
        need(pid == row["pid"] and im["exe"] == row["exe"] and im["file"] == row["file"] and args == row["argv"], "wrong counter to PID/argv join")
        need(pid not in seen and row["event_id"] not in event_ids, "duplicate PID/counter")
        seen.add(pid)
        event_ids.add(row["event_id"])
        result[name] = counter(row)
    need(set(result) == CRATES, "missing compiler")
    return result


def paired(values, threshold=Fraction(1)):
    ratios = [Fraction(a, b) for a, b in values]
    up = sum(x > threshold for x in ratios)
    n = sum(x != threshold for x in ratios)
    need(len(ratios) == 8, "missing pair")
    mid = median(ratios)
    return {"raw_control_candidate": values, "median_factor": float(mid), "fewer_percent": float(100 * (1 - 1 / mid)),
            "hold_medians": [float(median(x)) for x in (ratios[:4], ratios[4:])], "range": [float(min(ratios)), float(max(ratios))],
            "above": up, "ties": 8 - n, "threshold": str(threshold), "one_sided_sign_p": sum(comb(n, i) for i in range(up, n + 1)) / 2**n}


def verify(origin, study, blobs, hostile):
    def j(n):
        return json.loads(blobs[n])
    roles = study["roles"]
    need([origin["source_commits"][r] for r in roles] == SOURCE and set(study["edited_workspace_roster"]) == CRATES, "wrong compilers/workload")
    need(study["A"] == "a2a02424dcba3c3f37cf6b8de5484497dd48651e" and study["B"] == "9049e07fa6b8e4863807b3a6e6e1293cbf68d0c3", "wrong uv edit")
    ready = j("calibration.json")["ready"]
    need(j("calibration.json")["unmultiplexed_calibration_clocks"] == 28 and ready["boot"] == "8461ebca-9583-4d70-8eac-198744186904", "wrong calibration")
    native_cal = j("per-rustc-calibration/calibration.json")
    need(native_cal["reexec_rejected"], "missing rejected second exec")
    for label, multiplier in [("serial", 1), ("threads", 3), ("fork", 0)]:
        vals = [counter(j(f"per-rustc-calibration/{label}-{n}/per-rustc.json")["targets"]["probe"]) for n in (3000000, 14000000)]
        info = native_cal["known_two_instruction_loop"][label]
        need(vals == info["counts"] and vals[1] - vals[0] == info["measured_delta"] and abs(vals[1] - vals[0] - multiplier * 22000000) <= 100000, "failed raw calibration")
    need(j("intake.json")["sdk_lock_sha256"] == study["sdk_lock_sha256"] and j("intake.json")["signed_cargo_sha256"] == "3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871", "different signed Cargo")
    pair = json.loads((HERE/"pair.json").read_bytes())
    need(pair["roles"] == roles, "wrong source role order")
    for i,r in enumerate(roles):
        sel = pair["arms"][r]
        got = j("intake.json")["installed"][r]
        need(got["server"] == sel["artifact"] and sel["driver"] in got["runtime"].values() and sel["source"]["commit"] == SOURCE[i] and sel["source"]["epoch"] == 43311, "different installed compiler")
    for tag in ("coroutine-transition", "foreign-transition"):
        test = j(f"intake/{tag}/passed.json")
        need(not test["self_check"] and len(test["modes"]) == 4, "missing true cache-compatibility fixtures")
        for mode, visits in test["modes"].items():
            need(len(visits) == 7 and visits[2]["asserted_incremental_state"] == ("loaded" if mode.endswith("-shared") else "not-loaded"), "wrong native cache path")
            need(visits[2]["binary"] == visits[3]["binary"] == visits[5]["binary"] and visits[4]["commands"]["reader"]["codes"] == visits[6]["commands"]["reader"]["codes"] == ["E0061"], "wrong actual binary or diagnostics")
    data = {}
    for h in (0, 1):
        for r in roles:
            q = f"uv-client/hold-{h}-{r}/"
            a, b, cold = [j(q + name + "/products.json") for name in ("ordinary-A", "warm-B", "cold-B")]
            need(a == j(q+"settled-A/products.json") == j(q+"typed-fresh-A/products.json"), "A did not settle")
            need(b == j(q+"settled-B/products.json") == j(q+"typed-fresh-B/products.json") == j(q+"typed-B/products.json"), "B did not settle")
            for key in ("relative_paths", "semantic", "structural", "public_sidecars"):
                need(b[key] == cold[key], "incremental/cold B disagrees")
            need(len(b["raw"]) == 37 and set(b["raw"]) == set(study["native_workspace_units"]), "wrong workspace products")
            for phase in ("typed-fresh-A", "typed-B", "typed-fresh-B"):
                units = j(q+phase+"/actual-units.json")
                need(len(units["units"]) == units["count"] == 486 and sha(canonical(units["units"])) == units["logical_sha256"] == study["native_complete_unit_sha256"], "wrong complete Cargo unit graph")
                need({k:v["rmeta"] for k,v in units["workspace"].items()} == a["relative_paths"], "wrong workspace artifact paths")
                roster = j(q+phase+"/roster.json")
                need(roster["artifact_crates"] == ({n:1 for n in CRATES} if phase == "typed-B" else {}), "wrong actual dirty set")
            need(j(q+"A-unit-graph.json")["logical_sha256"] == j(q+"B-unit-graph.json")["logical_sha256"] == study["structural_graph_sha256"], "changed structural graph")
            if h == 0:
                fixtures = [j(q+"behavior-"+n+"/witness.json") for n in ("A", "B", "cold-B")]
                need(all(x["exact"] for x in fixtures) and len({x["output_sha256"] for x in fixtures}) == 1, "linked behavior mismatch")
            forms = j(q+"typed-B/roster.json")["commands"]
            selected = {v[v.index("--crate-name")+1]:v for v in forms}
            need(len(forms) == len(selected) == 8, "not eight native calls")
            ck = j(q+"checkpoint.json")
            need(ck["hold"] == h and ck["role"] == r and ck["count"] > 0, "wrong source checkpoint")
            data[h,r] = selected,b,ck["sha256"]
    rows = j("uv-client/raw-pairs.json")
    need(len(rows) == 8 and study["independent_holds"] == [0]*4+[1]*4, "not two four-pair holds")
    arm_order = [(0,1),(1,0),(1,0),(0,1),(1,0),(0,1),(0,1),(1,0)]
    metrics = {k:[] for k in ["wall","whole_cargo","sum_of_eight",*sorted(CRATES)]}
    for i, row in enumerate(rows):
        h = i // 4
        need(row["pair"] == i and row["hold"] == h and row["order"] == [roles[n] for n in arm_order[i]] == study["orders"][i] and row["modes"] == study["mode_orders"][i], "changed pair/metric order")
        pair = {}
        for r in roles:
            p = f"uv-client/pair-{i}-{r}/"
            selectors, b, ck = data[h,r]
            v = row["values"][r]
            for mode in row["modes"]:
                d = p + mode + "/"
                source = j(d+"source.json")
                need(source["head"] == study["A"] and source["index"] == study["A_tree"], "wrong HEAD/index")
                need(source["working_tree"] == study["B_tree"] and source["source"] == study["B_file"] and source["lock"] == study["lock_sha256"] and v[mode]["checkpoint_sha256"] == ck, "not a restored genuine first edit")
                need(j(d+"products.json") == b and j(d+"same-seed-equivalence.json")["passed"], "not the same actual product")
            wall = j(p+"wall/ordinary.json"); whole = j(p+"clock/ordinary.json"); hw = j(p+"clock/whole-clock.json")
            for x in (wall,whole):
                need(x["argv"] == COMMAND and x["exit"] == 0 and x["boot"] == ready["boot"] and x["cpus"] == ready["affinity"] and x["end_ns"]-x["start_ns"] == x["ns"] > 0, "bad command clock")
            need(wall["invoked"] == COMMAND and wall["mode"] == "native" and wall["env"] == whole["env"] and not any(k == "RUSTC_WRAPPER" or k == "RUSTC_WORKSPACE_WRAPPER" for k in wall["env"]), "instrumented plain wall")
            need(whole["mode"] == "pmu" and whole["invoked"][0] == ready["plain"] and whole["invoked"][2:] == COMMAND and hw["enabled"] == hw["running"] > 0 and hw["code"] == hw["event_errno"] == 0, "invalid whole-Cargo hardware clock")
            need(wall["ns"] == v["wall"]["value"] and hw["instructions"] == v["clock"]["value"], "wrong whole-command reading")
            req, events, ids, perf = [j(p+n) for n in ("scoped-request.json","scoped/kernel-events.json","scoped/images.json","scoped/per-rustc.json")]
            need(req["environment"] == wall["env"], "different per-process environment")
            counts = counted(req, events, ids, perf, selectors)
            need(counts == j(p+"scoped/counts.json") == v["scoped"]["counts"] and v["scoped"]["qualified"], "unreproducible counter totals")
            if hostile and i==0 and r==roles[0]:
                damaged = deepcopy(perf)
                damaged["targets"]["uv_client"]["instructions"] += 1
                expect_refusal(lambda:counted(req,events,ids,damaged,selectors))
                damaged = deepcopy(perf)
                damaged["targets"]["uv_client"]["pid"] = damaged["targets"]["uv_cache"]["pid"]
                expect_refusal(lambda:counted(req,events,ids,damaged,selectors))
                damaged = deepcopy(req)
                damaged["selectors"]["uv_client"].append("--test")
                expect_refusal(lambda:counted(damaged,events,ids,perf,selectors))
                damaged = deepcopy(events)
                damaged["events"] = [v for v in damaged["events"] if v != [events["root"], 0]]
                expect_refusal(lambda:counted(req,damaged,ids,perf,selectors))
            pair[r] = dict(counts,wall=wall["ns"],whole_cargo=hw["instructions"],sum_of_eight=sum(counts.values()))
        for k in metrics:
            metrics[k].append([pair[r][k] for r in roles])
    res = {k:paired(v,Fraction(5,4) if k=="uv_install_wheel" else Fraction(1)) for k,v in metrics.items()}
    tests = ["uv_client","sum_of_eight","uv_install_wheel"]
    cumulative = 0
    reported = j("uv-client/score.json")
    need(reported["eligible"] and reported["physical_complete"] and not reported["same_seed_refusals"], "original run refused measurement")
    for i,k in enumerate(sorted(tests,key=lambda v:res[v]["one_sided_sign_p"])):
        cumulative = min(1,max(cumulative,res[k]["one_sided_sign_p"]*(len(tests)-i)))
        res[k]["holm_p"] = cumulative
        rep = next(x for x in reported["holm"] if x["name"]==k)
        need(rep["holm_p"] == cumulative and rep["above"] == res[k]["above"] and rep["p"] == res[k]["one_sided_sign_p"], "Holm/sign mismatch")
    return res


def expect_refusal(thunk):
    try:
        thunk()
    except (ValueError, KeyError):
        return
    raise ValueError("mutated actual evidence was accepted")


if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original",type=Path,help="also verify the full, original Actions ZIP and every selected member against it")
    ap.add_argument("--github-cli",help="also query the private Actions run, job and artifact, e.g. /home/dev-user/.local/bin/gh-auto")
    ap.add_argument("--self-test",action="store_true",help="also reject tampered genuine native data")
    ap.add_argument("--json",action="store_true",help="show every individual count, paired ratio and original order")
    args=ap.parse_args()
    origin,study,members=sources(args.original,args.github_cli)
    result=verify(origin,study,members,args.self_test)
    if args.json:
        print(json.dumps({"schema": 1, "role_order": study["roles"], "visit_orders": study["orders"], "by_endpoint": result},sort_keys=True,indent=2))
    else:
        print("Endpoint                  control / candidate    reduction    hold 1    hold 2    Holm p")
        for name,row in result.items():
            print(f"{name:25} {row['median_factor']:>10.5f}x {row['fewer_percent']:>10.2f}% {row['hold_medians'][0]:>9.5f} {row['hold_medians'][1]:>9.5f}   {row.get('holm_p','')}")
