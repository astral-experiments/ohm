"""Recalculate both prespecified median instruction ratios from original, per-PID hardware records."""
import argparse
from fractions import Fraction
import hashlib
import json
from math import comb
from pathlib import Path
from statistics import median
import struct
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
PACKET = "67f7e8f81a4f38fd3afcc80abd1af5285bea6472860d4ddaa45a310036755081"
ORIGINAL = "ed8aa6376104fcc84a9fe5566b4488f1e48cbdfea834376518d28795685abdcc"
SDK_LOCK = "b7b8705a2200ac514d219383339009d92ed3fe4046846b60010c60359d06f019"
TARGETS = ("uv-lib","uv_resolver-lib")
ROLES = ("stock_ctfe318","fa7a_stack_ctfe318")

def file_sha(path):
    with path.open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(x):
    return json.dumps(x,separators=(",",":"),sort_keys=True).encode()

def decode_counter(row):
    actual = struct.unpack("<4Q",bytes.fromhex(row["raw_hex"]))
    assert actual == tuple(row[k] for k in ("instructions","time_enabled_ns","time_running_ns","event_id"))
    value,enabled,running,event_id = actual
    assert value > 0 and enabled == running > 0 and event_id > 0
    return value

def kernel(data):
    root = data["root"]
    assert type(root) is int and root > 0 and data["options"] == 0x10001e
    parents,exits,handoffs,images = {},{},{},[]
    for event in data["events"]:
        pid,status = event[:2]
        if status == "resume-ESRCH": continue
        assert type(status) is int and 0 <= status < 1<<24
        if status & 255 != 127:
            assert len(event) == 2 and pid not in exits
            exits[pid] = -(status & 127) if status & 127 else status >> 8
        else:
            assert status & 65535 == (5<<8)|127
            child = event[2]
            if status >> 16 in (1,2,3):
                assert len(event) == 3 and child not in parents and child != pid and child != root
                parents[child] = pid
            else:
                assert status >> 16 == 4 and len(event) == 4
                images.append((pid,event[3]))
                if pid != child:
                    assert child not in handoffs
                    handoffs[child] = pid
    live = {root,*parents}
    assert live == set(exits)|set(handoffs) and exits[root] == 0 and images[0][0] == root
    for child in parents:
        visited = set()
        while child != root:
            assert child not in visited and child in parents
            visited.add(child);child = parents[child]
    return root,images,exits

