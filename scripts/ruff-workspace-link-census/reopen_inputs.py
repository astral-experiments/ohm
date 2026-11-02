"""Independently rejoin the genuine constructors outcomes to their Linux process and file traces."""
from pathlib import Path
from collections import Counter
import ast
import hashlib
import json
import re
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reopen import traced

CASES={"shadow":29,"malformed":None,"nested-missing":None,"repair":41,"restored":0}
LIBS={"lib"+name+suffix for name in ("gcc_s","util","rt","pthread","m","dl","c") for suffix in (".so",".a")}


def check(path,digest):
    with path.open("rb") as inp:assert hashlib.file_digest(inp,"sha256").hexdigest()==digest
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        names=z.namelist();assert len(names)==len(set(names)) and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
        base=next(n for n in names if n.endswith("constructors-inputs-complete.json")).removesuffix("constructors-inputs-complete.json")
        def rd(n):return json.loads(z.read(base+n))
        route=rd("constructors-input-route.json");terminal=rd("constructors-inputs-complete.json");meta=rd("identity.json")
        visible=route["visible"];assert terminal["route"]==route["kind"]=="system-overlay" and route["gate"]["exit"]==0 and visible==route["gccdir"]+"/libutil.so"
        assert meta["ruff"]==terminal["source"] and meta["lock"]==terminal["lock"] and len(meta["sdk"])==79
        measures={};history={}
        for role in ("parent","child"):
            assert len(rd(role+"/registry.json"))==498
            phases=["cold","ordinary","audit-absent","independent-train"]+[v for case in CASES for v in ([case,case+"-empty",case+"-target-forced"] if CASES[case] is None else [case,case+"-empty"])]
            assert len(phases)==16
            for ph in phases:
                root=role+"/"+ph;cmd=rd(root+"/command.json");rec=rd(root+"/result.json")
                assert cmd["argv"]==["cargo","+ohm","test","-p","ruff_text_size","--test","constructors","--features","get-size,schemars,serde","--no-run","--locked","--offline","-j8","--message-format=json"]
                typed=[json.loads(l) for l in z.read(base+root+"/stdout.jsonl").splitlines()]
                assert typed[-1]=={"reason":"build-finished","success":cmd["exit"]==0}
                arts=[r for r in typed if r["reason"]=="compiler-artifact"];assert rec["typed"]==len(arts) and rec["dirty"]==[r["target"]["name"] for r in arts if not r["fresh"]]
                view=rd(root+"-view.json");assert view["uid"]==view["effective_uid"]>0 and view["mnt"]!=route["namespace"] and ' overlay overlay ro,' in view["gccdir_mount"]
                native=traced(z,base,root);act=[(r[1],r[2]) for r in native["owners"].values()]
                assert Counter(act)==Counter(tuple(v) for v in rec["rustc"]) and len(native["links"])==rec["wild"]
                value=None
                if cmd["exit"]==0:
                    out=z.read(base+root+"/native.stdout");assert out.decode()==rec["native"] and b"test main ... ok" in out and b"1 passed; 0 failed" in out
                    tags=re.findall(rb'^chosen-gnu-provider-(\d+)$',out,re.M);assert len(tags)<=1
                    value=int(tags[0]) if tags else 0
                else:
                    assert cmd["exit"]==101 and any(m["reason"]=="compiler-message" and ("linking with" in (m["message"].get("rendered") or "")) for m in typed)
                if ph.endswith("-target-forced"):
                    assert any(c=="constructors" and not lo for c,lo in act) and len(native["links"])==1 and cmd["exit"]==101
                if ph in CASES or ph in ("audit-absent","ordinary"):
                    assert (act,rec["wild"])==(([("constructors",ph not in ("nested-missing","repair"))],1) if role=="child" else ([],0)),(role,ph,act)
                case=ph.removesuffix("-empty").removesuffix("-target-forced")
                wanted=CASES[case] if case in CASES and (role=="child" or case!=ph) else 0
                assert (cmd["exit"],value)==((101,None) if wanted is None else (0,wanted)),(role,ph,value)
                history[root]={"exit":cmd["exit"],"tag":value,"elf":rec.get("elf"),"rustc":len(act),"wild":rec["wild"],"full_constructors":("constructors",False) in act}
                if role=="child" and ph in ("audit-absent","shadow","malformed","nested-missing"):
                    read=rd(root+"/wild-files.json");assert read["wild_pid"]==native["links"][0]["pid"]
                    lookup=set();raw_read=set();nonregular_failures=Counter()
                    for pid in read["threads"]:
                        for s in z.read(base+root+"/exec."+str(pid)).decode(errors="replace").splitlines():
                            x=re.search(r'"((?:[^"\\]|\\.)*)"',s)
                            if x is None:continue
                            n=ast.literal_eval('"'+x[1]+'"')
                            if not n.startswith("/"):continue
                            if s.startswith(("open(","openat(","openat2(")) and "O_RDONLY" in s and re.search(r'= \d+<',s):
                                raw_read.add(n)
                            if Path(n).name in LIBS and re.search(r'= -1 ENOENT \(',s):lookup.add(n)
                    assert raw_read==set(read["read_opens"])
                    actual={n for n,errs in read["even_failing_probes"].items() if Path(n).name in LIBS and "ENOENT" in errs}
                    assert actual==lookup and (visible in raw_read)==(ph!="audit-absent") and (visible in lookup)==(ph=="audit-absent")
                    if ph in ("shadow","nested-missing"):
                        obj=next(n for n in raw_read|set(read["even_failing_probes"]) if n.endswith("/objects/active.o"))
                        assert (obj in raw_read)==(ph=="shadow") and (obj in read["even_failing_probes"] and "ENOENT" in read["even_failing_probes"][obj])==(ph=="nested-missing")
                    stats=read["read_opens"];regs={tuple(v[:2]):v for n,v in stats.items() if v and (v[2]&0o170000)==0o100000 and not n.startswith(("/proc/","/sys/","/dev/"))}
                    assert len(regs)==read["distinct_postlink_regular_inodes"] and sum(v[5] for v in regs.values())==read["postlink_regular_bytes"]
                    measures[ph]={"wild_tasks":len(read["threads"]),"read_open_paths":len(raw_read),"regular_inodes":len(regs),"regular_bytes":read["postlink_regular_bytes"],"root_owned_regular":sum(v[3]==0 for v in regs.values()),"root_owned_bytes":sum(v[5] for v in regs.values() if v[3]==0),"failed_native_ENOENT":len(lookup),"ordered_util_events":[s for _,s in read["native_lookup_syscalls"] if "libutil." in s or "/objects/active.o" in s],"mapped_symbols_bytes":[l for n,l in read["mmap_lengths_by_fd_name"].items() if n.endswith("/symbols.o")],"hot_rows":read["hot_observation_only"]}
                    for obs in read["hot_observation_only"]:
                        assert obs["hashed_files"]==len(regs) and obs["hashed_bytes"]==sum(v[5] for v in regs.values()) and obs["negatives_still_absent"]==len(lookup)
            for case,val in CASES.items():
                if val is not None and role=="child":
                    assert history[role+"/"+case]["elf"]==history[role+"/"+case+"-empty"]["elf"]
            stamps=rd(role+"/restamp.json");assert stamps["before"][:8]==stamps["after"][:8]
        return {"source":meta["ruff"],"lock":meta["lock"],"run":meta["run"],"qa":meta["sha"],"archive":digest,"route":route,"commands":history,"current_Wild_files":measures}

if __name__=="__main__":print(json.dumps(check(Path(sys.argv[1]),sys.argv[2]),indent=2,sort_keys=True))
