"""Recalculate the twelve production pairs from the selected original evidence."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import statistics
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
DATA_SHA = "e8f91feb5df69788f29b472da482ac3005b8433b3a77d108945b85260f0c8783"
ORIG_SHA = "57f9bef5eb224bb70823c6d7df3f9611289f89b2af8d3c851f1486b9e0d778cd"
SDK_LOCK = "b7b8705a2200ac514d219383339009d92ed3fe4046846b60010c60359d06f019"
ROLES = ("stock_ctfe318","fa7a_stack_ctfe318")
METRICS = ("wall_nanoseconds","user_instructions")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":")).encode()

def semantics(proof, left, right):
    assert left.keys() == right.keys() and len(left) == 70
    drift = {name for name in left if left[name] != right[name]}
    terminal, = [name for name in left if "/out/libuv-" in name]
    assert set(proof["raw_drift"]) == drift and proof["all_70_roots_and_deps_equal"] is True
    assert proof["actual_downstream"] and set(proof["deep"]) == drift | {terminal}
    for name, detail in proof["deep"].items():
        assert detail["raw_equal"] == (name not in drift)
        projection = detail["projection"]
        for field in ("all_definitions","allocation_content_counts","all_reachable_expansions"):
            assert len(bytes.fromhex(projection[field])) == 32
        assert len(bytes.fromhex(projection["header"]["allocation_order_sha256"])) == 32

def replay(original):
    packet = HERE/"evidence.tar.xz"
    if not __debug__:
        raise RuntimeError("Run Python with assertions enabled")
    assert file_digest(packet) == DATA_SHA
    with tarfile.open(packet,"r:xz") as tar:
        files = {m.name:tar.extractfile(m).read() for m in tar if m.isfile()}
    assert len(files) == 291
    def read(name):
        return json.loads(files[name])
    run = read("service.json")
    assert (run["run"],run["job"],run["id"],run["conclusion"],run["sha256"]) == (41393501771,125109757150,13119104713,"success",ORIG_SHA)
    if original:
        assert original.stat().st_size == run["bytes"] and file_digest(original) == ORIG_SHA
        with zipfile.ZipFile(original) as archive:
            assert len(archive.infolist()) == run["members"]
            for name in files.keys()-{"protocol.json","service.json"}:
                assert archive.read(name) == files[name]
    protocol, result = read("protocol.json"),read("result.json")
    assert result["protocol_sha256"] == digest(files["protocol.json"])
    assert result["sdk_lock"] == SDK_LOCK == digest(files["intake/sdk-lock.json"])
    assert read("intake.json")["build_run"] == 41374825846 and read("intake/cache-transition.json")["native_processes"] == 16
    case = result["source"]
    assert case == protocol["case"] and case["B"] == "1979349b68dbaa936b98c0f409c1df0598fa72f1"
    assert read("panel-finished.json")["observed_pairs"] == len(protocol["orders"]) == len(result["pairs"]) == 12
    host = read("host.json")
    abi = read("calibration.json")["abi"]
    assert abi["config"] == "PERF_COUNT_HW_INSTRUCTIONS" and (abi["inherit"],abi["exclude_kernel"],abi["exclude_hv"]) == (1,1,1)
    baselines = {}
    for role in ROLES:
        source = protocol["roles"][role]
        built = read("intake/role-material/"+role+"/role.json")
        assert (built["source_commit"],built["source_tree"],built["epoch"]) == (source["commit"],source["tree"],source["epoch"])
        assert built["bolt_note"] is True and "executed PGO" in built["execution_pgo"]
        assert read("final-sdk.json")[role]["runtime"]["bin/cargo"] == result["signed_cargo"] == protocol["signed_cargo_sha256"]
        q = "qualification-"+role+"/"
        states = read(q+"four-state.json")
        assert digest(files[q+"four-state.json"]) == result["qualification"][role]
        for state in ("A","B"):
            fixture = read(q+"fixture-"+state+"/receipt.json")
            assert fixture["exit"] == 0 and fixture["tree"] == case[state+"_tree"] and fixture["passed"] == case["fixture"][state]
        maps = {key:read(q+key+"/workspace-products.json") for key in ("A-to-B","cold-B1","cold-B2")}
        for key,x,y in (("cold-B1","A-to-B","cold-B1"),("cold-B2","A-to-B","cold-B2"),("both-independent-cold","cold-B1","cold-B2")):
            semantics(states["comparisons"][key],maps[x],maps[y])
        baselines[role] = maps["cold-B1"]
    rows = []
    seeds = set()
    argv_digest = None
    last = 0
    for d, scored in zip(protocol["orders"],result["pairs"],strict=True):
        assert scored["design"] == d and set(d["roles"]) == set(ROLES)
        values = {}
        for role in d["roles"]:
            p = f"hold{d['hold']}-pair{d['pair']:02d}-{role}/"
            accepted, seed = read(p+"accepted.json"),read(p+"A-snapshot.json")
            assert (accepted["A"],accepted["B"]) == (case["A_tree"],case["B_tree"])
            assert (accepted["hold"],accepted["pair"],accepted["role"]) == (d["hold"],d["pair"],role)
            assert accepted["A_snapshot"] == seed["tree_sha256"] and seed["tree_sha256"] not in seeds
            seeds.add(seed["tree_sha256"])
            assert {epoch for _,epoch,_ in seed["actual_incremental_headers"]} == {protocol["roles"][role]["epoch"]}
            products = read(p+"native/workspace-products.json")
            assert digest(canonical(products)) == accepted["same_seed_raw_sha256"]
            for visit in ("pmu","typed","scoped"):
                assert products == read(p+visit+"/workspace-products.json")
            semantics(accepted["independent_cold"],products,baselines[role])
            typed, kernel = read(p+"typed/observed.json"),read(p+"scoped/compiler-execs.json")
            assert (typed["rows"],typed["build_scripts"],typed["workspace"],typed["diagnostics"]) == (641,51,70,[])
            assert len({x["pid"] for x in kernel["compilations"]}) == kernel["all_rustc"] == accepted["genuine_children"] == 18
            args = sorted(x["argv"] for x in kernel["compilations"])
            assert args == typed["argv"] and kernel["command"] == protocol["argv"] and kernel["score"] is False
            normalized = digest(canonical(args))
            assert argv_digest is None or argv_digest == normalized
            argv_digest = normalized
            counts = {}
            for mode in d["modes"]:
                r = read(p+mode+"/ordinary.json")
                assert r["boot"] == host["boot"] and r["cpus"] == host["cpus"] and r["env"] == protocol["env"]
                assert r["exit"] == 0 and r["mode"] == mode and r["argv"] == protocol["argv"]
                assert last < r["start_ns"] < r["end_ns"] and r["ns"] == r["end_ns"]-r["start_ns"]
                last = r["end_ns"]
                if mode == "native":
                    assert r["invoked"] == r["argv"]
                    counts["wall_nanoseconds"] = r["ns"]
                else:
                    assert r["invoked"][2:] == r["argv"] and r["invoked"][1].endswith(p+"pmu/whole-clock.json")
                    pmu = read(p+"pmu/whole-clock.json")
                    assert pmu["running"] == pmu["enabled"] > 0 and pmu["code"] == pmu["event_errno"] == 0
                    assert pmu["instructions"] > 0 and pmu["stop"] > pmu["start"] > 0
                    counts["user_instructions"] = pmu["instructions"]
            values[role] = counts
        assert values == scored["values"]
        rows.append((d,values))
    for metric in METRICS:
        ratios = [Fraction(v[ROLES[0]][metric],v[ROLES[1]][metric]) for _,v in rows]
        m = result["metrics"][metric]
        assert ratios == [Fraction(x["fraction"]) for x in m["paired_ratios"]]
        mid = statistics.median(ratios)
        low, high = sorted(ratios)[1],sorted(ratios)[-2]
        assert [mid,low,high] == [Fraction(x["fraction"]) for x in [m["median"],*m["interval_order_2_11"]]]
        for field,groups,key in (("hold_medians",(1,2),lambda d:d["hold"]),("first_role_medians",ROLES,lambda d:d["roles"][0])):
            for group in groups:
                sub = [x for x,(d,_) in zip(ratios,rows,strict=True) if key(d)==group]
                assert len(sub)==6 and statistics.median(sub)==Fraction(m[field][str(group)]["fraction"])
        assert sum(x>1 for x in ratios) == m["wins_over_parity"]
        assert sum(x>2 for x in ratios) == m["wins_over_double"]
        a,b = [statistics.median(v[role][metric] for _,v in rows)/1e9 for role in ROLES]
        unit = "seconds" if metric == "wall_nanoseconds" else "billion userspace instructions"
        print(f"{a:.6f} -> {b:.6f} {unit}, {float(mid):.6f}x [{float(low):.6f}, {float(high):.6f}], {m['wins_over_parity']}/12 above parity, {m['wins_over_double']}/12 above 2x")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original",type=Path,help="also compare every selected member with the complete original Actions ZIP")
    replay(parser.parse_args().original)
