"""Rebuild the portable observations from the two original GitHub Actions artifact ZIPs."""
import gzip
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

PARENT = "2035696c5316079f5b2e4373aee834839aac97e9"
CHILD = "444c0273a2e2bc0b161e988d43c882349bc2d7a6"
ARCHIVES = {
    "signed": (41048321533, "7c4cfa668f1a58bfe3092051a70b86197092efa400b1fa6a72599d836d51c2b6", 179),
    "qualified": (41048813491, "43e46340f95c438d2ea149f19c5305a144fde3d2f117a74f3262a826eebcf825", 1371),
}
PHASES = ("edit", "repeat-1", "repeat-2")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class Original:
    def __init__(self, role, path):
        self.z = ZipFile(path)
        self.files = set(x.filename for x in self.z.infolist() if not x.is_dir())
        assert sha(Path(path).read_bytes()) == ARCHIVES[role][1]
        assert len(self.files) == ARCHIVES[role][2] and self.z.testzip() is None

    def data(self, name):
        return self.z.read(name)

    def obj(self, name):
        return json.loads(self.data(name))

    def unpack(self, name):
        return gzip.decompress(self.data(name))

    def hash(self, name):
        return sha(self.data(name))

    def streams(self, dirname, sums):
        for key, value in sums.items():
            filename = "exec.json.gz" if key == "native_events" else key + ".gz"
            assert sha(self.unpack(dirname + "/" + filename)) == value


def native(z, dirname, declared, kernel, sdk_name):
    rows = json.loads(z.unpack(dirname + "/exec.json.gz"))
    full, link_only, lds, compilers = [], [], [], []
    for row in rows:
        exe = row["path"].rsplit("/", 1)[-1]
        args = row["argv"]
        if exe == "rustc" and "--crate-name" in args:
            assert row["path"].endswith("/" + sdk_name + "/bin/rustc")
            crate = args[args.index("--crate-name") + 1]
            if crate == "___" and any(a == "--print" or a.startswith("--print=") for a in args):
                continue
            assert not any("ohm-branch-cache" in a or "incremental-branches" in a for a in args)
            bucket = link_only if any("link-only" in a for a in args) else full
            bucket.append(crate)
            compilers.append([crate, row["pid"], row["ppid"], sha(encoded(args)), row["cdhash"]])
        if exe in ("ld", "ld64", "ld-prime", "ld-classic", "rust-lld", "wild", "wild-ld", "ld.lld"):
            assert row["path"] == kernel["path"] and row["cdhash"] == kernel["cdhash"]
            lds.append((row["argv"], row["pid"]))
    assert sorted(full) == declared["full"] and sorted(link_only) == declared["link_only"], dirname
    assert [a for a, _ in lds] == [e["argv"] for e in declared["linkers"]]
    assert all(e["stock"] and e["sha"] == kernel["sha"] for e in declared["linkers"])
    return {"full": sorted(full), "link_only": sorted(link_only), "apple_ld": len(lds),
            "compiler_events": sorted(compilers), "exec_gzip": z.hash(dirname + "/exec.json.gz")}


def kernel(z):
    cal = z.obj("observer.json")
    linkers = [(e["path"], e["cdhash"]) for e in cal["rows"] if e["path"].split("/")[-1] == "ld"]
    assert len(linkers) == 1 and cal["exit"] == 29
    return {"path": linkers[0][0], "cdhash": linkers[0][1], "sha": cal["ld"]}


