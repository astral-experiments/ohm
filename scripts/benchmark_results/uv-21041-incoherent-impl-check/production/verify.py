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
RUN = 41423715247
JOB = 125205140087
ARTIFACT = 13131591831
HEAD = "37eb27d53652479648be37ff573e142b99b122f8"
ZIP_SHA = "9cf8d1f99e499755a504266b987000c5a4b476fe9a21f68945e1695cc6338d61"
SOURCE = ["f53496e2dd363b1455fc7e0a9d2dedea1bf7650e", "77ce0545653df71f43e601c28dde01a5e4f02b09"]
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
    need(origin["original"]["digest"] == "sha256:" + ZIP_SHA and origin["original"]["size_in_bytes"] == 40167164, "wrong original artifact")
    p = HERE / "evidence.tar.xz"
    need(file_sha(p) == "6a10f02618a4e0999cf772b1d036bcf4ebd62403bfee77945b2f1d86cee4892e" == origin["checksums"]["selected_archive"] and p.stat().st_size == origin["selected_archive_bytes"], "changed portable archive")
    need(file_sha(HERE / "pair.json") == origin["checksums"]["native_sdk_lock"] == "403777de9a8827bcf95517caf1f55998fc39bfa408e67b6a162ef77cd6f8595b", "wrong source and SDK pair")
    need(file_sha(HERE / "study.json") == "c0b4cbf8d3240172a9a005e27b4ec9623344ae49c6018f2e190c95cbc4794035" == origin["checksums"]["packaged_study"], "changed protocol")
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
            need(len(members) < 850, "too many members")
            data = files.extractfile(f).read(f.size + 1)
            need(len(data) == f.size, "truncated member")
            members[f.name] = data
    manifest = "".join(f"{k}\t{len(v)}\t{sha(v)}\n" for k, v in sorted(members.items())).encode()
    need(sha(manifest) == "8af6498c52d85f109f7b1e524c6692f383381feb8646b561e379efc149657135" == origin["checksums"]["selected_exact_members"] and len(members) == origin["selected_file_count"] == 486, "wrong selected original bytes")
    need(sum(map(len, members.values())) == origin["selected_raw_bytes"] == 25814917, "wrong selected size")
    if original:
        need(original.stat().st_size == 40167164 and file_sha(original) == ZIP_SHA, "wrong full ZIP")
        with zipfile.ZipFile(original) as z:
            need(len(z.infolist()) == len(set(z.namelist())) == origin["n_original_members"] == 1539, "wrong original members")
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
    need(j("calibration.json")["unmultiplexed_calibration_clocks"] == 28 and ready["boot"] == "c0cef69c-0c2e-4bf2-a63b-eee0dc0947d6", "wrong calibration")
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
        need(got["server"] == sel["artifact"] and sel["driver"] in got["runtime"].values() and sel["source"]["commit"] == SOURCE[i] and sel["source"]["epoch"] == (43309,43317)[i], "different installed compiler")
    boot=j("fresh-boot.json");need(boot["boot"]==ready["boot"]and boot["boot"]not in boot["excluded"]and boot["excluded"]==sorted(v["boot"] for v in pair["prior_boots"].values()) and len(boot["excluded"])==14,"repeated hardware or changed enrollment")
    for key,filename in [("thread_calibration","per-rustc-calibration/calibration.json"),("blocking_clock","blocking-clock/passed.json"),("calibration","calibration.json")]:
        need(boot[key]==sha(blobs[filename]),"wrong same-boot calibration")
    for phase in ("blocking-clock","blocking-clock-post"):
        cal=j(phase+"/passed.json");need(cal["machine"]=={"boot":ready["boot"],"cpus":ready["affinity"]} and len(cal["samples"])==25 and cal["nonzero_exit"]==17 and cal["deadline_exit"]==-9,"invalid native wait calibration")
    ns=j("intake/domain-native/accepted.json");checked=j("intake/domain-native/epoch/passed.json")
    need(checked["signed_argv_refusal_both_directions"] and checked["same_sdk_self_loaded_before_and_after"]and checked["no_compiler_version_override"]and checked["no_header_edit"]and checked["reader_compilations"]==10 and ns["epochs"]==sha(blobs["intake/domain-native/epoch/passed.json"]),"lost two-way incompatible cache refusal")
    for k in ("0-to-1","1-to-0"):
        row=checked["genuine_session_headers"][k]
        need(row["rejected_then_fresh"]["actual_epoch_refusals"]and row["rejected_then_fresh"]["binary"]==row["reused_own"]["binary"]==row["independent_cold"]["binary"],"foreign cache admitted or behavior changed")
    for i,(r,name)in enumerate(zip(roles,("control","candidate"))):
        f="intake/domain-native/"+name+"/qualified.json";p=j(f)
        need(p["registered_foreign_transitions"]==11 and p["actual_empty_edit_typeck"]==dict.fromkeys(("read_adt","read_str","read_reference"),1-i)and p["warm_cold_binary_and_errors"]and ns["roles"][r]["oracle"]==sha(blobs[f]),"incorrect native methods")
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
            for tag,baseline in (("A",a),("B",b)):
                base=q+"unchanged-kernel-"+tag+"/";images,exits=event_tree(j(base+"kernel-events.json"));chosen=j(base+"compiler-image.json");stamp=j(base+"zero.json")
                need(chosen["sha256"]==j("intake.json")["installed"][r]["runtime"]["bin/rustc"] and stamp["events_sha256"]==sha(blobs[base+"kernel-events.json"]),"no-op observer or image substitution")
                need(images[0][1]["argv"]==COMMAND and exits[images[0][0]]==0 and all(im["file"]!=chosen["id"]and PurePosixPath(im["exe"]).name!="rustc"for _,im in images),"unchanged Cargo launched rustc")
                need(stamp["rustc_images"]==0 and j(base+"products.json")==baseline and blobs[base+"stdout"]==b"" and b"Finished "in blobs[base+"stderr"],"changed no-op native products")
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
    metrics = {k:[] for k in ["wall","sum_of_eight",*sorted(CRATES)]}
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
            wall = j(p+"wall/ordinary.json")
            for x in (wall,):
                need(x["argv"] == COMMAND and x["exit"] == 0 and x["boot"] == ready["boot"] and x["cpus"] == ready["affinity"] and x["end_ns"]-x["start_ns"] == x["ns"] > 0, "bad command clock")
            need(wall["timer"]=="CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog" and not wall["deadline_fired"] and wall["invoked"] == COMMAND and wall["mode"] == "native" and not any(k == "RUSTC_WRAPPER" or k == "RUSTC_WORKSPACE_WRAPPER" for k in wall["env"]), "instrumented plain wall")
            need(wall["ns"] == v["wall"]["value"], "wrong whole-command reading")
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
            pair[r] = dict(counts,wall=wall["ns"],sum_of_eight=sum(counts.values()))
        for k in metrics:
            metrics[k].append([pair[r][k] for r in roles])
    res = {k:paired(v,Fraction(5,4) if k=="uv_metadata" else Fraction(1)) for k,v in metrics.items()}
    selected="uv_metadata";ratios=[Fraction(b,a)for a,b in metrics[selected]];wins=sum(v<Fraction(4,5)for v in ratios);p=sum(comb(8,i)for i in range(wins,9))/256
    both=[float(median(v))for v in (ratios[:4],ratios[4:])];rep=j("uv-client/score.json");t=rep["primary_test"]
    need(rep["eligible"]and rep["physical_complete"]and not rep["same_seed_refusals"]and t==j("uv-client/native-rustc.json")["primary_test"],"actual study incomplete or inconsistent")
    need(t["primary"]==selected and t["wins"]==wins and t["one_sided_exact_sign_p_ties_counted_against"]==p and t["two_hold_median_ratios"]==both and t["qualified"]==(all(v<.8 for v in both)and p<=.05),"wrong prespecified effect or confidence")
    res[selected]["registered_primary"]=t
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
        print("Endpoint                  control / candidate    reduction    hold 1    hold 2    Primary sign p")
        for name,row in result.items():
            print(f"{name:25} {row['median_factor']:>10.5f}x {row['fewer_percent']:>10.2f}% {row['hold_medians'][0]:>9.5f} {row['hold_medians'][1]:>9.5f}   {row.get('registered_primary',{}).get('one_sided_exact_sign_p_ties_counted_against','')}")
