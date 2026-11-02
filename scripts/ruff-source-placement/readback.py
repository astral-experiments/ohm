"""Reopen the complete source subjects without any product binary, SDK or live target."""
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from common import WORKFLOW, enrollment, need, save, sha
import receiver
import storage
import tracking
sys.path.insert(0,str(WORKFLOW))
import raw
import extern_diff
import shards
import durable

digest=raw.digest
read=raw.read
PHASES=("old","new","unchanged","invalid","repair","clean-new")


def whole(z,name):
    with z.open(name) as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def storage_read(z,folder,index_cache):
    reported=read(z,folder+"/storage.json")
    pathname=folder+"/actual-storage.jsonl.gz"
    need(whole(z,pathname)==reported["rows_sha256"],"changed physical file census")
    union=set();totals=Counter();by_root={"target":Counter(),"build":Counter()};indices={};footers={}
    with z.open(pathname) as source,gzip.GzipFile(fileobj=source) as lines:
        for line in lines:
            root,rel,dev,ino,mode,nlink,size,blocks,*target=json.loads(line)
            path=Path(rel)
            need(root in by_root and not path.is_absolute() and ".." not in path.parts and ino>0 and nlink>0
                 and size>=0 and blocks>=0 and blocks%512==0 and len(target)==stat.S_ISLNK(mode),"invalid original stat row")
            counts=by_root[root]
            counts["paths"]+=1;counts["logical_bytes_per_path"]+=size;counts["allocated_bytes_per_path"]+=blocks
            if (dev,ino) in union:continue
            union.add((dev,ino));counts["unique_first_here"]+=1;counts["allocated_first_here"]+=blocks
            totals["allocated"]+=blocks
            kind=("directory" if stat.S_ISDIR(mode) else "symlink" if stat.S_ISLNK(mode) else
                  "index" if path.name=="work-products.bin" else "object" if path.suffix==".o" else
                  "incremental_other" if "incremental" in path.parts else "other")
            totals[kind]+=blocks
            if kind!="index":continue
            name=root+"/"+rel
            key,logical=reported["indices"][name]
            need(size==logical and re.fullmatch("[a-f0-9]{64}",key),"unbound original incremental index")
            if key not in index_cache:
                data=gzip.decompress(z.read("physical/workproduct-indices/"+key+".gz"))
                need(len(data)==size and digest(data)==key,"different original index body")
                index_cache[key]=storage.parse_footer(data)
            indices[name]=[key,size]
            if index_cache[key]:footers[name]=index_cache[key]
    result={"roots":by_root,"union_unique":len(union),"allocated":totals,"rows_sha256":reported["rows_sha256"],
            "indices":indices,"footers":footers,"optional_tail_bytes":sum(f["bytes"] for f in footers.values()),
            "optional_entries":sum(len(f["entries"]) for f in footers.values())}
    need(result==reported,"different reconstructed storage/optional record costs")
    return {k:reported[k] for k in ("roots","union_unique","allocated","optional_tail_bytes","optional_entries")}|{"rows_sha256":reported["rows_sha256"]}