def phase(z, path, v, observer, sdk_name):
    z.streams(path, v["cargo"]["streams"])
    actual = [json.loads(line) for line in z.unpack(path + "/stdout.gz").splitlines()]
    assert actual[-1] == {"reason": "build-finished", "success": v["success"]}
    artifacts = [r for r in actual if r["reason"] == "compiler-artifact"]
    names = sorted(r["target"]["name"] for r in artifacts if not r["fresh"])
    assert names == sorted(d[1] for d in v["dirty"]) and len(artifacts) == len(v["roster"])
    codes = sorted(r["message"]["code"]["code"] for r in actual if r["reason"] == "compiler-message" and r["message"]["code"])
    assert codes == sorted(v["codes"])
    dep = z.unpack(path + "/zmij.dep.gz")
    assert (sha(dep), b"ohm-untracked-relink-inputs" in dep, b"/dev/null/ohm-recheck-dependent-links" in dep) == (v["marker"]["sha256"], v["marker"]["hard"], v["marker"]["recheck"])
    ans = {"success": v["success"], "state": v["state"], "dirty": names, "typed": len(artifacts), "codes": codes,
           "typed_identity": sha(encoded(v["roster"])), "zmij": v["marker"], "receipt": z.hash(path + "/verified.json")}
    if v["native"]:
        ans["native"] = native(z, path, v["native"], observer, sdk_name)
    if "ns" in v["cargo"]:
        clock = v["cargo"]
        assert clock["ns"] == clock["stop_ns"] - clock["start_ns"] > 0 and not v["native"]
        import re
        m = re.search(rb"([0-9.]+) real\s+([0-9.]+) user\s+([0-9.]+) sys",z.data(path + "/time.txt"))
        assert m and tuple(map(float,m.groups())) == (clock["wall"],clock["user"],clock["system"])
        ans["ns"], ans["cpu_ms"] = clock["ns"], round((clock["user"] + clock["system"]) * 1000)
    if v["reader"]:
        r = v["reader"]
        z.streams(path + "/reader/link", r["streams"])
        if r["native"]:
            observed = native(z, path + "/reader/link", r["native"], observer, sdk_name)
            assert observed["full"] == ["qa_version_reader"] and observed["apple_ld"] == 1 and not observed["link_only"]
        ans["product"] = {"reader": r["sha256"], "value": r["value"], "archive": r["archive_sha256"],
                          "objects": r["archive_objects"], "metadata": r["archive_metadata"]}
    return ans


def providers(z):
    ans = {}
    for terminal in sorted(n for n in z.files if n.startswith("native-input/") and n.endswith("/terminal.json")):
        d = terminal.rsplit("/", 1)[0]
        phases = {}
        for name, record in z.obj(terminal).items():
            s = d + "/" + name
            assert record == z.obj(s + "/verified.json")
            z.streams(s, record["streams"]["streams"])
            phases[name] = {k:record[k] for k in ("archive","cargo_exit","executable","value") if k in record}
        ans[d.split("/")[-1]] = phases
    return ans


def calibration(z):
    c = z.obj("calibration/result.json")
    for row in c["rows"]:
        n = "calibration/time-{rep}-{depth}-{iters}.txt".format(**row)
        raw = z.data(n)
        assert sha(raw) == row["time_raw"] and b"instructions retired" not in raw
    assert len(c["rows"]) == 18
    return {k:c[k] for k in ("tree_CPU_calibrated","user_seconds_deltas","retired_deltas","retired_instruction_scope")}


