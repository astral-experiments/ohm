"""Reopen the private Actions ZIP and derive portable measurements from its original streams."""
import gzip
import hashlib
import json
import re
import struct
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
from macho import audit

PARENT = "2035696c5316079f5b2e4373aee834839aac97e9"
CHILD = "444c0273a2e2bc0b161e988d43c882349bc2d7a6"
QA = "51f61408905b3f1abe913641b5c13a1346011d77"
RUN = 41056802208
HARNESS_SHA = "d23b4c1b2a2f9d06b4a99f23ca6c0a74b6b2bba67d1b224409d3e89d21013129"
SIGNED_ZIP = "d91085ee544c70231dc3e18a2d9c3db8f2a02b6f5a53270a8bb853f19b108447"
SOURCE = ["b5dba861cc38e3f7fb4524c9ceba3e01a474ea13", "7b13f01ba1569887a25670820764b24c206da8e5"]
ORDERS = {"screen":["PC","CP"],"confirm":["CP","PC","CP","CP","CP","PC","PC","PC","PC","CP","CP","PC"]}
ENDPOINTS = ("edit","repeat-1","repeat-2")
PANICS = {"token::tokens::tests::"+n for n in (
    "tokens_after_offset_inside_token","tokens_before_offset_inside_token",
    "tokens_in_range_start_offset_inside_token","tokens_in_range_end_offset_inside_token",
    "tokens_split_at_inside_token","tokens_split_at_matches_before_and_after_zero_length",
)}

def mach_image(body):
    header=struct.unpack_from("<8I",body)
    magic,cpu,_,filetype,count,end,_,_=header
    assert magic==0xfeedfacf and cpu==0x0100000c and filetype==2 and end+32<=len(body)
    off=32;arrays=[];uuid=[]
    for _ in range(count):
        tag,length=struct.unpack_from("<II",body,off);assert length>=8 and off+length<=32+end
        if tag==0x1b:
            assert length==24
            uuid.append(body[off+8:off+24].hex())
        if tag==0x19:
            n=struct.unpack_from("<I",body,off+64)[0];assert length==72+n*80
            for t in range(n):
                sec=off+72+t*80
                name,seg,addr,sz,where=struct.unpack_from("<16s16sQQI",body,sec)
                if name.split(b"\0")[0]==b"__text" and seg.split(b"\0")[0]==b"__TEXT":
                    assert sz and where+sz<=len(body)
                    arrays.append([sz,sha(body[where:where+sz])])
        off+=length
    assert off==end+32 and len(arrays)==len(uuid)==1
    return {"size":len(body),"raw":sha(body),"text":arrays[0],"uuid":uuid[0],"ncmds":count}


def encoded(v):
    return (json.dumps(v,sort_keys=True,separators=(",",":"))+"\n").encode()

def sha(b):
    return hashlib.sha256(b).hexdigest()

class Raw:
    def __init__(self, path):
        self.zip=ZipFile(path)
        self.files={i.filename for i in self.zip.infolist() if not i.is_dir()}
        assert len(self.files)==sum(not i.is_dir() for i in self.zip.infolist()) and self.zip.testzip() is None
        self.digest=sha(Path(path).read_bytes())
        self.products={}
    def body(self,n):
        return self.zip.read(n)
    def obj(self,n):
        return json.loads(self.body(n))
    def unpack(self,n):
        return gzip.decompress(self.body(n))
    def streams(self,path,declared):
        names={"stdout":"stdout.gz","stderr":"stderr.gz","native_events":"exec.json.gz"}
        actual={k:self.unpack(path+"/"+names[k]) for k in declared}
        assert {k:sha(v) for k,v in actual.items()}==declared
        return actual