def selection_read(z,folder,files,sdk):
    report=read(z,folder+"/source-selection.json")
    kernel=raw.checked_json(z,folder+"/kernel.json",report["raw_kernel_tree_sha256"])
    parents={int(c):p for c,p in kernel["tree"]["parents"].items()}
    compiler={r["pid"]:r for r in kernel["compilers"] if r["kind"]=="full" and r["exec"]==sdk+"/bin/rustc"}
    children={r["pid"] for r in kernel["tree"]["processes"] if r["path"]!=sdk+"/bin/rustc"}
    literal=read(z,folder+"/command.json")["actual"]
    effective=read(z,folder+"/effective-file-trace.json")
    need(literal==effective["registered_observer"] and literal[literal.index("--")+1:]==effective["ordinary"],"registered subject differs")
    changed=effective["actual_observer"]
    need(len(literal)==len(changed) and changed[changed.index("--")+1:]==effective["ordinary"],"observer changed actual Cargo/PMU args")
    different=[(a,b) for a,b in zip(literal,changed) if a!=b]
    need(len(different)==1 and different[0][0].startswith("trace=") and different[0][1].startswith(different[0][0]+",") and
         set(different[0][1][len(different[0][0])+1:].split(",")) in (set(tracking.EXTRA),set(tracking.EXTRA)|{"openat","openat2"}),
         "new observer changed non-file execution semantics")
    hits=[];writes=[]
    for name in sorted(files):
        tid=int(name.rsplit(".",1)[1]);owner=tracking.identity(tid,parents,compiler,children)
        with z.open(name) as inp,io.TextIOWrapper(inp,encoding="utf-8") as lines:
            for line in lines:
                if "ohm-placement-" in line and line.startswith(("rename(","renameat(","renameat2(")):
                    names=tracking.classify(line)
                    if not names:continue
                    start,dest=names;m=tracking.NAME.fullmatch(dest.name)
                    need(owner and m and m["owner"]==owner["name"],"actual durable rename is not in its enrolled physical rustc")
                    hits.append({"pid":owner["pid"],"tid":tid,"owner":m["owner"],"cgu":m["cgu"],"source":str(start),
                                 "destination":str(dest),"syscall_sha256":digest(line.encode())})
                elif owner and line.startswith(("openat(","openat2(")) and ".rcgu.o" in line and "O_CREAT" in line and (
                      "O_WRONLY" in line or "O_RDWR" in line) and not re.search(r"= -1\b",line):
                    operands=tracking.QUOTED.findall(line)
                    if not operands:continue
                    f=Path(tracking.ast.literal_eval(operands[0]));m=tracking.NAME.fullmatch(f.name)
                    if m and m["owner"]==owner["name"]:
                        writes.append({"pid":owner["pid"],"tid":tid,"owner":m["owner"],"cgu":m["cgu"],"path":str(f),
                                       "syscall_sha256":digest(line.encode())})
    need(hits==report["renames"] and writes==report["ordinary_native_object_writes"] and
         len({(r["pid"],r["cgu"]) for r in hits})==len(hits),"unsupported selection or fallback projection")
    return hits,writes


