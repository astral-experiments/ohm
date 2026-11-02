"""Characterize the getter from two independent same-path A seeds. Never score profile times."""
from pathlib import Path
import gzip,json,shutil,struct,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import gate as g

H=Path(__file__).resolve().parent; F=g.load(H/"fixtures.json")
PARENT=Path("/tmp/ohm-shared-reference-stage1-v1"); LIVE=PARENT/"live"
CASES=("A","offset","trait","both","move-line","real-lifetime-change"); CRATES=("workspace","normal","lint","hard","witness")
SUB=("normal","lint"); ARMS=("ordinary","keyed","cold","cold-keyed"); EPOCH=43309
def save(blobs,data):return g.save_blob(blobs,data)
def blob(out,h):
    assert len(h)==64 and all(c in "0123456789abcdef" for c in h)
    dst=out/"blobs"/(h+".gz");assert not dst.is_symlink() and 0<dst.stat().st_size<=16<<20
    with gzip.open(dst,"rb") as f:raw=f.read(16<<20);assert not f.read(1)
    assert g.digest(raw)==h
    return raw
def spans(diag):
    return diag.get("spans",[])+[s for child in diag.get("children",[]) for s in spans(child)]
def oracle(stderr,ret,case,crate):
    ds=[json.loads(v) for v in stderr.splitlines()];codes=[v["code"]["code"] for v in ds if v.get("code")]
    wanted=[];positions=[]
    if crate in ("lint","hard") and case!="real-lifetime-change":
        wanted=["E0794" if crate=="hard" else "late_bound_lifetime_arguments"]
        pos={"A":997,"trait":997,"offset":1029,"both":1029,"move-line":998}[case]
        line=890 if case=="move-line" else 889
        positions=[[line,25,line,26,pos,pos+1]]
    if crate=="witness" and case in ("trait","both"):
        wanted=["E0277"]
        error,=[v for v in ds if v.get("code")]
        assert error["message"]=="the trait bound `u8: Origin` is not satisfied"
    where=[[s[k] for k in ("line_start","column_start","line_end","column_end","byte_start","byte_end")] for d in ds for s in spans(d) if s["file_name"]=="workspace.rs"]
    # The trait witness can cite the changed implementation in workspace.rs in a help note.
    if crate!="witness":assert where==positions,(case,crate,where,positions)
    assert codes==wanted and ret==int(bool(wanted) and crate in ("hard","witness")),(case,crate,codes,ret)
    return {"exit":ret,"codes":codes,"external":where}
def argv(sdk,name,keyed):
    args=[str(sdk/"bin/rustc"),"--sysroot",str(sdk),"--edition=2024","--crate-type=lib","--emit=metadata","--error-format=json","--crate-name",name,"-Zthreads=1","-Zincremental-verify-ich=yes","-Cincremental=inc-"+name,name+".rs"]
    if name!="workspace":args+=["--extern","workspace=libworkspace.rmeta"]
    if keyed:args+=["-Zself-profile=keys-"+name,"-Zself-profile-events="+g.TRACE_EVENTS]
    return args
def depgraph(name):
    f,=(LIVE/("inc-"+name)).glob("*/s-*/dep-graph.bin")
    return f.read_bytes()
def previous(raw,name,version):
    graph=g.Graph(raw,g.load(H/"kinds.json")["kinds"],EPOCH,version)
    index,=[i for i,v in graph.by_id.items() if v[0]=="typeck_root"];owner=graph.by_id[index][1]
    if version==b"1.99.0-dev":assert owner==F["prior_owners"][name]
    edges=[graph.by_id[i] for i in graph.edges[index]]
    assert len(edges)=={"normal":35,"lint":39}[name] and edges.count(("incoherent_impls",F["shared_ref"]))==1
    return {"owner":owner,"direct":len(edges),"shared_ref":F["shared_ref"],"index":index}
def cold_owner(raw,graph,name,version):
    prof=g.Profile(raw);graph=g.Graph(graph,g.load(H/"kinds.json")["kinds"],EPOCH,version)
    event_id,=[n for cls,n,*_ in struct.iter_unpack("<QQIIII",memoryview(prof.entries)[8:]) if prof.label(cls)=="Query" and prof.label(n)=="typeck_root\x1e"+name+"::check"]
    assert graph.by_id[event_id][0]=="typeck_root"
    return graph.by_id[event_id][1]
def visit(sdk,env,out,version,case,arm):
    (LIVE/"workspace.rs").write_text(F["states"][case])
    for name,src in F["callers"].items():(LIVE/(name+".rs")).write_text(src)
    rows={};profs={};blobs=out/"blobs"
    for name in CRATES:
        keyed=arm in ("keyed","cold-keyed") and name in SUB;args=argv(sdk,name,keyed)
        pid,ret,stdout,err=g.process(args,LIVE,env,allow_error=True);assert not stdout
        stderr=save(blobs,err)
        with (out/"commands.jsonl").open("a") as f:print(json.dumps({"case":case,"arm":arm,"crate":name,"pid":pid,"cwd":str(LIVE),"argv":args,"exit":ret,"stderr":stderr},sort_keys=True),file=f)
        row=oracle(err,ret,case,name)|{"stderr":stderr,"metadata":None,"root":None}
        if ret==0:
            meta=LIVE/("lib"+name+".rmeta");row["metadata"]=save(blobs,meta.read_bytes())
            _,_,root,noise=g.process([str(sdk/"bin/rustc"),"-Zls=root",str(meta)],LIVE,env);assert root and not noise
            row["root"]=save(blobs,root)
        rows[name]=row
        if keyed:
            prof,=(LIVE/("keys-"+name)).glob("*.mm_profdata");raw=prof.read_bytes();graph=depgraph(name)
            events=g.profile_counts(raw,graph,EPOCH,pid,args,name,version)
            profs[name]={"profile":save(blobs,raw),"graph":save(blobs,graph),"pid":pid,"argv":args,"events":events}
    return {"rows":rows,"profiles":profs}