def kernel(z):
    obs=z.obj("observer.json")
    o,=[r for r in obs["rows"] if r["path"].endswith("/ld")]
    assert obs["exit"]==29 and sha(z.unpack("observer-probe/observed/output.macho.gz"))==obs["executable"]
    assert re.fullmatch("[0-9a-fA-F]{40}",o["cdhash"]) and o["argv"].count("-o")==1
    return {"path":o["path"],"cdhash":o["cdhash"],"sha":obs["ld"]}

def native(events,n,k):
    assert n["scope"]=="kernel-exec" and n["cargo"]==1
    cargo=[];compilers=[];linked=[];linkers=[];seq=[r["seq"] for r in events]
    assert seq==sorted(set(seq))
    for r in events:
        path=r["path"];name=PurePosixPath(path).name;args=r["argv"]
        if name=="cargo" and path.endswith("/native/bin/cargo"):cargo.append(r)
        if name=="rustc" and "--crate-name" in args:
            assert path.endswith("/native/bin/rustc")
            unit=args[args.index("--crate-name")+1]
            if unit=="___" and any(x=="--print" or x.startswith("--print=") for x in args):continue
            assert not any("ohm-branch-cache" in x or "incremental-branches" in x for x in args)
            (linked if any("link-only" in x for x in args) else compilers).append([unit,r["pid"],r["ppid"],r["cdhash"],sha(encoded(args))])
        if name in ("ld","ld64","ld-prime","ld-classic","rust-lld","ld64.lld","ld.lld","wild","wild-ld"):
            assert (path,r["cdhash"])==(k["path"],k["cdhash"]) and "-o" in args
            linkers.append((r["argv"],r["pid"],r["ppid"]))
    assert len(cargo)==1 and sorted(row[0] for row in compilers)==n["full"] and sorted(row[0] for row in linked)==n["link_only"]
    assert [v[0] for v in linkers]==[ld["argv"] for ld in n["linkers"]]
    assert all(ld["stock"] and ld["sha"]==k["sha"] for ld in n["linkers"])
    return {"full":sorted(n["full"]),"link_only":sorted(n["link_only"]),"ld":len(linkers),
            "cargo":[cargo[0]["pid"],cargo[0]["cdhash"]],"compiler_events":sorted(compilers+linked),
            "linker_events":[[pid,ppid,sha(encoded(a)),PurePosixPath(a[a.index("-o")+1]).name] for a,pid,ppid in linkers],
            "raw":sha(encoded(events))}

def check_suite(z,path,p,state,full):
    tests=p["tests"]
    assert sorted(set(tests))==tests and len(tests)==(53 if state=="old" else 54)
    assert ("nodes::tests::f_string_parts" in tests)==(state=="new") and "nodes::tests::size" in tests
    for name in ["size"]+(["f_string_parts"] if state=="new" else []):
        s=z.unpack(path+"/"+name+".gz");assert ("test nodes::tests::"+name+" ... ok").encode() in s and b"1 passed; 0 failed" in s
    if full:
        lines=z.unpack(path+"/test-list.gz").decode().splitlines();assert all(l.endswith(": test") for l in lines)
        assert sorted(l[:-6] for l in lines)==tests
        raw=z.unpack(path+"/test-suite.gz").decode().splitlines()
        assert z.obj(path+"/test-suite-exit.json")==0
        z.unpack(path+"/test-suite-stderr.gz")
        rows=[];annotated=set()
        for l in raw:
            if not l.startswith("test ") or " ... " not in l:continue
            label,result=l[5:].rsplit(" ... ",1)
            if label.endswith(" - should panic"):
                label=label[:-len(" - should panic")];annotated.add(label)
            assert result=="ok";rows.append([label,result])
        rows.sort()
        assert annotated==PANICS and rows==p["verdicts"] and [r[0] for r in rows]==tests
        assert any(l.startswith("test result: ok.") and f"{len(tests)} passed; 0 failed; 0 ignored" in l for l in raw)
    assert re.fullmatch(r"[0-9a-f]{64}",p["raw"]) and p["text"][0]>0 and re.fullmatch(r"[0-9a-f]{64}",p["text"][1])