def native_reversals(z,idx,sdk,ref,bodies):
    base="physical/durability/"
    final=read(z,base+"complete.json")
    known=set(final["reference_hits"]);chosen=final["ordinary_hit_cgu"];need(chosen in known,"unregistered mutation subject")
    expected={"round-trip":("old","new","return-old"),"object-corrupt":("old","new"),"optional-corrupt":("old","new"),
              "independent-empty-old":("old",)}
    need(set(final["outcomes"])==set(expected),"missing independently empty or adversarial install")
    result={}
    for case,phases in expected.items():
        prefix=base+case+"/";result[case]={}
        need(set(final["outcomes"][case])==set(phases),"missing adversarial history")
        for phase in phases:
            folder=prefix+phase;report=read(z,folder+"/durability.json")
            hits,writes=selection_read(z,folder,idx[folder],sdk)
            selected={r["cgu"] for r in hits if r["owner"]=="ruff_workspace"}
            emitted={r["cgu"] for r in writes if r["owner"]=="ruff_workspace"}
            key=report["archive"]["raw_sha256"]
            need(key in bodies["owner-archives"] and final["outcomes"][case][phase]==key and
                 report["reader"] in bodies["native-bodies"] and report["hits"]==sorted(selected) and
                 report["native_writes"]==sorted(emitted),"wrong source selection, emitted native body or reader")
            which="clean-new" if phase=="new" else "old"
            need(report["reader"]==ref[which]["elf"] and report["reference_archive"]==ref[which]["owner_archive"]["sha256"],
                 "different independently linked consumer or source archive")
            as_object=lambda n:durable.member_map(gzip.decompress(z.read("physical/owner-archives/"+n+".gz")))
            need(as_object(key)==report["archive"] and as_object(report["reference_archive"])["objects"]==report["archive"]["objects"],
                 "different complete native archive CGU or DWARF")
            if phase=="old":need(not selected,"empty build hit prior codegen")
            if case=="round-trip" and phase!="old":need(selected&known,"no selected object on return or forward")
            if case=="object-corrupt" and phase=="new":need(chosen not in selected and chosen in emitted,"known corrupted object accepted")
            if case=="optional-corrupt" and phase=="new":need(not selected and known<=emitted,"damaged source certificate accepted")
            # Reopen the native checker stdout and diagnostics against the identical clean source and executable.
            reference="physical/option/C-"+("clean/clean-new" if phase=="new" else "edit/old")
            for name in ("field","sibling","missing"):
                for ext in ("stdout","stderr"):
                    need(z.read(folder+"/client/"+name+"."+ext)==z.read(reference+"/client/"+name+"."+ext),"different real option verdict")
            result[case][phase]={"reader":report["reader"],"archive":key,"CGUs":len(report["archive"]["objects"]),"hits":len(selected),
                                 "selected":sorted(selected),"normal_writes":len(emitted)}
        if case=="round-trip":
            need(set(result[case]["new"]["selected"]) & set(result[case]["return-old"]["selected"]),"no freshly restored code on second switch")
            witnesses=read(z,prefix+"hardlinks-before.json")
            need(set(witnesses)==known and all(w["nlink"][1]==w["nlink"][0]+1 and w["size"]>0 for w in witnesses.values()),
                 "missing independent old hardlink witnesses")
            for ph in phases:
                witnessed=read(z,prefix+ph+"/durability.json")["prior_hardlink_readback"]
                need(set(witnessed)==set(witnesses) and all(row==[witnesses[cgu][k] for k in ("dev","ino","size","sha256")] for cgu,row in witnessed.items()),
                     "a prior finalized inode changed while the candidate used its private destination")
        if case in ("object-corrupt","optional-corrupt"):
            n="object-mutation.json" if case=="object-corrupt" else "footer-mutation.json"
            x=read(z,prefix+n);b=x["before"];a=x["after"]
            need(b[0]!=a[0] and b[1:3]!=a[1:3] and a[3]==1 and a[4:]==b[4:],"mutation did not isolate same-size/restamped bytes")
            original=gzip.decompress(z.read(prefix+"original-work-products.bin.gz"));ft=storage.parse_footer(original)
            old=read(z,prefix+"old/durability.json")
            if case=="optional-corrupt":
                changed=gzip.decompress(z.read(prefix+"mutated-work-products.bin.gz"))
                at=ft["offset"]+12
                need(digest(original)==b[0] and digest(changed)==a[0] and changed==original[:at]+bytes([255])*4+original[at+4:],"different legacy metadata or unchanged optional damage")
                try:storage.parse_footer(changed)
                except ValueError:pass
                else:raise ValueError("truncated optional placement accepted")
            else:
                raw_object=gzip.decompress(z.read(prefix+"original-old-object.o.gz"));corrupt=gzip.decompress(z.read(prefix+"mutated-old-object.o.gz"))
                off=old["old_object_mutation"]["offset"]
                need(digest(raw_object)==b[0]==old["archive"]["objects"][chosen] and digest(corrupt)==a[0] and
                     off==durable.executable_byte(raw_object) and corrupt==raw_object[:off]+bytes([raw_object[off]^1])+raw_object[off+1:],"unverified previous native object mutation")
                seal=old["old_object_mutation"]["record"];at=ft["offset"]+len(storage.MAGIC)
                for slot,size,key,expected in ft["entries"]:
                    at+=8;wire=original[at:at+size-32];at+=size
                    if slot!=seal["slot"]:continue
                    observed=subprocess.check_output(["/usr/bin/b3sum","--no-names"],input=raw_object+wire+struct.pack("<Q",len(wire))).decode().strip()
                    need(observed==expected==seal["bound_blake3"] and key==seal["key"] and seal["index"]==digest(original),
                         "old marked object failed actual source-bound length-framed BLAKE3")
                    break
                else:raise ValueError("absent original object slot")
    return result



