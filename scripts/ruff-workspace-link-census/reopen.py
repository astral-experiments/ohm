"""Reopen both recorded Cargo streams, real process genealogies and native ELF section tables."""
import ast
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

PHASES=("cold","ordinary","traced","fingerprint")


def raw_args(line):
    if not line.endswith(" = 0"):
        return
    m=re.match(r'^(?:execve\(|execveat\([^,]+, )"([^"\\]+)", (\[)',line)
    if not m:
        return
    start=m.start(2)
    quote=False
    escaped=False
    for i in range(start+1,len(line)):
        ch=line[i]
        if escaped:
            escaped=False
        elif ch=="\\" and quote:
            escaped=True
        elif ch=='"':
            quote=not quote
        elif ch==']' and not quote:
            return m[1],ast.literal_eval(line[start:i+1])
    raise AssertionError("unclosed exec argument vector")


def traced(z,prefix,trace_dir="traced"):
    processes={}
    parents={}
    image_execs=0
    for name in z.namelist():
        if not re.fullmatch(re.escape(prefix+trace_dir+"/")+r'exec\.\d+',name):
            continue
        pid=int(name.rsplit(".",1)[1])
        lines=z.read(name).decode(errors="replace").splitlines()
        for line in lines:
            child=re.match(r'(?:(?:clone3?|vfork|fork)\(|<\.\.\. (?:clone3?|fork|vfork) resumed>).*?= (\d+)$',line)
            if child:
                cp=int(child[1]);assert parents.get(cp,pid)==pid;parents[cp]=pid
            args=raw_args(line)
            if not args:continue
            image_execs+=1
            exe,argv=args
            key=hashlib.sha256(line.encode()).hexdigest()
            if exe.endswith("/rustup/toolchains/ohm/bin/rustc") and "--crate-name" in argv:
                val=argv[argv.index("--crate-name")+1]
                mode=any(x in ("link-only","-Zlink-only") or x.startswith(("-Zlink-only=","link-only=")) for x in argv)
                processes.setdefault(pid,[]).append(["rustc",val,mode,key])
            if exe.endswith("/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"):
                assert argv.count("-o")==1
                processes.setdefault(pid,[]).append(["wild",argv[argv.index("-o")+1],key])
    owners={pid:r for pid,items in processes.items() for r in items if r[0]=="rustc"}
    links=[]
    for pid,items in processes.items():
        for row in items:
            if row[0]!="wild":continue
            probe=pid;seen=set()
            while probe not in owners:
                assert probe in parents and probe not in seen
                seen.add(probe);probe=parents[probe]
            links.append({"pid":pid,"rustc_pid":probe,"rustc":owners[probe][1],"link_only":owners[probe][2],"output":row[1],"exec_sha256":row[2]})
    return {"image_execs":image_execs,"owners":owners,"links":links}


def roleid(a):
    pkg=a["package_id"]
    if "/ruff/crates/" in pkg:pkg="crates/"+pkg.split("/ruff/crates/",1)[1].split("#",1)[0]
    elif "/ruff/" in pkg:pkg=pkg.split("/ruff/",1)[1].split("#",1)[0]
    src=a["target"]["src_path"]
    if "/ruff/" in src:src=src.split("/ruff/",1)[1]
    elif "/registry/src/" in src:src=src.split("/registry/src/",1)[1].split("/",1)[1]
    return "|".join([pkg,a["target"]["name"],",".join(a["target"]["kind"]),str(a["profile"]["test"]).lower(),src])


def resolved(records,name):
    seen=set()
    while "alias" in records[name]:
        assert name not in seen
        seen.add(name);other=records[name]["alias"]
        assert records[name]["stat"]==records[other]["stat"];name=other
    return records[name]


def changed(a,b):
    secs={}
    for n in sorted(set(a["sections"])|set(b["sections"])):
        l=a["sections"].get(n); r=b["sections"].get(n)
        if l!=r:secs[n]={"header":l is None or r is None or l[:-1]!=r[:-1],"payload":l is None or r is None or l[-1]!=r[-1],"alloc":bool((l or r)[1]&2),"exec":bool((l or r)[1]&4)}
    la=a["loads"];lb=b["loads"]
    return {"sha256":[a["sha256"],b["sha256"]],"bytes":[a["bytes"],b["bytes"]],
            "sections":secs,"rodata_entsize":[a["rodata_entsize"],b["rodata_entsize"]],
            "gnu_id":[a["build_id"],b["build_id"]],
            "same_whole_after_two_fields":a["normalized_build_id_and_rodata_entsize"]==b["normalized_build_id_and_rodata_entsize"],
            "same_loads_without_build_id":[l[:6]+l[7:] for l in la]==[l[:6]+l[7:] for l in lb]}


