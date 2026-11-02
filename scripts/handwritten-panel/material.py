"""Canonical source, frozen first-edit states, and the existing hosted root/counter observers."""
import gzip, hashlib, importlib.util, json, os, re, shutil, stat, subprocess, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
P=json.loads((HERE/"protocol.json").read_bytes())
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":")).encode()
def digest(b):return hashlib.sha256(b).hexdigest()
def filesha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def read(p):return json.loads(p.read_bytes())
def save(p,v):
    with p.open("xb") as f:f.write(canon(v)+b"\n")
def guard(ok,why):
    if not ok:raise ValueError(why)
def load(n,p):
    spec=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def host():
    e=os.environ
    guard(__debug__ and e["GITHUB_REPOSITORY"]==P["coordinator_repo"] and e["GITHUB_EVENT_NAME"]=="workflow_dispatch" and
          e["GITHUB_REF"]=="refs/heads/"+P["branch"] and e["GITHUB_RUN_ATTEMPT"]=="1" and re.fullmatch("[0-9a-f]{40}",e["REVIEWED_HEAD"]) and
          e["GITHUB_SHA"]==e["REVIEWED_HEAD"] and e["GITHUB_WORKFLOW_REF"]==P["coordinator_repo"]+"/.github/workflows/ci.yml@"+e["GITHUB_REF"],"unreviewed Actions scope")
    return Path(e["GITHUB_WORKSPACE"]).resolve(strict=True),Path(e["RUNNER_TEMP"]).resolve(strict=True)
ROOT=Path("/tmp/uv-workflow-search")
SRC,TARGET,CARGO_HOME,HOME,SDK=[ROOT/n for n in ("uv","target","cargo","home","sdk")]
ENV=P["env"];ARGS=P["argv"];CASE=P["case"];RUSTC=SDK/"bin/rustc"
def reference():
    ref=HERE/"reference.json.gz";guard(filesha(ref)==P["reference_sha256"],"bad checkout reference");return json.loads(gzip.decompress(ref.read_bytes()))
def shape():
    f=HERE/"shape.json.gz";guard(filesha(f)==P["shape_sha256"],"bad concrete Cargo graph");return tuple(json.loads(gzip.decompress(f.read_bytes())))
def sha_git(repo,*a):return subprocess.check_output(["git","-C",repo,*a],env={"PATH":"/usr/bin:/bin","LC_ALL":"C","GIT_OPTIONAL_LOCKS":"0","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null"})
def check_sources(w):
    parent=w/"coordinator";guard(sha_git(parent,"rev-parse","HEAD").decode().strip()==os.environ["REVIEWED_HEAD"],"workflow tree/head")
    for role,label in (("opening","opening"),("previous","previous"),("qualified","qualifier"),("pilot","pilot"),("calibrator","calibrator"),("observers","observer")):
        repo=w/role;guard(sha_git(repo,"rev-parse","HEAD").decode().strip()==P["sources"][label] and not sha_git(repo,"status","--porcelain","--untracked-files=no"),role)
    opening=w/"opening/scripts/uv-root-20991-opening"
    for name,expect in P["pinned_opening"].items():guard(filesha(opening/name)==expect,("opening",name))
    previous=w/"previous/scripts/uv-resolver-whole-pmu"
    return opening,previous
def trace_observer(opening,tmp):
    from compiler_observer import Observer
    return Observer(ARGS,reference()["argv"])
def readers(opening,tmp):
    for name,sha in P["pinned_opening"].items():guard(filesha(opening/name)==sha,("prior admitted reader",name))
    sys.path.insert(0,str(opening));o=load("pinned_opening",opening/"opening.py")
    kit=tmp/"root-20988-readers";_,api,_=o.initialize(kit)
    import deep
    parser=deep.parser(kit/"check-root-20261101/ctfe-root-attribution/metadata.py")
    return o,api,parser,trace_observer(opening,tmp)
def observers(w,tmp):
    opening,_=check_sources(w);return readers(opening,tmp)
def pmu(w,tmp):
    _,previous=check_sources(w);sys.path.insert(0,str(previous));old=load("whole_pmu_calibration",previous/"run.py")
    old.scope=host
    return old,load("inherited_meter",w/"pilot/scripts/branch-return-pmu/meter.py")
def initial(w,tmp,out):
    guard(not ROOT.exists(),"runner reused across enrollments");ROOT.mkdir()
    for p in (CARGO_HOME,HOME):p.mkdir()
    donor=w/"uv-source";subprocess.run(["git","-c","core.autocrlf=false","clone","--no-checkout",donor.as_uri(),SRC],env=ENV,check=True)
    subprocess.run(["git","-C",SRC,"checkout","-q","--detach",CASE["A"]],env=ENV,check=True)
    src,delta=history();guard(src==CASE["A_tree"],"checkout of A")
    bank=ROOT/"bank";bank.mkdir();return bank,delta