def rss_read(z,folder,stage,suite,phase,frontend):
    meta=read(z,folder+"/rss.json")
    observed=raw.checked_json(z,folder+"/wait4-rss.json",meta["raw_sha256"])
    need(observed["maxrss_kib"]>0 and observed["user_us"]>=0 and observed["system_us"]>=0 and
         os.waitstatus_to_exitcode(observed["status"])==(101 if phase=="invalid" else 0),"different real native process status or peak")
    task=read(z,folder+"/command.json")["actual"]
    traced=read(z,folder+"/effective-file-trace.json")["actual_observer"] if stage=="admit" else task
    need(meta["tracer_argv"]==traced and traced[traced.index("--")+1:]==task[task.index("--")+1:],"peak observer changed ordinary Cargo/event subjects")
    kernel=read(z,folder+"/kernel.json");subjects={r["pid"]:r for r in kernel["compilers"] if r["kind"]=="full"}
    watched=meta["observed_owner_highwater"]
    for pid,record in watched.items():
        need(int(pid) in subjects and subjects[int(pid)]["name"]==record["owner"] and record["observed_highwater_kib"]>0
             and record["readings"]>0 and record["front_dev_ino"]==frontend and meta["sample_period_ms"]==100,"unbound per-compiler memory sample")
    if stage=="admit" and phase=="new":
        needed={"ruff_workspace"} if suite=="option" else {"ty_server","e2e"}
        need({v["owner"] for v in watched.values()}==needed,"no peak sample for the edited physical root")
    if stage=="score":need(not watched and meta["sample_period_ms"] is None,"sampled processes inside hardware study")
    return {"kernel_maxrss_kib":observed["maxrss_kib"],"owner_highwater_samples":watched,"raw":meta["raw_sha256"]}


def handoff_read(z,idx,sdk,vals,bodies,spec):
    complete=read(z,"physical/check-to-build/complete.json")
    expected=("empty-check-old","build-after-check-old","invalid-check-new","build-after-repair-new","repeat-build-new")
    need(set(complete)=={"P","C"},"incomplete role transition")
    for role,data in complete.items():
        need(set(data)==set(expected),"wrong check/build state machine")
        for phase in expected:
            pre="physical/check-to-build/"+role+"/"+phase
            visit=raw.checked_json(z,pre+"/transition.json",data[phase]);a=read(z,pre+"/command.json")
            cmd=list(spec["suites"]["option"]["cargo"]);is_check=phase in ("empty-check-old","invalid-check-new");bad=phase=="invalid-check-new"
            if is_check:cmd[cmd.index("build")]="check"
            need(visit["argv"]==cmd==a["ordinary"] and visit["returncode"]==(101 if bad else 0) and
                 visit["source"]==read(z,pre+"/source.json") and bool(visit["source"]["invalid"])==bad,"wrong command, source or verdict")
            rows=[json.loads(l) for l in z.read(pre+"/outer.stdout").splitlines() if l.strip()]
            durable.study.results(rows,not bad)
            hit,_=selection_read(z,pre,idx[pre],sdk)
            if is_check or role=="P":need(not hit,"parent or check-only published a native reuse")
            kernel=raw.checked_json(z,pre+"/kernel.json",visit["kernel"])
            owners=[r for r in kernel["compilers"] if r["name"]=="ruff_workspace" and r["kind"]=="full"]
            need(len(owners)==int(phase!="repeat-build-new"),"different true root compiler")
            if phase=="repeat-build-new":need(kernel["rustc"]==[] and kernel["linkers"]==[],"warm repaired build was not fresh")
            if bad:need(visit.get("error")=="E0308","different original invalid check")
            if is_check:continue
            which="old" if phase=="build-after-check-old" else "clean-new"
            gold=vals[role][which]
            need(visit["reader"]==gold["elf"] and visit["reader"] in bodies["native-bodies"] and
                 visit["reference"]==gold["owner_archive"]["sha256"] and {visit["archive"],visit["reference"]}<=bodies["owner-archives"],
                 "different independent native reader or owner archive")
            def objects(d):
                return durable.member_map(gzip.decompress(z.read("physical/owner-archives/"+d+".gz")))["objects"]
            need(objects(visit["archive"])==objects(visit["reference"]),"check/build or invalid/repair altered native CGU or debug data")
    return complete