def phase(z,prefix,p):
    def rd(n):return json.loads(z.read(prefix+p+"/"+n))
    typed=[json.loads(x) for x in z.read(prefix+p+"/stdout.jsonl").splitlines()]
    assert typed[-1]=={"reason":"build-finished","success":True}
    arts=[r for r in typed if r["reason"]=="compiler-artifact"]
    original=rd("result.json")
    assert len(arts)==original["count"] and sum(not a["fresh"] for a in arts)==len(original["dirty"])
    assert rd("command.json")["returncode"]==0
    native=z.read(prefix+p+"/native.stdout")
    assert b"test workspace_folders::single_file_workspace ... ok" in native and b"1 passed; 0 failed" in native
    meta=json.loads(gzip.decompress(z.read(prefix+p+"/product-bytes.json.gz")))
    names={x for a in arts for x in a["filenames"]}
    assert names==set(meta["files"]) and len(arts)==len(meta["units"])
    for a in arts:
        key="|".join([a["package_id"],a["target"]["name"],",".join(a["target"]["kind"]),str(a["profile"]["test"]),a["target"]["src_path"],",".join(sorted(a["features"])),",".join(sorted(a["filenames"]))])
        assert meta["units"][key]=={"fresh":a["fresh"],"executable":a["executable"],"files":a["filenames"]}
        if a["executable"]:
            assert original["native"][a["executable"]]==resolved(meta["files"],a["executable"])["sha256"]
    products={f:roleid(a) for a in arts for f in a["filenames"]}
    assert len(products)==len(names)
    logical=Counter((roleid(a),tuple(sorted(a["features"])),tuple(sorted(a["profile"].items(),key=lambda pair:pair[0])) if not any(isinstance(v,(dict,list)) for v in a["profile"].values()) else json.dumps(a["profile"],sort_keys=True)) for a in arts)
    return arts,meta["files"],products,logical