def phase(z,path,role,k):
    v=z.obj(path+"/verified.json");s=z.streams(path,v["streams"]);assert v["cargo"]["streams"]==v["streams"]
    js=[json.loads(l) for l in s["stdout"].splitlines()];assert v["role"]==role and v["verb"]=="test"
    ok=v["state"]!="invalid"
    assert v["argv"]==["cargo","+ohm","test","--lib","--no-run","-p","ruff_python_ast","--locked","--offline","-j4","--message-format=json"]
    assert v["status"]==(0 if ok else 101) and js[-1]=={"reason":"build-finished","success":ok}
    arts=[q for q in js if q["reason"]=="compiler-artifact"]
    def key(q):return [q["package_id"], q["target"]["name"], ",".join(q["target"]["kind"]),q["features"],json.dumps(q["profile"],sort_keys=True,separators=(",",":"))]
    assert sorted(key(q) for q in arts)==v["roster"] and sorted(key(q) for q in arts if not q["fresh"])==v["dirty"]
    codes=[q["message"]["code"]["code"] for q in js if q["reason"]=="compiler-message" and q["message"].get("code")]
    assert codes==v["codes"]==([] if ok else ["E0425"])
    zm,=[q for q in arts if q["target"]["name"]=="zmij" and q["target"]["kind"]==["lib"]]
    assert zm["fresh"]==v["fresh_zmij"]
    dep=z.unpack(path+"/zmij.dep.gz");hard=b"ohm-untracked-relink-inputs" in dep;recheck=b"/dev/null/ohm-recheck-dependent-links" in dep
    assert v["marker"]=={"sha256":sha(dep),"hard":hard,"recheck":recheck} and b"zmij-1.0.10/src/lib.rs" in dep
    out={"status":v["status"],"codes":codes,"state":v["state"],"role":role,"argv":v["argv"],"typed":len(arts),
         "roster":sha(encoded(v["roster"])),"dirty":[q[1] for q in v["dirty"]],"dirty_identity":sha(encoded(v["dirty"])),
         "zmij":{"fresh":zm["fresh"],"hard":hard,"recheck":recheck,"dep":sha(dep)},"streams":v["streams"],"receipt":sha(z.body(path+"/verified.json"))}
    if v["native"] is not None:
        out["native"]=native(json.loads(s["native_events"]),v["native"],k)
    if "ns" in v["cargo"]:
        c=v["cargo"];t=z.body(path+"/time.txt")
        assert v["native"] is None and "native_events" not in s and c["ns"]==c["stop_ns"]-c["start_ns"]>0
        m=re.search(rb"([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys",t);assert m and tuple(map(float,m.groups()))==(c["wall"],c["user"],c["system"])
        out["clock"]={key:c[key] for key in ("ns","start_ns","stop_ns","wall","user","system")}
        retired=re.search(rb"(?m)^\s*(\d+) instructions retired\s*$",t)
        assert (int(retired[1]) if retired else None)==c.get("instructions")
        if retired:out["clock"]["instructions"]=int(retired[1])
        out["clock"]["raw"]=sha(t)
    if ok:
        target,=[q for q in arts if q["target"]["name"]=="ruff_python_ast" and q["executable"]]
        assert target["profile"]["test"]
        product=v["product"];check_suite(z,path,product,v["state"],True)
        h=sha(encoded(product));z.products[h]=product;out["product"]=h
    else:
        assert v["product"] is None and b"ohm_test_build_missing_28335" in s["stdout"]
    return out