def run(sdk,version,out):
    sdk=sdk.resolve();(out/"blobs").mkdir();assert not PARENT.exists() and not PARENT.is_symlink();PARENT.mkdir(mode=0o700)
    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(sdk/"lib")}
    result={"sdk":str(sdk),"version":version.decode(),"fixtures":g.file_hash(H/"fixtures.json"),"seeds":{}}
    for i in ("01","02"):
        LIVE.mkdir();a=visit(sdk,env,out,version,"A","seed");seed=PARENT/"prior"
        graphs={}
        for name in SUB:
            gg=depgraph(name);graphs[name]=previous(gg,name,version)|{"sha256":save(out/"blobs",gg)}
        LIVE.rename(seed);states={}
        for case in CASES:
            visits={}
            for arm in ARMS:
                if arm.startswith("cold"):LIVE.mkdir()
                else:shutil.copytree(seed,LIVE)
                visits[arm]=visit(sdk,env,out,version,case,arm)
                shutil.rmtree(LIVE)
            assert all(visits[arm]["rows"]==visits["ordinary"]["rows"] for arm in ARMS)
            states[case]=visits
        shutil.rmtree(seed)
        result["seeds"][i]={"A":a["rows"],"previous":graphs,"cases":states}
    PARENT.rmdir();g.put(out/"probe.json",result);return verify(out)
def verify(out):
    p=g.load(out/"probe.json");base=Path(p["sdk"]);version=p["version"].encode()
    assert base.is_absolute() and p["fixtures"]==g.file_hash(H/"fixtures.json") and set(p["seeds"])=={"01","02"}
    same={};history={}; referenced=set()
    def get(h):referenced.add(h);return blob(out,h)
    def rows_check(rows,case):
        assert set(rows)==set(CRATES)
        for name,row in rows.items():
            expect=oracle(get(row["stderr"]),row["exit"],case,name)
            assert all(row[k]==v for k,v in expect.items())
            for field in ("metadata","root"):
                if row["exit"]:assert row[field] is None
                else:assert get(row[field])
    logrows=[json.loads(v) for v in (out/"commands.jsonl").read_bytes().splitlines()]
    assert len(logrows)==2*(1+len(CASES)*len(ARMS))*len(CRATES)
    ledger=iter(logrows)
    def command(case,arm,crate,row):
        cmd=next(ledger);args=argv(base,crate,arm in ("keyed","cold-keyed") and crate in SUB)
        assert cmd==dict(case=case,arm=arm,crate=crate,pid=cmd["pid"],cwd=str(LIVE),argv=args,exit=row["exit"],stderr=row["stderr"]) and type(cmd["pid"]) is int and cmd["pid"]>0
        return cmd["pid"]
    for i in ("01","02"):
        s=p["seeds"][i]
        rows_check(s["A"],"A");assert set(s["previous"])==set(SUB) and set(s["cases"])==set(CASES)
        for name in CRATES:command("A","seed",name,s["A"][name])
        assert same.setdefault("seed",s["A"])==s["A"]
        for name,old in s["previous"].items():assert previous(get(old["sha256"]),name,version)=={k:v for k,v in old.items() if k!="sha256"}
        for case in CASES:
            visits=s["cases"][case]
            assert set(visits)==set(ARMS);outcomes=visits["ordinary"]["rows"];rows_check(outcomes,case)
            assert same.setdefault(case,outcomes)==outcomes
            for arm in ARMS:
                f=visits[arm];pids={name:command(case,arm,name,f["rows"][name]) for name in CRATES}
                keyed=arm in ("keyed","cold-keyed");assert f["rows"]==outcomes and set(f["profiles"])==(set(SUB) if keyed else set())
                for name,rec in f["profiles"].items():
                    args=argv(base,name,True);assert args==rec["argv"] and pids[name]==rec["pid"]
                    raw,gg=get(rec["profile"]),get(rec["graph"]);events=g.profile_counts(raw,gg,EPOCH,rec["pid"],args,name,version)
                    assert events==rec["events"]
                    if arm=="cold-keyed":assert cold_owner(raw,gg,name,version)==s["previous"][name]["owner"]
                    nums={}
                    for kind in sorted(g.FAMILIES):
                        value=events["Query"].get(kind+" "+name+"::check",0);assert value in (0,1)
                        if arm=="cold-keyed" or case=="real-lifetime-change":assert value==1
                        if arm=="keyed" and case=="A":assert value==0
                        nums[kind]=value
                    if arm=="keyed":
                        k=case+"/"+name;assert history.setdefault(k,nums)==nums
    assert {f.stem for f in (out/"blobs").iterdir()}==referenced and sum(f.stat().st_size for f in (out/"blobs").iterdir())<64<<20
    return history