def history():
    A,B=CASE["A"],CASE["B"];g=lambda *a:sha_git(SRC,*a)
    guard(g("rev-parse","HEAD").decode().strip()==A and not g("diff","--cached","--name-only") and not g("ls-files","--others","--exclude-standard"),"A HEAD/index/extra files")
    guard(g("rev-parse",B+"^").decode().strip()==A and g("rev-parse",CASE["tag"]).decode().strip()==CASE["tag_commit"] and
          digest(g("rev-list","--parents","--topo-order",CASE["tag"]+".."+B))==CASE["chain"],"ancestry or release tag")
    guard([g("rev-parse",c+"^{tree}").decode().strip() for c in (A,B)]==[CASE["A_tree"],CASE["B_tree"]] and
          all(g("rev-parse",c+":crates/uv-cli/build.rs").decode().strip()==CASE["build_rs_blob"] for c in (A,B)),"Git tree or build owner")
    delta=g("diff","--binary","--full-index",A,B);current=g("diff","--binary","--full-index")
    guard(digest(delta)==CASE["patch"] and g("diff","--name-only",A,B).decode().splitlines()==CASE["files"] and
          current in (b"",delta) and filesha(SRC/"Cargo.lock")==CASE["lock"],"source/lock or patch")
    for f in CASE["files"]:
        guard((SRC/f).read_bytes()==g("show",(B if current else A)+":"+f),("changed-file bytes",f))
    return CASE["B_tree"] if current else CASE["A_tree"],delta
def edit(delta):
    guard(history()==(CASE["A_tree"],delta),"expected pristine A")
    subprocess.run(["git","-C",SRC,"apply","--whitespace=nowarn","-"],input=delta,env=ENV,check=True)
    guard(history()==(CASE["B_tree"],delta),"genuine edit failed")
def erase(*paths):
    for p in paths:
        guard(p.parent==ROOT and p.name in ("uv","target","cargo","home","sdk","seed","fixture") and not p.is_symlink(),"unsafe scratch path")
        if p.exists():shutil.rmtree(p)
def cp(a,b):
    guard(a.is_dir() and not b.exists(),"invalid isolated replica");subprocess.run(["/usr/bin/cp","-a","--reflink=auto",a,b],check=True)
def provision(o,bank,out):
    env=ENV|{"CARGO_NET_OFFLINE":"false"}
    with (out/"cargo-fetch.stdout").open("xb") as so,(out/"cargo-fetch.stderr").open("xb") as se:
        subprocess.run([ARGS[0],"fetch","--locked"],cwd=SRC,env=env,stdout=so,stderr=se,check=True,timeout=1200)
    guard(history()[0]==CASE["A_tree"],"fetch changed uv")
    reg=o.registry(CARGO_HOME);guard(reg==CASE["registry"],"registry archive/entry checksums");save(out/"registry.json",reg)
    cp(SRC,bank/"uv");cp(CARGO_HOME/"registry",bank/"registry");erase(SRC,TARGET,CARGO_HOME,HOME)
def reset(bank,state,delta):
    erase(SRC,TARGET,CARGO_HOME,HOME)
    cp(bank/"uv",SRC);HOME.mkdir();CARGO_HOME.mkdir();cp(bank/"registry",CARGO_HOME/"registry")
    if state=="B":edit(delta)
    else:guard(state=="A" and history()==(CASE["A_tree"],delta),"cold reset")
def freeze():
    seed=ROOT/"seed";guard(not seed.exists(),"reused seed");seed.mkdir()
    for p in (SRC,TARGET,CARGO_HOME,HOME):p.rename(seed/p.name)
    return seed
def seed_state(base,role):
    # Compare contents and restored relative namespace, ignoring volatile allocation and atime.
    parts=[];epochs=[];tally=0
    for key in ("uv","target","cargo","home"):
        tree=base/key
        for path in sorted(tree.rglob("*")):
            st=path.lstat();p=str(path.relative_to(base));mode=st.st_mode
            if stat.S_ISREG(mode):
                ident=[st.st_size,filesha(path)];tally+=st.st_size
                if key=="target" and path.name in ("dep-graph.bin","query-cache.bin"):
                    with path.open("rb") as f:
                        head=f.read(7);guard(len(head)==7 and head[:4]==b"RSIC","unexpected incremental file");v=f.read(head[6]).decode()
                    epoch=int.from_bytes(head[4:6],"little");guard(epoch==P["roles"][role]["epoch"] and v,"incorrect active uv incremental epoch");epochs.append([p,epoch,v])
            elif stat.S_ISLNK(mode):ident=os.readlink(path)
            else:guard(stat.S_ISDIR(mode),"unrestorable nonfile A state");ident=None
            parts.append([p,mode,st.st_mtime_ns,ident])
    guard(len(epochs)>=4 and any("/uv-" in p or "/uv/" in p for p,_,_ in epochs),"no genuine uv cache")
    return {"tree_sha256":digest(canon(parts)),"paths":len(parts),"regular_bytes":tally,"actual_incremental_headers":epochs}
def restore(seed,delta,role,stamp):
    erase(SRC,TARGET,CARGO_HOME,HOME)
    for p in (SRC,TARGET,CARGO_HOME,HOME):cp(seed/p.name,p)
    guard(seed_state(ROOT,role)==stamp,"restored A differs in source, home, Cargo cache or any target byte");edit(delta)
def choose(role,bank,installed):
    guard(role in P["roles"],"unexpected compiler")
    if SDK.exists():
        old,=[k for k in installed if not (bank/("sdk-"+k)).exists()];SDK.rename(bank/("sdk-"+old))
    (bank/("sdk-"+role)).rename(SDK)
    for rel,sha in installed[role]["runtime"].items():guard(filesha(SDK/rel)==sha,("SDK identity",rel))
    guard(filesha(SDK/"bin/cargo")==P["signed_cargo_sha256"] and subprocess.check_output([RUSTC,"--print","sysroot"],env=ENV,text=True).strip()==str(SDK),"canonical SDK/Cargo")