def providers(z,k):
    ans={}
    for terminal in sorted(s for s in z.files if s.startswith("native-input/") and s.endswith("/terminal.json")):
        folder=terminal[:-len("/terminal.json")];garden={}
        for name,v in z.obj(terminal).items():
            p=folder+"/"+name;assert v==z.obj(p+"/verified.json")
            streams=z.streams(p,v["streams"]["streams"]);samples=[json.loads(l) for l in streams["stdout"].splitlines()]
            assert samples[-1]=={"reason":"build-finished","success":v["cargo_exit"]==0}
            if v["cargo_exit"]:
                assert b"qa_answer" in streams["stdout"]+streams["stderr"]
            n=native(json.loads(streams["native_events"]),v["native"],k)
            garden[name]={x:v.get(x) for x in ("archive","cargo_exit","executable","value")}
            garden[name].update(full=n["full"],ld=n["ld"],streams=v["streams"]["streams"],kernel=n)
        ans[folder.rsplit("/",1)[1]]=garden
    return ans

def authenticated_image(z,path,observer):
    v=z.obj(path+"/verified.json")
    cargo=[json.loads(l) for l in z.unpack(path+"/stdout.gz").splitlines()]
    exe,=[a["executable"] for a in cargo if a.get("executable") and a["target"]["name"]=="ruff_python_ast" and a["profile"]["test"]]
    events=json.loads(z.unpack(path+"/exec.json.gz"))
    linked,=[r for r in events if (r["path"],r["cdhash"])==(observer["path"],observer["cdhash"])
             and [r["argv"][i+1] for i,a in enumerate(r["argv"]) if a=="-o"]==[exe]]
    original=z.unpack("test-executables/"+v["product"]["raw"]+".macho.gz")
    assert sha(original)==v["product"]["raw"]
    canonical,members=audit(original,linked["argv"],exe)
    return original,canonical,members

