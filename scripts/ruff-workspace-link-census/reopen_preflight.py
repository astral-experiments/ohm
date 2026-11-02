"""Reopen every calibration, measured Wild invocation, input change and native ELF from the QA ZIP."""
from collections import Counter
from pathlib import Path
import hashlib
import itertools
import json
import re
import statistics
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import raw_args,traced

STOCK="0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
CARGO="3e6948caba617c5f776641df2ade87fe772d0b656a53b538cd93b63351c56c53"
ORDER=(("stock","off","active"),("off","active","stock"),("active","stock","off"),("active","off","stock"),("off","stock","active"),("stock","active","off"))


def check(path,digest):
    with path.open("rb") as inp:assert hashlib.file_digest(inp,"sha256").hexdigest()==digest
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        allfiles=set(z.namelist());assert len(allfiles)==len(z.namelist()) and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in allfiles)
        base=next(n for n in allfiles if n.endswith("/preflight/study.json") or n=="preflight/study.json").removesuffix("study.json")
        def raw(n):return z.read(base+n)
        def rd(n):return json.loads(raw(n))
        def count(folder):
            parent=base+folder+"/"
            if parent+"counter.json" in allfiles:
                r=rd(folder+"/counter.json");assert r["status"]==0 and 0<r["instructions"] and 0.99*r["enabled"]<=r["running"]<=r["enabled"] and r["running"]>0
                return r["instructions"]
            profiles=[n for n in allfiles if n.startswith(parent) and re.fullmatch(r"callgrind\.\d+",n[len(parent):])]
            assert 1<=len(profiles)<=2 and (len(profiles)==1 or folder=="calibration/fork")
            total=0
            for name in profiles:
                s=z.read(name).decode();names=re.search(r"^events: (.+)$",s,re.M)[1].split()
                m=re.search(r"^totals: ([0-9 ]+)$",s,re.M) or re.search(r"^summary: ([0-9 ]+)$",s,re.M);assert m
                total+=int(m[1].split()[names.index("Ir")])
            assert total>0;return total
        study=rd("study.json");build=rd("build.json");cal=rd("calibration/verified.json");fs=rd("final-binding.json")
        assert study["stock"]==build["official_wild"]==STOCK and study["matched"]==build["matched_wild"] and study["cargo"][1]==CARGO and fs["original_source_status"]==""
        assert len(fs["before"])==len(fs["after"])==79 and all(fs["before"][k][:6]==fs["after"][k][:6] for k in fs["before"])
        assert tuple(map(tuple,study["schedule"]))==ORDER and set(ORDER)==set(itertools.permutations(("stock","off","active")))
        cs={x:count("calibration/"+x) for x in ("empty","loop","thread","fork")}
        assert cs==cal["measured"] and study["counter"]==cal["counter"] and all(3_800_000<=n-cs["empty"]<=4_400_000 for k,n in cs.items() if k!="empty")
        rows={};bodies={};cost=[]
        for key,r in study["rows"].items():
            assert rd(key+"/verified.json")==r
            native=not ("-count" in key or key.startswith(("cost-","meter-train-")))
            inner=key+"/native/" if native else key+"/"
            stream=[json.loads(s) for s in raw(inner+"stdout.jsonl").splitlines()]
            assert stream[-1]=={"reason":"build-finished","success":r["exit"]==0}
            arts=[x for x in stream if x["reason"]=="compiler-artifact"]
            assert r["typed"]==len(arts) and r["dirty"]==[x["target"]["name"] for x in arts if not x["fresh"]]
            view=rd(key+"/view.json");assert view["uid"]!=0 and "overlay" in view["gcc"] and "ro," in view["gcc"]
            if not r["selection"]:
                assert native and key in ("missing-empty","malformed-empty") and r["exit"]==101 and r["actual_link_requests"]==0
                assert not any(n.startswith(base+key+"/link-selection") for n in allfiles)
                trace=traced(z,base,key+"/native")
                assert trace["links"] and all(l["rustc"]=="build_script_build" and not l["link_only"] for l in trace["links"])
                err="\n".join(a["message"].get("rendered","") for a in stream if a["reason"]=="compiler-message" and a["message"]["level"]=="error")
                assert "wild: error: Failed to process" in err and "/libutil.so" in err and ("/objects/active.o" in err)==(key=="missing-empty")
                rows[key]={"subject":"stock","exit":101,"tag":None,"elf":None,"link_only":False,"events":{},"physical_links":0,"earlier_stock_build_script_linkers":len(trace["links"])}
                continue
            selection=rd(key+"/link-selection.json")
            physical=[json.loads(z.read(n)) for n in allfiles if re.fullmatch(re.escape(base+key+"/")+r'link-selection\.\d+\.json',n)]
            assert r["actual_link_requests"]==len(physical) and selection==max(physical,key=lambda p:p["observed_ns"])
            if len(physical)>1:assert (key=="cold" or "empty" in key) and all(p["mode"]=="stock" and not p["owning_rustc_is_link_only"] for p in physical)
            argv=selection["args"];out=selection["output"];role=selection["mode"].split("-")[0]
            assert argv[argv.index("-o")+1]==out and Path(out).name.startswith("constructors-") and selection["uid"]==view["uid"] and selection["symbols_bytes"]>0
            assert selection["symbols_file"] in argv and len(selection["symbols_sha256"])==64
            assert selection["subject"].endswith("/"+("stock-wild" if role=="stock" else "matched-wild"))
            parent=[v for v in selection["ancestry"] if v["path"].endswith("/rustup/toolchains/ohm/bin/rustc")];front,=parent
            assert front["args"][front["args"].index("--crate-name")+1]=="constructors" and any(v["path"].endswith("/rustup/toolchains/ohm/bin/cargo") for v in selection["ancestry"])
            is_link_only=any(a in ("-Zlink-only","link-only") or a.startswith(("-Zlink-only=","link-only=")) for a in front["args"])
            assert is_link_only==selection["owning_rustc_is_link_only"]
            event_counts=Counter()
            if base+key+"/events" in allfiles:
                for line in raw(key+"/events").decode().splitlines():
                    pid,name=line.split();assert pid.isdigit();event_counts[name]+=1
            assert event_counts==r["events"] and event_counts.get("hit",0)<=1
            tag=None;elf=None
            if r["exit"]==0:
                native_stdout=raw(inner+"native.stdout");assert r["native"]==native_stdout.decode() and b"test main ... ok" in native_stdout and b"1 passed; 0 failed" in native_stdout
                vals=re.findall(rb'^chosen-gnu-provider-(\d+)$',native_stdout,re.M);assert len(vals)<=1;tag=int(vals[0]) if vals else 0
                elf=r["elf"]
                if elf not in bodies:
                    blob=raw("native-bodies/"+elf);assert blob[:4]==b"\x7fELF" and hashlib.sha256(blob).hexdigest()==elf;bodies[elf]=len(blob)
            else:
                assert r["exit"]==101 and any(x["reason"]=="compiler-message" and "linking with" in (x["message"].get("rendered") or "") for x in stream)
            if native:
                trace=traced(z,base,key+"/native")
                kernel={v["pid"]:v for v in trace["links"] if v["output"]==out}
                assert set(kernel)=={p["dispatch_pid"] for p in physical}
                for p in physical:
                    rootlink=kernel[p["dispatch_pid"]]
                    assert rootlink["rustc_pid"] in [v["pid"] for v in p["ancestry"] if v["path"].endswith("/rustc")] and rootlink["link_only"]==p["owning_rustc_is_link_only"]
                    lines=z.read(base+inner+"exec."+str(rootlink["pid"])).decode(errors="replace").splitlines()
                    subjects=[q for l in lines if (q:=raw_args(l)) and q[0]==p["subject"]];assert len(subjects)==1 and subjects[0][1][1:]==p["args"][1:]
            else:
                assert len(physical)==1 and is_link_only and tag==0 and len(arts)==53 and r["dirty"]==["constructors"] and elf==study["references"]["0"] and r["instructions"]==count(key)
            rows[key]={"subject":role,"exit":r["exit"],"tag":tag,"elf":elf,"link_only":is_link_only,"events":dict(event_counts),"physical_links":len(physical)}
            if key.startswith("cost-"):rows[key]["instructions"]=r["instructions"]
        for i,perm in enumerate(ORDER,1):
            one={role:rows[f"cost-{i:02d}-{role}"]["instructions"] for role in perm};cost.append(one)
        for k,value in [("cold",0),("empty-29",29),("empty-41",41),("restored-fully-empty",0),("shadow-29",29),("repair-41",41),("system-restored",0)]:
            assert rows[k]["tag"]==value and rows[k]["elf"]==study["references"][str(value)]
        for k in ("malformed","missing"):
            assert all(rows[n]["exit"]==101 for n in (k,k+"-empty"))
        alias={};mut={}
        for role in ("stock","active"):
            cr=rd(role+"-corruption.json");assert cr["before"][:8]==cr["changed"][:8] and cr["digest_corrupt"]!=study["references"]["0"]
            original=bytearray(raw("native-bodies/"+study["references"]["0"]));assert original[cr["offset"]]==cr["byte_original"];original[cr["offset"]]=cr["byte_corrupt"]
            assert hashlib.sha256(original).hexdigest()==cr["digest_corrupt"]
            assert rows[role+"-corrupt-output"]["elf"]==study["references"]["0"] and not rows[role+"-corrupt-output"]["events"].get("hit")
            for shape in ("hardlink","symlink"):
                a=rd(role+"-"+shape+".json");rec=rows[role+"-"+shape+"-output"];assert rec["elf"]==a["output_final"]==study["references"]["0"]
                alias[role+"-"+shape]={"entry_same_inode":a["before"][0][:2]==a["before"][1][:2],"exit_same_inode":a["after"][0][:2]==a["after"][1][:2],"seen_by_wild":rd(role+"-"+shape+"-output/link-selection.json")["output_before"],"hit":rec["events"].get("hit",0)}
        for role,cut in [("off","full-layout"),("active","receipt-hit")]:
            rec=rows[role+"-race"];f=role+"-race/mutation.json"
            if base+f not in allfiles:
                assert not rec["events"].get("hit");mut[role]={"bypass":True};continue
            m=rd(f);old=raw("real-hook-source/hook29.o");new=raw("real-hook-source/hook41.o")
            assert m["old"]==hashlib.sha256(old).hexdigest() and m["new"]==hashlib.sha256(new).hexdigest() and m["offsets"]==[i for i,(a,b) in enumerate(zip(old,new,strict=True)) if a!=b]
            assert m["all_stat_fields_equal"]==(m["before"]==m["after"]) and m["cut"]==(cut if role=="off" or rec["events"].get("hit") else "full-layout")
            assert rows[role+"-race-current-stock"]["elf"]==study["references"]["41"] and rec["elf"]==study["references"][str(rec["tag"])]
            mut[role]={**m,"tag":rec["tag"],"elf":rec["elf"],"current_stock":rows[role+"-race-current-stock"]["tag"]}
        ratios={r:[a[r]/a["active"] for a in cost] for r in ("stock","off")}
        return {"archive_sha256":digest,"ruff":study["source"],"cargo":study["cargo"],"wild_source":build["upstream"],"matched_wild":study["matched"],"signed_wild":STOCK,"counter":cal,"rows":rows,"body_sizes":bodies,"receipt_bytes":sum(r[1] for r in study["witness_files"]),"paired_instructions":cost,"paired_ratio":ratios,"median_ratio":{r:statistics.median(v) for r,v in ratios.items()},"active_hits":sum(rows[f"cost-{i:02d}-active"]["events"].get("hit",0) for i in range(1,7)),"output_aliases":alias,"input_race":mut}


if __name__=="__main__":print(json.dumps(check(Path(sys.argv[1]),sys.argv[2]),indent=2,sort_keys=True))