def scan(z,run,qa,stage,slot):
    infos=z.infolist()
    need(len(infos)==len(set(i.filename for i in infos)) and sum(i.file_size for i in infos)<80<<30 and all(
         i.file_size<8<<30 for i in infos) and z.testzip() is None,"duplicate, unbounded or CRC-corrupt evidence")
    idx=defaultdict(list)
    for i in infos:
        if re.search(r"/trace/exec\.\d+$",i.filename):idx[i.filename.split("/trace/exec.")[0]].append(i.filename)
    e=read(z,"physical/entry.json");end=read(z,"physical/complete.json")
    need((e["qa"],e["run"],e["stage"],e["slot"])==(qa,run,stage,slot) and end["entry"]==whole(z,"physical/entry.json"),"wrong scheduled subject")
    roles=raw.checked_json(z,"physical/physical-roles.json",end["physical"])
    proof=raw.checked_json(z,"physical/source-qualification.json",roles["source_qualification"])
    reg=enrollment()
    need(e["source"]==end["source"]==proof["source"]==reg["roles"] and e["kit"]==end["kit"]==proof["seal"]["sha256"] and
         proof["factory_run"]==receiver.FACTORY==e["factory"] and proof["factory_qa"]==receiver.FACTORY_QA,"different source factory or SDK")
    roledef=roles["kits"]
    docs=read(z,"physical/docs-qualification.json")
    for r in ("P","C"):
        source=read(z,"physical/"+r+"-source-kit.json");kit=roledef[r];doc=roles["documentation"][r]
        need(source["commit"]==e["source"][r]["revision"] and all(source["files"][v["name"]][0]==v["sha"] for v in kit.values()) and
             kit["driver"]["sha"]==proof["physical"][r]["driver"] and doc["rustdoc"]==docs["actual"][r]["rustdoc"][0]
             and doc["html"]==whole(z,"physical/doc-control-"+r+"/actual.html") and all(
             doc["actual_libs"][k]["sha"]==kit[k]["sha"] for k in ("driver","llvm")),"different physical compiler or real documentation body")
    need(roledef["P"]["driver"]["sha"]!=roledef["C"]["driver"]["sha"] and roles["versions"]["P"]==roles["versions"]["C"] and
         all(roledef["P"][k]["sha"]==roledef["C"][k]["sha"] for k in ("cargo","wild","llvm")),"unmatched compiler or shared tool")
    spec=json.loads((HERE/"protocol.json").read_bytes())
    order=spec["assignments"][slot-1] if stage=="score" else {"roles":["P","C"] if slot==1 else ["C","P"],"suites":["option" if slot==1 else "e2e"]}
    need(e["order"]==order["roles"] and e["suites"]==order["suites"] and e["registration"]==sha(HERE/"protocol.json")
         and e["boot"]!=proof["seal"]["boot"],"different schedule, enrollment or boot")
    calibration=raw.calibration(z);bodies=raw.verify_bytes(z);index_cache={};results={};inputs={};controls={};handoff={};oracles={};pmu={}
    for suite in e["suites"]:
        d="physical/"+suite+"/";st=end["suites"][suite];vals=raw.checked_json(z,d+"acquired.json",st["acquired"])
        registry=raw.checked_json(z,d+"registry.json",st["registry"])
        need(st["command"]==spec["suites"][suite]["cargo"] and registry["autocfg-1.5.0.crate"]==
             json.loads((WORKFLOW/"worker.json").read_bytes())["autocfg"],"altered command or registry donor")
        phases=PHASES+(("negative","restored-new") if suite=="e2e" else ())
        results[suite]={};oracles[suite]={};pmu[suite]={}
        for r in e["order"]:
            results[suite][r]={};oracles[suite][r]={};pmu[suite][r]={}
            need(set(vals[r])==set(phases),"incorrect native history")
            for ph in phases:
                folder=d+r+("-edit/" if ph in ("old","new","unchanged","invalid","repair") else "-clean/")+ph
                v=vals[r][ph];actual=raw.phase_read(z,folder,ph,suite,stage,r,v,roledef[r],roles["sdk"],bodies,idx[folder])
                storage_row=storage_read(z,folder,index_cache)
                rss=rss_read(z,folder,stage,suite,ph,roledef[r]["front"]["id"][:2])
                if r=="P":need(storage_row["optional_tail_bytes"]==0,"parent has an optional placement record")
                hit=None
                if stage=="admit":
                    hits,_=selection_read(z,folder,idx[folder],roles["sdk"]);hit=Counter(v["owner"] for v in hits)
                    if r=="P" or ph in ("old","clean-new") or (ph=="unchanged" and suite=="option"):need(not hit,"unexpected reuse")
                    if (suite,r,ph)==("option","C","new"):need(hit["ruff_workspace"]>0 and storage_row["optional_entries"]>0,"no real edited acceptance")
                results[suite][r][ph]={"compilers":actual["compilers"],"wild":actual["wild"],"probes":actual["probes"],"hits":hit,"disk":storage_row,"rss":rss}
                if actual["pm"] is not None:pmu[suite][r][ph]=actual["pm"]
                oracles[suite][r][ph]={k:v[k] for k in ("elf","verdict","error","raw_roster") if k in v}
            for phase in ("new","unchanged","repair",*(("restored-new",) if suite=="e2e" else ())):
                need(all(vals[r][phase][k]==vals[r]["clean-new"][k] for k in ("elf","verdict","inventory")),"different independently empty primary goods")
            need(vals[r]["old"]["elf"]!=vals[r]["new"]["elf"] and set(pmu[suite][r])==({"old","new","unchanged"} if stage=="score" else set()),"wrong original/edited goods or event scope")
        groups={r:{s for v in rs.values() for s in v["compiler_namespace"]["ids"]} for r,rs in vals.items()}
        need(len(groups["P"])==len(groups["C"])==1 and groups["P"]!=groups["C"],"missing authenticated shared owner identity")
        for ph in phases:
            p,c=vals["P"][ph],vals["C"][ph];dirs=p["compiler_namespace"]["paths"]
            need(dirs==c["compiler_namespace"]["paths"] and shards.comparable(p,dirs)==shards.comparable(c,dirs),
                 "different native oracle or compiler args beyond physical role namespace")
        groups={r:{s for phase in phases for s in vals[r][phase]["compiler_namespace"]["ids"]} for r in ("P","C")}
        need(len(groups["P"])==len(groups["C"])==1 and groups["P"]!=groups["C"],"unstable role registry identities")
        if stage=="admit":inputs[suite]=extern_diff.scan(z,suite,dirs,{r:next(iter(a)) for r,a in groups.items()})
        if suite=="option" and stage=="admit":
            controls=native_reversals(z,idx,roles["sdk"],vals["C"],bodies)
            handoff=handoff_read(z,idx,roles["sdk"],vals,bodies,spec)
    return {"run":run,"qa":qa,"stage":stage,"slot":slot,"source":e["source"],"kit":e["kit"],"boot":e["boot"],
            "order":e["order"],"suites":e["suites"],"roles":roledef,"calibration":calibration,"native":results,"verdicts":oracles,"pmu":pmu,
            "registry_inputs":inputs,"durable":controls,"check_handoff":handoff,"raw_consumer_bodies":{k:sorted(v) for k,v in bodies.items()},"terminal_sha256":whole(z,"physical/complete.json")}


if __name__=="__main__":
    stage,slot,dest=sys.argv[1:];slot=int(slot);run=int(os.environ["GITHUB_RUN_ID"]);qa=os.environ["GITHUB_SHA"]
    artifact=Path(os.environ["RUNNER_TEMP"])/"placement-subject.zip"
    row=receiver.archive(run,qa,f"placement-{stage}-raw-{slot}",artifact,13<<30,current=True)
    with zipfile.ZipFile(artifact) as z:report=scan(z,run,qa,stage,slot)
    save(Path(dest),dict(raw=row,**report));print("Complete originals independently reopened",row,stage,slot,flush=True)