def compare_clean(z, root, state, observer):
    arms={r:authenticated_image(z,root+"/"+r+"/empty-"+state+"/clean",observer) for r in "PC"}
    a,ca,ma=arms["P"];b,cb,mb=arms["C"]
    assert ca==cb and ma["layout"]==mb["layout"] and ma["slots"]==mb["slots"]
    assert [(n[0],n[2]) for n in ma["names"]]==[(n[0],n[2]) for n in mb["names"]]
    changes={i for i,(x,y) in enumerate(zip(a,b)) if x!=y};locations={i for l,h in ma["slots"] for i in range(l,h)}
    pages,pagesize,limit,offset=ma["layout"]["page"];changed_pages={i//pagesize for i in changes&locations}
    allowed={i for p in changed_pages for i in range(offset+p*32,offset+(p+1)*32)}
    assert changes<=allowed|locations
    record=z.obj(root+"/verified.json")["cross_compiler"][state]
    assert record["canonical_sha256"]==sha(ca) and record["raw_difference_bytes"]==len(changes)
    by_role={}
    for role,(body,_,members) in arms.items():
        real=record[role]
        assert real["raw"]==sha(body) and real["code_pages"]==pages and real["key"]==members["names"][0][1] and len(real["paths"])==len(members["slots"])
        by_role[role]={"raw":real["raw"],"namespace":real["key"]}
    return {"same_after_verified_paths_and_pages":sha(ca),"roles":by_role,"different_total":len(changes),
            "different_N_OSO":len(changes&locations),"different_signature":len(changes&allowed),
            "path_count":len(ma["slots"]),"archive_members":ma["archive_members"],"code_pages":pages,
            "changed_pages":sorted(changed_pages),"workspace":ma["names"][0][0]}


def physical_calibration(z, cal):
    from statistics import median
    assert cal["source"] == sha(z.body("calibration/burn.c"))
    assert cal["toy"] == sha(z.body("calibration/burn"))
    assert cal["host"]["machine"] == "arm64"
    iters = 200_000_000
    assert cal["expected_delta"] == 2 * iters
    samples = {}
    for row in cal["rows"]:
        ident = row["rep"], row["depth"], row["iters"]
        raw = z.body("calibration/time-{rep}-{depth}-{iters}.txt".format(**row))
        assert ident not in samples and sha(raw) == row["time_raw"]
        time = re.search(rb"([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys", raw)
        assert time and list(map(float,time.groups())) == [row[k] for k in ("wall","user","system")]
        counter = re.search(rb"(?m)^\s*(\d+) instructions retired\s*$", raw)
        n = int(counter[1]) if counter else None
        assert n == row.get("instructions")
        samples[ident] = [row["user"], n]
    assert set(samples)=={(r,d,i) for r in range(3) for d in range(3) for i in (0,iters)}
    def delta(d, idx):
        heavy = [samples[r,d,iters][idx] for r in range(3)]
        zero = [samples[r,d,0][idx] for r in range(3)]
        return None if None in heavy + zero else median(heavy) - median(zero)
    cpu = {str(d):delta(d,0) for d in range(3)}
    retired = {str(d):delta(d,1) for d in range(3)}
    calibrated = cpu["0"] >= .01 and min(cpu.values()) >= .45 * cpu["0"]
    plausible = lambda v: v is not None and .9*iters*2 <= v <= 1.1*iters*2
    child_interior = all(v is not None and abs(v)<=.05*iters*2 for k,v in retired.items() if k!="0")
    scope=("whole-tree-calibrated" if all(map(plausible,retired.values())) else
           "direct-process-only" if plausible(retired["0"]) and child_interior else "unavailable-or-inconclusive")
    assert (retired,cpu,scope,calibrated) == (cal["retired_deltas"],cal["user_seconds_deltas"],cal["retired_instruction_scope"],cal["tree_CPU_calibrated"])
    return {"retired_deltas":retired,"user_seconds_deltas":cpu,"tree_CPU_calibrated":calibrated,
            "retired_instruction_scope":scope,"host":cal["host"],"toy_assembly_source":cal["source"],
            "timing_streams":[r["time_raw"] for r in cal["rows"]],"burn_executable":cal["toy"]}


def project(path):
    z=Raw(path);k=kernel(z);pair=z.obj("pair.json");roles=pair["products"]
    assert set(roles)=={"P","C"} and [roles[r]["source"] for r in "PC"]==[PARENT,CHILD]
    assert all(roles["P"][n]==roles["C"][n] for n in ("stage0_cargo","stage0_rustc","build_argv","rustc","library_tree","source_stamp_input"))
    assert roles["P"]["runtime"].keys()==roles["C"]["runtime"].keys()
    diff,=[name for name in roles["P"]["runtime"] if roles["P"]["runtime"][name]!=roles["C"]["runtime"][name]]
    assert pair["differ"]==[diff] and diff.startswith("lib/librustc_driver")
    for r in "PC":
        assert roles[r]==z.obj("bootstrap-"+r+"-product.json") and roles[r]["build_log"]==sha(z.body("bootstrap-"+r+".log"))
    rel=z.obj("release.json");ruff=z.obj("ruff.json");trans=z.obj("public-source-transport.json");cal=z.obj("calibration/result.json")
    assert rel["archive"]=="7cd292583785c25a315f67bf85c8f028a15ccb0be5461ac39ce6e46720807bb8"
    assert all(v in rel[k] for k,v in (("cargo_version","2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"),("rustc_version","7e71d3150938ff8ed82aca03416439d7e5b87ef3")))
    assert rel["packed_cargo"]["sha256"]==rel["cargo"]["sha256"]=="505008003127f597cf2bdbd967d2bac9158d706b55a18f8bf17790e9ea3bbac9"
    assert z.obj("run-make.json")=={"source":CHILD,"log":sha(z.body("run-make.log"))}
    assert (trans["parent"],trans["candidate"])==(PARENT,CHILD) and trans["public_base"]=="b940084d7eb6a299eb4bfeb8e34901bc051e7ac4"
    assert [roles[r]["tree"] for r in "PC"]==["df84b98ba4deb07dd6f25446632704a1302c23a3","f08c7d8e65d8d06ae7da0d81dafb25cc68124567"]
    assert len(roles["P"]["runtime"])==2466 and roles["P"]["runtime"]["bin/cargo"]==rel["cargo"]["sha256"]
    assert [ruff["old"],ruff["new"]]==SOURCE and ruff["lock"]=="839edc8250480bb523619b8d24bd57176a6e1f57c152cca85c5adc61ea5f94eb"
    assert z.obj("accepted-verbs-pilot.json")=={"run":41051991519,"head":"8fb888395d94179bf969f60e5667df473b16b17c","archive":SIGNED_ZIP,"eligible":["test"],"check_repeat_compilers":0}
    counter=physical_calibration(z,cal)
    out={"qa":QA,"run":RUN,"raw_sha256":z.digest,"files":len(z.files),"source":{"roles":[PARENT,CHILD],"trees":[roles[r]["tree"] for r in "PC"],"ruff":SOURCE,"ruff_trees":[ruff[n] for n in ("old_tree","new_tree")],"lock":ruff["lock"],"archives":len(ruff["archives"]),"archive_manifest":sha(encoded(ruff["archives"])),"build_recipe":sha(encoded(roles["P"]["build_argv"])),"source_stamp":roles["P"]["source_stamp_input"]},
         "sdk":{"members":len(roles["P"]["runtime"]),"driver_file":diff,"drivers":{r:roles[r]["runtime"][diff] for r in "PC"},"release":rel["archive"],"cargo":rel["cargo"]["sha256"],
                "stage0":{n:roles["P"][n]["sha256"] for n in ("stage0_rustc","stage0_cargo")},"transport_receipt":sha(encoded(trans)),"run_make":z.obj("run-make.json")},
         "kernel":{"cdhash":k["cdhash"],"apple_ld_sha256":k["sha"]},"counter":counter,
         "providers":providers(z,k),"modes":{}}
    preflight=z.obj("reopened-native-programs.json")
    assert preflight["negative_controls"]==4 and preflight["timed_pairs"]==0
    assert preflight["raw_sha256"]=="777a63bd3105370057ec66646b785b4b0e43926e2f17a4ade6d12f39ce5d44bf"
    out["mach_o_preflight"]={"tamper_controls":4,"old_artifact":preflight["raw_sha256"],"receipt":sha(z.body("reopened-native-programs.json"))}
    proc={}
    for role in "SPC":
        root="proc-macro/"+role+"/"
        v=z.obj(root+"verified.json")
        assert v["rustc"]["sha256"]==(rel["rustc"]["sha256"] if role=="S" else roles[role]["runtime"]["bin/rustc"])
        for phase_name in ("producer","consumer","run"):
            where=root+phase_name
            command=z.obj(where+"/command.json")
            material=z.streams(where,command["streams"])
            assert command["exit"]==0
            if phase_name=="run":assert material["stdout"]==b"3\n" and command["argv"]==["./reader"]
            else:assert command["argv"][:2]==["rustc","+ohm"]
        proc[role]={"source":sha(encoded(v["sources"])),"metadata":v["members"],"outputs":v["outputs"],
                    "rustc":v["rustc"]["sha256"],"stdout":sha(material["stdout"])}
    out["proc_macro_loader"]=proc
    for mode in ORDERS:
        start="test-"+mode+"/"
        if start+"result.json" not in z.files:continue
        reg=z.obj(start+"registered.json");res=z.obj(start+"result.json")
        assert reg["compilers"]==[PARENT,CHILD] and [reg["old"],reg["new"]]==SOURCE and reg["order"]==ORDERS[mode] and reg["pilot_sha"]==SIGNED_ZIP
        assert len(reg["harness"])==22 and sha(encoded(reg["harness"]))==HARNESS_SHA
        assert res["registration"]==sha(z.body(start+"registered.json")) and reg["harness"]==res["harness"]
        dirs=sorted(s[:-len("/verified.json")] for s in z.files if s.startswith(start) and s.endswith("/verified.json") and "dyld" not in s and s.count("/")>=4)
        rows={}
        for dirname in dirs:
            relpath=dirname[len(start):];parts=relpath.split("/");role=parts[1]
            if role not in "PC" or len(role)!=1:continue
            rows[relpath]=phase(z,dirname,role,k)
        dyld={}
        for flank in ("native-before","native-after"):
            for r in "PC":
                d=start+flank+"/"+r+"/dyld/";v=z.obj(d+"verified.json")
                assert v["loaded"][diff]["sha256"]==roles[r]["runtime"][diff] and v["role"]==r and v["object"]==sha(z.body(d+"test.o"))
                dyld[flank+"/"+r]=v["loaded"][diff]["sha256"]
        cross={f+"/"+state:compare_clean(z,start+f,state,k) for f in ("native-before","native-after") for state in ("old","new")}
        installations={}
        for index in range(1,len(reg["order"])+1):
            for role in "PC":
                case=f"pair-{index:02}/{role}"
                sel=z.obj(start+case+"/selected-driver.json")
                assert sel["role"]==role and sel["image"]["sha256"]==roles[role]["runtime"][diff] and sel["ctime_ns"]>0
                entry={"selected":{"role":role,"image_sha":sel["image"]["sha256"],"dev":sel["image"]["dev"],"ino":sel["image"]["ino"],"ctime_ns":sel["ctime_ns"]},"states":{}}
                for state,labels in (("old",["cold"]),("new",list(ENDPOINTS))):
                    filepath=start+case+"/reference/empty-"+state
                    assert z.obj(filepath+"/selected-driver.json")==sel
                    verification=z.obj(filepath+"/checked.json")
                    assert verification["driver"]==sel and verification["compared"]==labels
                    raw,canonical,mem=authenticated_image(z,filepath+"/clean",k)
                    record=verification["proof"]
                    assert sha(canonical)==verification["canonical_sha256"]==cross["native-before/"+state]["same_after_verified_paths_and_pages"]
                    assert record["raw"]==sha(raw) and record["code_pages"]==mem["layout"]["page"][0] and len(record["paths"])==len(mem["slots"])
                    anchor=z.obj(start+"native-before/verified.json")["cross_compiler"][state][role]
                    assert record["paths"]==anchor["paths"] and record["base"]==anchor["base"]
                    for label in labels:
                        cold=rows[case+"/reference/empty-"+state+"/clean"]
                        assert cold["product"]==rows[case+"/"+label]["product"]
                    entry["states"][state]={"raw":sha(raw),"canonical":sha(canonical),"paths":len(mem["slots"]),"page_count":record["code_pages"],
                                             "namespace":record["key"],"compared":labels,"archive_members":mem["archive_members"],"checked":sha(z.body(filepath+"/checked.json"))}
                installations[case]=entry
        assert ("instructions" in res)==(counter["retired_instruction_scope"]=="whole-tree-calibrated")
        assert ("cpu_seconds" in res)==counter["tree_CPU_calibrated"]
        out["modes"][mode]={"installations":installations,"cross":cross,"orders":reg["order"],"registered":res["registration"],"harness_sha":HARNESS_SHA,"rows":rows,"dyld":dyld,"reported":res["wall"],"accepted":res["accept"]}
    out["products"]=z.products
    images={}
    for source in sorted(n for n in z.files if n.startswith("test-executables/") and n.endswith(".macho.gz")):
        body=z.unpack(source);image=mach_image(body)
        assert source=="test-executables/"+image["raw"]+".macho.gz"
        images[image["raw"]]={**image,"gzip":sha(z.body(source))}
    assert {p["raw"] for p in out["products"].values()}==set(images)
    for p in out["products"].values():assert p["text"]==images[p["raw"]]["text"]
    out["archived_executables"]=images
    return out
