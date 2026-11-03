"""Independently authenticate the ordinary Ruff library build, all native members and both verdicts."""
import argparse,collections,hashlib,json,os,re,resource,shutil,subprocess as sp,sys,tempfile,zipfile
from pathlib import Path
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE.parent/"owner-buckets"))
import verify as e2e
sys.path.insert(0,str(BASE))
from member_names import read_names, native_identity
from public_states import inspect as inspect_public_states
must=e2e.must
bodies=collections.defaultdict(list)
WANT={True:b"scripts=1\nscripts=1\nvendored-paths=3\n",False:b"scripts=0\nscripts=1\nvendored-paths=3\n"}
PROJECT=b'#!/usr/bin/env -S uv run --script\n# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\nprint("fixture")\n'
def read(archive,sha,work,report):
    must(e2e.digest(archive)==sha and shutil.disk_usage(work).free>16*2**30,"source archive identity / disk guard")
    typed_archives=collections.defaultdict(list);grades={};rlibs=collections.defaultdict(list);sizes={};executables={};sealed_roster=graph=None;summary=[];graph_checks=[]
    with zipfile.ZipFile(archive)as z,tempfile.TemporaryDirectory(dir=work)as scratch:
        root=Path(scratch);fixture=root/"fixture";fixture.mkdir();(fixture/"script.py").write_bytes(PROJECT)
        must(len(z.namelist())==len(set(z.namelist())),"duplicate source member")
        def j(k):return json.loads(z.read(k))
        def lines(k):return [json.loads(s)for s in z.open(k)]
        def pmu(k):
            h=j(k+"/hardware.json");must(h["status"]==0 and h["instructions"]>0 and 0<h["running"]==h["enabled"],"raw nonmultiplexed counter "+k);return h["instructions"]
        def body(b):
            s,n=b["sha256"],b["bytes"];must(re.fullmatch("[0-9a-f]{64}",s) and 0<n<650*2**20 and sizes.setdefault(s,n)==n,"out-of-range original")
        def native_obs(n,tools):
            rows=z.read(n+"/tasks/epochs.tsv").decode().splitlines();images={};called=[];cost=collections.Counter();bad=collections.Counter()
            for ln in rows:
                row=ln.split()
                if row[0]=="I":
                    idx=int(row[1]);args=z.read(n+f"/tasks/{idx:05}.nul").split(b"\0");must(args.pop()==b"" and args[0].decode()==row[2],"physical exec")
                    identity=tuple(map(int,args[1:3]));exe=Path(os.fsdecode(args[3])).name;argv=args[4:]
                    if identity==tuple(tools["rustc"][k]for k in ("dev","ino"))and b"--crate-name"in argv:exe="rustc:"+argv[argv.index(b"--crate-name")+1].decode()
                    if identity==tuple(tools["wild"][k]for k in ("dev","ino")):exe="wild"
                    images[idx]=exe
                    if row[5]=="exec"and(exe=="wild"or exe.startswith("rustc:")):called.append(exe)
                elif row[0]=="C":
                    idx,_,_,inst,enabled,running=map(int,row[1:7]);must(inst>=0 and enabled==running,"process clock");cost[images[idx]]+=inst
                    if inst and not enabled:bad[images[idx]]+=inst
            return {"real_execs":called,"process_instructions":dict(cost),"positive_instructions_without_clock":dict(bad)}
        public=inspect_public_states(z);reg=j("registration.json");factory=j("factory-consumed.json");must(reg["old"]==e2e.OLD and reg["new"]==e2e.NEW and reg["order"]=="PC" and reg["factory"]==factory["binding"] and hashlib.sha256((BASE/"client.rs").read_bytes()).hexdigest()==reg["client"],"source/actor binding")
        must(reg["command"]==["cargo","+ohm","build","-p","ty_ide","--lib","--locked","--offline","-j4","--message-format=json"],"different entry")
        must(3.8<pmu("calibration-4000000")/pmu("calibration-1000000")<4.2,"hardware calibration");terminal=j("terminal.json")
        for ix,role in enumerate("PC"):
            tool=j(role+"/tools.json");must(tool["driver"]["sha256"]==reg["factory"]["driver"][role],"different compiler")
            gbuf=z.read(role+"/unit-graph.json");g=json.loads(gbuf);must(graph is None or graph==gbuf,"resolution changed");graph=gbuf
            u=g["units"];i,=g["roots"];deps={u[r["index"]]["target"]["name"]for r in u[i]["dependencies"]};names={a["target"]["name"]for a in u}
            must(len(u)==283 and u[i]["target"]["name"]=="ty_ide" and u[i]["mode"]=="build" and "ty_project"in deps and not names&{"ty_server","e2e"},"different standalone target")
            fail=lines(role+"/invalid/stdout.jsonl");must(fail[-1]=={"reason":"build-finished","success":False}and any((v.get("message",{}).get("code")or{}).get("code")=="E0308"for v in fail if v["reason"]=="compiler-message"),"invalid source falsely passed")
            objects={};arts={};phase={};oracles={};observed={};member_sets={}
            for n in ("old","edit","unchanged","repair","observed-old","observed-edit","observed-unchanged","independent-clean"):
                p=role+"/"+n;d=j(p+"/result.json");data=lines(p+"/stdout.jsonl")
                must(data[-1]=={"reason":"build-finished","success":True}and d["source"]==(e2e.OLD if n in ("old","observed-old")else e2e.NEW),"Cargo/source verdict "+p)
                units=[r for r in data if r["reason"]=="compiler-artifact"];roster=sorted((r["package_id"],r["target"]["name"],r["target"]["kind"],sorted(r["features"]),r["profile"])for r in units)
                if sealed_roster is None:sealed_roster=roster
                must(roster==sealed_roster and len(units)==259 and sorted(r["target"]["name"]for r in units if not r["fresh"])==d["dirty"],p+" typed roster")
                if n in ("old","independent-clean"):must(len(d["dirty"])==259,p+" fully empty")
                if n in ("edit","observed-edit"):must(d["dirty"]==["ty_ide","ty_project"],p+" edited roster")
                if "unchanged"in n:must(not d["dirty"],p+" no-op")
                if n.startswith("observed"):
                    obs=native_obs(p,tool["physical"]);must(obs==d["observed"],p+" process identity");observed[n]=obs
                    if n=="observed-edit":must(sorted(obs["real_execs"])==["rustc:ty_ide","rustc:ty_project"],p+" real edited worker roster")
                    if "unchanged"in n:must(not obs["real_execs"],p+" real no-op")
                else:phase[n]=pmu(p);must(phase[n]==d["instructions"],p+" raw PMU")
                if n in ("old","edit","repair","independent-clean"):
                    oracle=d["oracle"];body(oracle["elf"]);is_old=n=="old";s=oracle["elf"]["sha256"];oracles[n]=s
                    must(z.read(p+"/oracle/stdout")==WANT[is_old] and oracle["stdout"].encode()==WANT[is_old]and executables.setdefault(s,is_old)==is_old,p+" native verdict")
                    if is_old:
                        errors=lines(p+"/oracle/old-interface.stderr");must(any((r.get("code")or{}).get("code")=="E0599"and"scripts_to_synchronize"in r.get("message","")for r in errors),p+" old interface")
                    args=j(p+"/oracle/argv.json");real=set(args[i+1]for i,k in enumerate(args)if k=="--extern")
                    for crate in ("ty_ide","ty_project","ruff_db"):
                        entry,=(r for r in units if r["target"]["name"]==crate and r["target"]["kind"]==["lib"]);lib,=(v for v in entry["filenames"]if v.endswith(".rlib"));must(crate+"="+lib in real,"wrong selected library")
                    syms=j(p+"/oracle/linked-symbols.json");must(any("map_system_to_vendored"in v[0]for v in syms)and any("scripts_to_synchronize"in v[0]for v in syms)==(not is_old),"wrong linked API")
                if n in ("old","edit","observed-old","observed-edit","independent-clean"):
                    a=j(p+"/native.json");objects[n]=a["objects"];arts[n]=a["outputs"];member_sets[n]=a["members"]
                    for key,v in arts[n].items():
                        body(v["rlib"]);s=v["rlib"]["sha256"]
                        for b in v["metadata"]:body(b)
                        if a["members"]:
                            mem=a["members"][key];typed_archives[s].append((key,mem["bijection"]));counts=collections.Counter({(h,m):count for h,m,count in mem["native_content"]});rlibs[s].append((counts,mem["names"]))
                        if key=="ty_ide":rlibs[s].append((collections.Counter((b["sha256"],b["bytes"])for b in a["objects"].values()),None))
                    for f in a["indices"].values():
                        if "body"in f:body(f)
            def classify(x,y):
                a,b=objects[x],objects[y];must(a.keys()==b.keys(),role+" changed native inventory");out={"retained":[],"regenerated":[]}
                for name in sorted(a):
                    l,r=a[name],b[name];must(l["sha256"]==r["sha256"] and l["bytes"]==r["bytes"],role+" wrong native body")
                    equal=(l["dev"],l["ino"])==(r["dev"],r["ino"]);must(not equal or l["mtime_ns"]==r["mtime_ns"],role+" inode recycling")
                    out["retained"if equal else"regenerated"].append(name)
                return out
            base=classify("old","edit");again=classify("observed-old","observed-edit")
            must(base==j(role+"/retention.json")and again==j(role+"/observed-retention.json"),"CGU donor joins")
            must(oracles["old"]!=oracles["edit"]==oracles["repair"]==oracles["independent-clean"] and z.read(role+"/old-client-on-new.stdout")==WANT[True],"warm/repair/fresh full executable")
            canon=lambda n:{k:(v["sha256"],v["bytes"])for k,v in objects[n].items()}
            must(canon("edit")==canon("independent-clean"),"wrong fresh native object")
            for crate,m in member_sets["edit"].items():
                other=member_sets["independent-clean"][crate]
                must(m["native_content"]==other["native_content"] and native_identity(m["bijection"])==native_identity(other["bijection"]),"wrong warm/fresh native association")
            q=j(role+"/qualified.json");must(q==terminal["roles"][ix]and q["retained"]==len(base["retained"])and q["primary"]==phase["edit"]and q["cold"]==phase["old"]and q["noop"]==phase["unchanged"],"sealed phase did not reproduce")
            summary.append({"role":role,"primary":phase["edit"],"cold":phase["old"],"noop":phase["unchanged"],"CGUs":len(objects["edit"]),"retained":len(base["retained"]),"observed_matches_primary":base==again,"observed":observed["observed-edit"],"oracle_elf":oracles,"rlib_edit":arts["edit"],"rlib_independent":arts["independent-clean"],"footprint":j(role+"/footprint.json")})
        must(reg["kernel_boot"] and len({r["oracle_elf"]["old"]for r in summary})==len({r["oracle_elf"]["edit"]for r in summary})==1,"cross-role executables")
        must({f for f in z.namelist()if f.startswith("native/")and not f.endswith("/")}=={"native/"+s+".zst"for s in sizes},"native original coverage")
        for s,n in sorted(sizes.items()):
            path=root/s
            with path.open("xb")as out:
                proc=sp.Popen(["zstd","-qdc"],stdin=sp.PIPE,stdout=out,preexec_fn=lambda:resource.setrlimit(resource.RLIMIT_FSIZE,(n,n)))
                with proc.stdin,z.open("native/"+s+".zst")as source:shutil.copyfileobj(source,proc.stdin,2**20)
                must(proc.wait()==0,"invalid compressed original")
            must(path.stat().st_size==n and e2e.digest(path)==s,"native original changed")
            if s in rlibs:
                for crate,at in typed_archives[s]:must(read_names(path,crate)==at,"native names, payloads or symbol associations diverged")
                count=e2e.ar(path);names=sp.check_output(["ar","t",path],text=True).splitlines()
                for body_counts,member_names in rlibs[s]:must(count==body_counts and(member_names is None or names==member_names),"original native archive differs")
            if s in executables:
                path.chmod(0o700);out=sp.run([path,fixture],cwd=root,env={"PATH":"/usr/bin:/bin","HOME":str(root),"LANG":"C","UV_OFFLINE":"1"},capture_output=True,timeout=60,check=True)
                must(out.stdout==WANT[executables[s]],"actual independently executed emitter changed")
            path.unlink()
    p,c=summary;gain=1-c["primary"]/p["primary"];must(gain==terminal["reduction"]and c["retained"]-p["retained"]==terminal["additional_objects"],"independently priced result")
    result={"metadata":public,"archive_sha256":sha,"hardware_boot":reg["kernel_boot"],"source_pair":[reg["old"],reg["new"]],"unit_graph_sha256":hashlib.sha256(graph).hexdigest(),"units":len(sealed_roster),"unit_graph_nodes":283,"native_bodies":len(sizes),"native_bytes":sum(sizes.values()),"physical_native_clients_executed":len(executables),"histories":summary,"reduction":gain,"speedup":p["primary"]/c["primary"]};report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("archive",type=Path);parser.add_argument("--sha256",required=True);parser.add_argument("--work",type=Path,required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args();read(args.archive,args.sha256,args.work,args.output)