def full(z,role,prefix):
    def rd(n):return json.loads(z.read(prefix+n))
    ident=rd("identity.json"); summary=rd("qualified.json")
    assert len(ident["sdk"])==79 and len(rd("registry.json"))==498
    native=traced(z,prefix);worker=rd("native-processes.json")
    assert native["image_execs"]==len(worker["processes"])
    assert len(native["owners"])==len({r["pid"] for r in worker["processes"] if r["owner"]})
    assert len(native["links"])==len(worker["linkers"])==summary["native_link_executions"]
    phases={p:phase(z,prefix,p) for p in PHASES};cold,files0,_,l0=phases["cold"]
    result={}
    for p,(arts,files,labels,logical) in phases.items():
        assert logical==l0 and set(files)==set(files0)
        elfs={};nonelf=[];elf_count=0
        for name in sorted(files):
            a=resolved(files0,name);b=resolved(files,name)
            if "sections" in a:
                elf_count+=1
                assert "sections" in b
                if a["sha256"]!=b["sha256"]:elfs[labels[name]+"|"+Path(name).name]=changed(a,b)
            elif a["sha256"]!=b["sha256"]:
                nonelf.append([labels[name],Path(name).name,a["sha256"],b["sha256"]])
        result[p]={"typed":len(arts),"dirty":len([r for r in arts if not r["fresh"]]),"declared_paths":len(files),"elf_files":elf_count,"changed_elfs":elfs,"changed_nonelfs":nonelf}
    logic=sorted((json.dumps(key,separators=(",",":"),sort_keys=True),ct) for key,ct in l0.items())
    logic_sha=hashlib.sha256(json.dumps(logic,separators=(",",":"),sort_keys=True).encode()).hexdigest()
    arts,files,labels,_=phases["traced"]
    byname={}
    for name,label in labels.items():byname.setdefault(Path(name).name,set()).add(label)
    for n in native["links"]:
        fname=n.pop("output")
        if fname in labels:label=labels[fname]
        else:
            matched=byname[Path(fname).name];assert len(matched)==1;label,=matched
        n["target"]=label;n["basename"]=Path(fname).name;n["unit_directory"]=str(Path(fname).parent.parent)
    assert len({(n["target"],n["basename"]) for n in native["links"]})==len(native["links"])
    counts=Counter("link_only" if row[2] else "full" for row in native["owners"].values())
    counts.update({"Wild":len(native["links"]),"link_only_with_Wild":sum(x["link_only"] for x in native["links"])})
    # This independently acquired planner is accepted per arm only when its actual
    # observed ID/name anchors and direct edges agree with this Cargo's own log.
    graph=json.loads(gzip.decompress(Path(__file__).with_name("previous-planner-ids.json.gz").read_bytes()))["units"]
    reasons=[];anchors=set();mismatches=[];independent_edges=[];latest={};physical_roots={}
    for line in z.read(prefix+"fingerprint/stderr").decode().splitlines():
        context=re.search(r'prepare_target\{(.*?target="[^"]+")\}: cargo::compiler::fingerprint: +(.+?)$',line)
        if context and context[2].startswith("fingerprint at: "):
            latest[context[1]]=Path(context[2].removeprefix("fingerprint at: "))
        anchor=re.search(r'package_id=(\S+) v.*? target="([^"]+)".*?early_cutoff: unit UnitIndex\((\d+)\) is FRESH',line)
        if anchor:
            pkg,tgt,k=anchor[1],anchor[2],int(anchor[3])
            if k<len(graph) and graph[k][:2]==[pkg,tgt]:anchors.add(k)
            else:mismatches.append([pkg,tgt,k])
        if 'cargo::compiler::fingerprint:' not in line or 'dirty: ' not in line:continue
        target=re.search(r'package_id=(\S+) v[^ }]+(?: \(.*?\))? target="([^"]+)"',line)
        if not target:continue
        why=line.split('dirty: ',1)[1];dep=re.search(r'UnitIndex\((\d+)\)',why)
        if dep:
            k=int(dep[1])
            options=[i for i,g in enumerate(graph) if g[:2]==[target[1],target[2]] and any(d[0]==k for d in g[4])]
            independent_edges.append([target[1],target[2],k,options])
        reasons.append([target[1],target[2],("upstream:"+dep[1]) if dep else ("foreign-span" if "ohm-foreign-span-bytes" in why else "native-recheck" if "/dev/null/ohm-recheck-dependent-links" in why else why)])
        assert context and context[1] in latest
        f=latest[context[1]]
        physical_roots.setdefault(str(f.parent.parent),[]).append((f.name,reasons[-1]))
    for link in native["links"]:
        raw=physical_roots.get(link.pop("unit_directory"),[])
        assert len(raw)==1,(link,raw)
        link["fingerprint"]=raw[0][0]
        link["observed_dirty_reason"]=raw[0][1][2]
    graph_agrees=len(anchors)>300 and not mismatches and all(r[3] for r in independent_edges)
    planner={"confirmed_id_count":len(anchors),"disagreements":mismatches,"matching_edges":sum(bool(r[3]) for r in independent_edges),"total_stale_edges":len(independent_edges),"planner_agrees":graph_agrees}
    if graph_agrees:
        counts_by_id=Counter(r[2] for r in independent_edges)
        planner["upstream_fingerprint_reasons"]={str(k):{"count":n,"package":graph[k][0],"target":graph[k][1],"mode":graph[k][3],"dependencies_also_reported":[d for d in graph[k][4] if d[0] in counts_by_id]} for k,n in sorted(counts_by_id.items())}
    rawmark=rd("transitive-markers.json");markers={}
    for fn,r in rawmark["marked"].items():
        data=z.read(prefix+"fingerprints/"+r["saved"])
        assert hashlib.sha256(data).hexdigest()==r["sha256"] and len(data)==r["bytes"] and all(x.encode() in data for x in r["markers"])
        markers[fn.split("/")[-1]]=r["markers"]
    print(role,counts,{p:[r["typed"],r["dirty"],list(r["changed_elfs"])] for p,r in result.items()},file=sys.stderr)
    return {"identity":{k:ident[k] for k in ("worker","boot","ruff","lock","run","sha","release_asset")},"phases":result,"logical_inventory_sha256":logic_sha,"planner_crosscheck":planner,"counts":dict(counts),"operating_system_execs":native["image_execs"],"links":native["links"],"fingerprint_reasons":reasons,"marked_depfiles":markers}


def reopen(archive,digest):
    with archive.open("rb") as f:assert hashlib.file_digest(f,"sha256").hexdigest()==digest
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        names=z.namelist();assert len(names)==len(set(names)) and all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in names)
        rows={}
        for v in ("18","22"):
            suffix=v+"/evidence/identity.json"
            matches=[n for n in names if n.endswith(suffix) and not n.endswith("1"+suffix)]
            assert len(matches)==1,(v,matches)
            rows[v]=full(z,v,matches[0].removesuffix("identity.json"))
    assert all(rows["18"]["identity"][k]==rows["22"]["identity"][k] for k in ("worker","boot","ruff","lock","run","sha"))
    a,b=({x["target"] for x in rows[r]["links"]} for r in ("18","22"))
    return {"archive_sha256":digest,"arms":rows,"same_logical_inventory":rows["18"]["logical_inventory_sha256"]==rows["22"]["logical_inventory_sha256"],"shared_destinations":sorted(a&b),"extra_22":sorted(b-a),"only_18":sorted(a-b)}


if __name__=="__main__":
    assert len(sys.argv)==3
    print(json.dumps(reopen(Path(sys.argv[1]),sys.argv[2]),indent=2,sort_keys=True))