def projection(signed, qualified):
    s, q = Original("signed", signed), Original("qualified", qualified)
    sg, obs = kernel(s), kernel(q)
    release = q.obj("release.json")
    assert release["archive"] == s.obj("release.json")["archive"] == "7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8"
    pair = q.obj("pair.json")
    roles = pair["products"]
    diffs = [n for n, v in roles["P"]["runtime"].items() if v != roles["C"]["runtime"][n]]
    assert sorted(diffs) == sorted(pair["differ"]) and len(diffs) == 1 and diffs[0].startswith("lib/librustc_driver")
    assert set(roles["P"]["runtime"]) == set(roles["C"]["runtime"])
    assert all(roles["P"][n] == roles["C"][n] for n in ("stage0_cargo","stage0_rustc","build_argv","rustc","library_tree"))
    assert roles["P"]["build_argv"][-6:] == ["build","--stage","1","-j4","compiler/rustc","library"]
    out = {
        "qa_revision": "3290af7b378353c6a2808487bc93ed587ab024bb",
        "raw": {n:{"run":v[0],"zip_sha256":v[1],"files":v[2]} for n,v in ARCHIVES.items()},
        "source": {"parent":PARENT,"child":CHILD,"ruff":q.obj("ruff.json")["new"],"ruff_lock":q.obj("ruff.json")["lock"]},
        "sdk": {"release_sha":release["archive"],"cargo":release["cargo"]["sha256"],"signed_driver":release["driver"]["sha256"],
                "stage0_rustc":roles["P"]["stage0_rustc"]["sha256"],"stage0_cargo":roles["P"]["stage0_cargo"]["sha256"],
                "members":len(roles["P"]["runtime"]),"one_changed_member":diffs[0],
                "driver":{r:roles[r]["runtime"][diffs[0]] for r in "PC"},"run_make":q.obj("run-make.json")},
        "calibration":calibration(q),"apple_ld":obs["sha"],"causal":{},"proc_macro":{},"providers":providers(q),
        "confirm":{},"screen":{},"objects":{},"signed_native":{},
    }
    assert out["sdk"]["run_make"]["log"] == q.hash("run-make.log")
    for z, tag, names in [(s,"signed","S"),(q,"qualified","SPC")]:
        for role in names:
            base="proc-macro/"+role
            v=z.obj(base+"/verified.json")
            for step in ("producer","consumer","run"):
                command=z.obj(base+"/"+step+"/command.json");assert command["exit"]==0
                z.streams(base+"/"+step,command["streams"])
            assert z.unpack(base+"/run/stdout.gz")==b"3\n" and v["value"]==3
            assert any(n.startswith("libproc_macro-") and n.endswith(".rlib") for n in v["members"])
            out["proc_macro"][tag+"-"+role]=dict(value=3, members=v["members"],outputs=v["outputs"])
    for role, source in zip("PC",(PARENT,CHILD)):
        assert roles[role] == q.obj("bootstrap-"+role+"-product.json") and roles[role]["source"]==source
        assert roles[role]["build_log"] == q.hash("bootstrap-"+role+".log") and roles[role]["runtime"]["bin/cargo"] == out["sdk"]["cargo"]
    for label in ("untouched","omit-vector-comment","restored"):
        counts=[]
        for ph in ("cold","repeat-1","repeat-2"):
            d="causal/"+label+"/"+ph
            v=s.obj(d+"/verified.json")
            s.streams(d,v["streams"]["streams"])
            events=json.loads(s.unpack(d+"/exec.json.gz"))
            counts.append(sum(1 for r in events if r["path"].endswith("/signed/bin/rustc") and "--crate-name" in r["argv"] and r["argv"][r["argv"].index("--crate-name")+1]=="zmij"))
        out["causal"][label]=counts
    for ph in ("edit","repeat-1","repeat-2"):
        d="ruff-signed/"+ph
        r=s.obj(d+"/verified.json");out["signed_native"][ph]=native(s,d,r["native"],sg,"signed")
    # Each entity is a true returned product. Store identical SHA inventories once.
    def compact(value):
        if "product" in value:
            product=value.pop("product");key=sha(encoded(product));out["objects"].setdefault(key,product)
            value["product"]=key
        return value
    for mode in ("screen","confirm"):
        c=out[mode]
        plan=q.obj(mode+"/registered.json")
        result=q.obj(mode+"/result.json")
        assert result["registration"]==q.hash(mode+"/registered.json") and result["harness"]==plan["harness"]
        c.update(order=plan["order"], registration=result["registration"], accepted=result["accept_"+mode], cohorts={})
        terms=sorted(n for n in q.files if n.startswith(mode+"/") and n.endswith("/terminal.json"))
        for n in terms:
            where=n.rsplit("/",1)[0];t=q.obj(n);role=t["role"]
            assert t["compiler"]["driver"]["sha256"]==out["sdk"]["driver"][role] and t["compiler"]["cargo"]["sha256"]==out["sdk"]["cargo"]
            rows={}
            for ph,h in t["phase_sha256"].items():
                d=where+"/"+ph;assert q.hash(d+"/verified.json")==h
                rows[ph]=compact(phase(q,d,q.obj(d+"/verified.json"),obs,"native"))
            c["cohorts"][where[len(mode)+1:]]=rows
        c["reported"]={p:result["wall"][p] for p in PHASES}
        for arm in "PC":
            f=mode+"/native-before/"+arm+"/dyld/"
            v=q.obj(f+"verified.json");assert v["role"]==arm and v["loaded"][diffs[0]]["sha256"]==out["sdk"]["driver"][arm]
            assert sha(q.data(f+"test.o"))==v["object"]
    return out