def replay(original):
    if not __debug__: raise RuntimeError("Run Python with assertions enabled")
    packet = HERE/"evidence.tar.xz"
    assert file_sha(packet) == PACKET
    with tarfile.open(packet,"r:xz") as tar:
        files = {t.name:tar.extractfile(t).read() for t in tar if t.isfile()}
    def read(name): return json.loads(files[name])
    service = read("service.json")
    assert (service["run"],service["job"],service["conclusion"],service["sha256"]) == (41385306015,125084718448,"success",ORIGINAL)
    if original:
        assert original.stat().st_size == service["bytes"] and file_sha(original) == ORIGINAL
        with zipfile.ZipFile(original) as archive:
            for name in files.keys()-{"service.json","protocol.json","thread-protocol.json"}: assert files[name] == archive.read(name)
    protocol,plan = read("protocol.json"),read("thread-protocol.json")
    print("Production rustc on uv #20988")
    report = read("result.json")
    assert digest(files["intake/sdk-lock.json"]) == report["SDK_lock"] == plan["sdk_lock"] == SDK_LOCK
    assert report["primary"] == list(TARGETS) == plan["primary"] and report["protocol"] == digest(files["thread-protocol.json"])
    assert protocol["case"]["B"] == "1979349b68dbaa936b98c0f409c1df0598fa72f1"
    assert read("panel-finished.json")["observed_pairs"] == 8 and plan["order"] == protocol["orders"]
    chost = read("per-rustc-calibration/source.json");host = read("host.json")
    assert chost["tool"] == plan["meter_commit"] and chost["host"] == {k:host[k] for k in ("boot","cpus")}
    proof = read("per-rustc-calibration/calibration.json")
    assert proof["reexec_rejected"] is True and b"measured process executed a second image" in files["per-rustc-calibration/reexec-3000000.stderr"]
    for mode,factor in (("serial",1),("threads",3),("fork",0)):
        counts = [decode_counter(read(f"per-rustc-calibration/{mode}-{n}/per-rustc.json")["targets"]["probe"]) for n in (3000000,14000000)]
        delta = counts[1]-counts[0];want = 22000000*factor
        assert abs(delta-want) <= 100000 and proof["known_two_instruction_loop"][mode] == {"counts":counts,"expected_delta":want,"measured_delta":delta}
    for role in ROLES:
        props=read("intake/role-material/"+role+"/role.json")
        assert (props["source_commit"],props["epoch"]) == (protocol["roles"][role]["commit"],protocol["roles"][role]["epoch"])
        assert props["bolt_note"] is True and "executed PGO" in props["execution_pgo"]
        assert read("final-sdk.json")[role]["runtime"]["bin/cargo"] == protocol["signed_cargo_sha256"]
        q="qualification-"+role+"/"
        assert all(v["all_70_roots_and_deps_equal"] and v["actual_downstream"] for v in read(q+"four-state.json")["comparisons"].values())
        for state in ("A","B"):
            witness=read(q+"fixture-"+state+"/receipt.json")
            assert witness["exit"] == 0 and witness["passed"] == protocol["case"]["fixture"][state]
    seeds = set();series = {r:{k:[]for k in TARGETS} for r in ROLES}
    for design,summary in zip(plan["order"],report["pairs"],strict=True):
        assert summary["design"] == design
        for role in design["roles"]:
            p = f"hold{design['hold']}-pair{design['pair']:02d}-{role}/"
            accepted = read(p+"accepted.json");seed = read(p+"A-snapshot.json");meta=read(p+"counted/source.json")
            assert (accepted["hold"],accepted["pair"],accepted["role"]) == (design["hold"],design["pair"],role)
            assert accepted["A_snapshot"] == seed["tree_sha256"] and seed["tree_sha256"] not in seeds
            seeds.add(accepted["A_snapshot"])
            assert meta["host"]==chost["host"] and meta["role"]==role and meta["library"]==chost["library"]
            product=read(p+"native/workspace-products.json")
            assert len(product)==70 and digest(canonical(product))==accepted["same_seed_raw_sha256"] and accepted["independent_cold"]["all_70_roots_and_deps_equal"]
            for mode in ("counted","scoped","typed"):assert read(p+mode+"/workspace-products.json")==product
            reference=read(p+"scoped/compiler-execs.json");typed=read(p+"typed/observed.json")
            assert reference["score"] is False and (typed["rows"],typed["workspace"],typed["diagnostics"])==(641,70,[])
            enrolled=sorted(x["argv"] for x in reference["compilations"])
            counts=read(p+"counted/per-rustc.json");root,images,exits=kernel(read(p+"counted/kernel-events.json"))
            assert counts["root"]==root and counts["scope"]=="retired userspace instructions in the selected process and its threads"
            assert images[0][1]["argv"]==protocol["argv"] and images[0][1]["file"]==meta["cargo_file"]
            rustc=[(pid,row) for pid,row in images if row["file"]==meta["compiler_file"]]
            assert len(enrolled)==len(rustc)==18 and len({pid for pid,_ in rustc})==18
            assert enrolled==typed["argv"]==sorted(row["argv"] for _,row in rustc)
            request=read(p+"counted/request.json")
            assert request["command"]==protocol["argv"] and request["environment"]==protocol["env"]
            assert set(request["selectors"])==set(counts["targets"])==set(TARGETS)
            assert len({r["event_id"] for r in counts["targets"].values()})==2
            for label in TARGETS:
                row=counts["targets"][label];argv=request["selectors"][label]
                exact,=[(pid,r)for pid,r in rustc if r["argv"]==argv]
                assert exact[0]==row["pid"] and exits[row["pid"]]==0 and row["file"]==exact[1]["file"] and row["exe"]==exact[1]["exe"]
                assert row["argv"]==argv and "-".join(argv[argv.index(k)+1] for k in ("--crate-name","--crate-type"))==label
                assert plan["primary_enrollment"][label]["features"]==sorted(x for i,x in enumerate(argv[1:],1) if argv[i-1]=="--cfg" and x.startswith("feature="))
                value=decode_counter(row);assert value==accepted["instructions"][label]==summary["values"][role][label]
                series[role][label].append(value)
                assert digest(canonical(request["selectors"]))==accepted["enrolled_argv_sha256"]
    assert len(seeds)==16 and [d["roles"][0]==ROLES[1] for d in plan["order"]]==[False,True,False,True,True,False,True,False]
    for label in TARGETS:
        base,treatment=[series[r][label]for r in ROLES]
        ratios=[Fraction(a,b)for a,b in zip(base,treatment,strict=True)]
        s=report["statistics"][label];wins=sum(r>Fraction(5,4) for r in ratios)
        assert len(ratios)==8 and ratios==[Fraction(x["fraction"])for x in s["ratios"]]
        assert median(ratios)==Fraction(s["paired_median"]["fraction"]) and min(ratios)==Fraction(s["simultaneous_lower_ratio"]["fraction"])
        p=min(Fraction(1),Fraction(2*sum(comb(8,k) for k in range(wins,9)),256))
        assert p==Fraction(s["bonferroni_p"]["fraction"]) and wins==s["above_20pct_fewer"]
        for kind,groups,by in [("hold_medians",(1,2),lambda d:d["hold"]),("first_role_medians",ROLES,lambda d:d["roles"][0])]:
            for group in groups:
                sub=[r for r,d in zip(ratios,plan["order"]) if by(d)==group]
                assert len(sub)==4 and median(sub)==Fraction(s[kind][str(group)]["fraction"])
        assert s["qualified_20pct"]==(wins==8 and p<Fraction(1,20))
        print(f"{label}: {median(base)/1e9:.6f}B -> {median(treatment)/1e9:.6f}B. {100*float(1-1/median(ratios)):.3f}% fewer, {wins}/8 above 20%, adjusted p={float(p):.8f}.")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original",type=Path,help="optionally check all included original members against the complete Actions ZIP")
    replay(parser.parse_args().original)
