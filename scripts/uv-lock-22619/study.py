"""One production compiler on a real edit. The off-clock forensic capture is independent of ordinary results."""
import gzip,hashlib,importlib.util,json,os,re,shlex,shutil,subprocess,sys,time,tomllib
from pathlib import Path
H=Path(__file__).resolve().parent
sys.path.insert(0,str(H))
import sdk,witness
P=sdk.CFG;U=P["uv"];A=U["A"];B=U["B"];write=sdk.save;read=sdk.read;sha=sdk.sha
def need(value,why):
    if not value:raise ValueError(why)
def canonical(v):return json.dumps(v,sort_keys=True,separators=(",",":")).encode()
def digest(b):return hashlib.sha256(b).hexdigest()
def module(path,name):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
def roots():
    w=sdk.workspace();return w,w/"trait-results",Path(os.environ["RUNNER_TEMP"]).resolve()/"uv-lock-22619"
def storage(p,floor):
    free=shutil.disk_usage(p).free;need(free>floor,("runner disk",str(p),free,floor));return free
def event_values(e,dispatch,head):
    ref="refs/heads/"+P["branch"];repo=P["repo"];workflow=repo+"/.github/workflows/ci.yml@"+ref
    need(__debug__ and e["GITHUB_EVENT_NAME"]=="workflow_dispatch" and e["GITHUB_REPOSITORY"]==repo and e["GITHUB_REPOSITORY_ID"]=="1319437234" and e["GITHUB_RUN_ATTEMPT"]=="1" and e["GITHUB_RUN_ID"].isdecimal(),"wrong GitHub event/repository/attempt")
    need(e["GITHUB_REF"]==ref and e["GITHUB_WORKFLOW_REF"]==workflow and re.fullmatch("[0-9a-f]{40}",head) and head==e["GITHUB_SHA"]==e["GITHUB_WORKFLOW_SHA"]==e["REVIEWED_HEAD"],"wrong workflow/reviewed checkout")
    need(dispatch["repository"]["full_name"]==repo and dispatch["repository"]["private"] is True and dispatch["repository"]["id"]==1319437234 and dispatch["ref"] in (ref,P["branch"]) and dispatch["inputs"]=={"reviewed_head":head},"changed dispatch inputs")
    return {"repository_id":1319437234,"run_id":e["GITHUB_RUN_ID"],"attempt":1,"head":head,"workflow":workflow}
def admission():
    w,out,_=roots();head=git(w,"rev-parse","HEAD").decode().strip();row=event_values(os.environ,read(Path(os.environ["GITHUB_EVENT_PATH"])),head)
    need(not git(w,"diff","--quiet") and not git(w,"diff","--cached","--quiet"),"changed tracked workflow checkout")
    wf=w/".github/workflows/ci.yml";need(sha(wf)==P["workflow_sha256"] and git(w,"hash-object",str(wf)).strip()==git(w,"rev-parse","HEAD:.github/workflows/ci.yml").strip(),"workflow bytes differ from registration")
    write(out/"event.json",dict(row,workflow_sha256=sha(wf)))
def earlier():
    w,_,_=roots();base=w/"previous/scripts/uv-resolver-whole-pmu";need(sha(base/"run.py")==P["old_files"]["run.py"],"prior runner source")
    sys.path.insert(0,str(base));return module(base/"run.py","previous_runner")
def calibrate():
    sdk.configure();w,out,work=roots();out.mkdir(exist_ok=True);work.mkdir()
    storage(work,P["required_free_gib"]<<30);r=earlier();r.verified_checkouts(w);host=r.cpu_receipt(out);write(out/"host.json",host)
    root=r.meter_root(work.parent);root.mkdir(parents=True)
    subprocess.run([sys.executable,"-IB",w/"pilot/scripts/branch-return-pmu/meter.py",w/"calibrator",w/"observers"],check=True,timeout=480)
    ready=read(root/"meter-ready.json");plain=root/"observers/plain"
    need(ready["boot"]==host["boot"] and ready["affinity"]==host["cpus"] and ready["observer"]==r.P["observer"] and ready["calibrator"]==r.P["calibrator"] and Path(ready["plain"])==plain,"counter authority/boot/mask")
    rows=[read(p)for p in sorted((root/"calibration").glob("whole-*-*.json"))]
    need(len(rows)==28 and all(q["code"]==q["event_errno"]==0 and q["running"]==q["enabled"]>0 and q["instructions"]>0 for q in rows),"fork/thread/exec controls")
    shutil.copytree(root,out/"pmu-calibration");write(out/"calibration.json",{"ready":ready,"sha256":sha(plain),"controls":len(rows)})
def intake():
    w,out,work=roots();sdk.acquire(out,work/"media")
def git(src,*args):
    return subprocess.check_output(["git","-c","core.autocrlf=false","-c","core.fsmonitor=false","-C",src,*args],cwd=src,env={"PATH":"/usr/bin:/bin","LC_ALL":"C","GIT_CONFIG_NOSYSTEM":"1","GIT_NO_LAZY_FETCH":"1"})
def check_source(src,rev):
    need(git(src,"rev-parse","HEAD").decode().strip()==A and not git(src,"diff","--cached","--name-only"),"A HEAD/index")
    need(not git(src,"ls-files","--others","--exclude-standard"),"untracked source")
    patch=git(src,"diff","--binary","--full-index","--no-ext-diff")
    need((rev==A and not patch)or(rev==B and digest(patch)==U["patch_sha256"]),"whole unstaged edit")
    need(git(src,"hash-object",str(src/U["file"])).decode().strip()==U["blobs"][int(rev==B)] and sha(src/"Cargo.lock")==U["lock_sha256"],"source/lock")
def source(src):
    need(git(src,"rev-parse",B+"^").decode().strip()==A and git(src,"rev-parse",A+"^{tree}",B+"^{tree}").decode().splitlines()==U["trees"],"source DAG/two trees")
    need(git(src,"rev-parse",U["tag"]+"^{}").decode().strip()==U["tag_commit"] and [git(src,"describe","--tags","--abbrev=9",r).decode().strip()for r in(A,B)]==U["describe"],"actual historical release tag")
    need(git(src,"diff","--name-only",A,B).decode().splitlines()==[U["file"]] and digest(git(src,"diff","--binary","--full-index","--no-ext-diff",A,B))==U["patch_sha256"],"historical complete diff")
    git(src,"checkout","-q","--detach",A);check_source(src,A)
def material(src,home):
    expected=read(H/"registry.json");need(len(expected)==654 and sha(H/"registry.json")==P["registry_sha256"],"bank registration")
    lock=tomllib.loads((src/"Cargo.lock").read_text())["package"];locked={(r["name"],r["version"]):r["checksum"]for r in lock if "source"in r}
    need(all(r.get("source","registry+https://github.com/rust-lang/crates.io-index")=="registry+https://github.com/rust-lang/crates.io-index"for r in lock)and len(locked)==654,"lock provenance")
    cache,=(home/"registry/cache").iterdir();idx,=(home/"registry/index").iterdir()
    for n,v,ck,size,ri in expected:
        k=n.lower();rel="1/"+k if len(k)==1 else "2/"+k if len(k)==2 else "3/"+k[0]+"/"+k if len(k)==3 else k[:2]+"/"+k[2:4]+"/"+k
        row,=[o for x in (idx/".cache"/rel).read_bytes().split(b"\0")if x.startswith(b"{")and(o:=json.loads(x))["vers"]==v]
        file=cache/(n+"-"+v+".crate")
        need(row["name"]==n and row["cksum"]==locked[(n,v)]==ck and digest(canonical(row))==ri and file.stat().st_size==size and sha(file)==ck,("locked registry archive/index",n,v))
    return {"packages":len(locked),"sha256":P["registry_sha256"]}
def fileset(base):
    h=hashlib.sha256();size=count=0
    for p in sorted(base.rglob("*")):
        st=p.lstat()
        if p.is_symlink():item=["link",os.readlink(p)]
        elif p.is_file():item=["file",sha(p)];size+=st.st_size
        elif p.is_dir():continue
        else:raise ValueError(("special target entry",p))
        h.update(canonical([str(p.relative_to(base)),st.st_mode,st.st_mtime_ns,*item])+b"\n");count+=1
    need(count>20,"empty parent");return {"sha256":h.hexdigest(),"files":count,"bytes":size}
def clone(parent,child):
    need(parent.is_dir()and not child.exists(),"checkpoint copy");subprocess.run(["cp","-a","--reflink=auto","--sparse=always",parent,child],check=True)
def packed(p,dest,rel):
    need(1024<p.stat().st_size<384<<20,("forensics budget",p))
    with p.open("rb")as a,gzip.open(dest,"wb",compresslevel=1)as b:shutil.copyfileobj(a,b,1<<20)
    return {"path":str(p.relative_to(rel)),"bytes":p.stat().st_size,"sha256":sha(p),"compressed_sha256":sha(dest)}
def graph(target,argv,dest):
    inc=None
    for i,arg in enumerate(argv[:-1]):
        code=argv[i+1] if arg=="-C" else arg[2:] if arg.startswith("-C")else ""
        if code.startswith("incremental="):inc=Path(code.split("=",1)[1])
    need(inc and inc.resolve()==(target/"debug/incremental").resolve(),"actual consumer incremental path")
    outdir=Path(argv[argv.index("--out-dir")+1]).resolve(strict=True);need(outdir.is_relative_to(target),"wrong consumer output dir")
    rmeta,=outdir.glob("libuv_lock-*.rmeta")
    rustc=Path(argv[0]);env={"PATH":"/usr/bin:/bin","LD_LIBRARY_PATH":str(rustc.parent.parent/"lib"),"RUSTC_BOOTSTRAP":"1","LC_ALL":"C"}
    dump=subprocess.check_output([rustc,"-Zls=root",rmeta],env=env,cwd=target,timeout=60)
    (dest/"uv-lock-root.txt").write_bytes(dump)
    name,=re.findall(rb"^name (uv_lock-[0-9a-f]{16})$",dump,re.M)
    sid,=re.findall(rb"^private hash [0-9a-f]{32} stable_crate_id StableCrateId\((\d+)\)$",dump,re.M)
    pub,=re.findall(rb"^public_hash ([0-9a-f]{32})$",dump,re.M)
    need(rmeta.name=="lib"+name.decode()+".rmeta","consumer crate/rmeta")
    n=int(sid);suffix=""
    for _ in range(13):
        n,j=divmod(n,36);suffix="0123456789abcdefghijklmnopqrstuvwxyz"[j]+suffix
    need(n==0,"consumer stable crate id width")
    base=inc/("uv_lock-"+suffix);session,=[p for p in base.glob("s-*")if not p.name.endswith("-working")and(p/"ohm-check-session").is_file()]
    g=session/"dep-graph.bin";cg=session/"ohm-check-dep-graph.bin";q=session/"query-cache.bin"
    need(all(p.is_file() and not p.is_symlink() for p in (g,cg,q)) and q.stat().st_size>0 and(g.samefile(cg)or sha(g)==sha(cg)),"unbound current native graph")
    ver=b"1.99.0-dev (f12924d91 2026-11-01) (ohm-1.99.0-23)"
    with g.open("rb")as f:
        need(f.read(6)==b"RSIC"+P["sdk_media"]["cache_epoch"].to_bytes(2,"little")and f.read(1)==bytes([len(ver)])and f.read(len(ver))==ver,"wrong graph producer")
        f.seek(-13,2);need(f.read()==b"rust-end-file","truncated graph")
    write(dest/"graph.json",dict(packed(g,dest/"uv-lock.dep-graph.bin.gz",target),rmeta=str(rmeta.relative_to(target)),rmeta_sha256=sha(rmeta),stable_crate_id=int(sid),public_hash=pub.decode(),epoch=P["sdk_media"]["cache_epoch"]))

def running_rustcs(stderr,rustc):
    cmds=[]
    for line in stderr.decode().splitlines():
        m=re.match(r"^\s*Running `(.*)`$",line)
        if not m:continue
        vals=shlex.split(m.group(1));ids=[i for i,v in enumerate(vals) if v==str(rustc)]
        if not ids:continue
        need(len(ids)==1,"ambiguous rustc");args=vals[ids[0]:]
        if "--crate-name" in args:cmds.append(args)
    return cmds
def parse_argv(stderr,rustc):
    cmds=running_rustcs(stderr,rustc)
    argv,=[v for v in cmds if v[v.index("--crate-name")+1]=="uv_lock"]
    need("--crate-type" in argv and argv[argv.index("--crate-type")+1]=="lib" and any(v.startswith("--emit=")and set(v[7:].split(","))=={"dep-info","metadata"}for v in argv),"metadata-only genuine uv_lock")
    need(not any(a=="--cfg"and argv[i+1].startswith("feature=")for i,a in enumerate(argv[:-1])),"uv-lock feature drift")
    return argv,cmds
def execution(receipt,original,flags):
    row=read(receipt);pid=row.get("pid");need(type(pid)is int and pid>0 and receipt.name==str(pid)+".json" and set(row)=={"pid","original","executed"} and row["original"]==original and row["executed"]==original+flags,"wrong selected real compiler invocation")
    return row
def observe(data,err,rustc,target,members):
    events=[json.loads(x)for x in data.splitlines()];need(events[-1].get("success")is True and events[-1]["reason"]=="build-finished","typed completion")
    roster=[];wm={};direct=0;diags=[]
    for e in events:
        if e["reason"]=="compiler-message" and e["package_id"]in members:diags.append(e)
        if e["reason"]!="compiler-artifact":continue
        names=[str(Path(n).relative_to(target))for n in e["filenames"]]
        roster.append([e["package_id"],e["target"]["name"],e["target"]["kind"],e["features"],e["profile"],names])
        if e["package_id"]not in members:continue
        if e["target"]["name"]=="uv_lock" and e["target"]["kind"]==["lib"]:
            direct+=1;need(e["features"]==[] and not e["fresh"],"real uv-lock provider/feature")
        for n in names:
            if n.endswith(".rmeta"):wm[n]=[(target/n).stat().st_size,sha(target/n)]
    need(direct==1 and any("libuv_lock-"in n for n in wm)and any("libuv_distribution_types-"in n for n in wm),"workspace products")
    av,cmds=parse_argv(err,rustc)
    return {"units":sorted(roster,key=canonical),"workspace_rmeta":wm,"workspace_diagnostics":sorted(diags,key=canonical),"argv":av,"rustcs":cmds}
def live_meta(target,ref):
    return {n:[(target/n).stat().st_size,sha(target/n)]for n in ref}
def same_result(left,right):
    return all(left[k]==right[k]for k in("units","workspace_rmeta","workspace_diagnostics"))
def progress(stderr):
    return sorted(m.decode()for m in re.findall(rb"^\s*(?:Checking|Compiling) ([\w-]+) v",stderr,re.M))
class Study:
    def __init__(self):
        sdk.configure();w,out,work=roots();self.out=out;self.work=work;self.src=w/"uv-source";self.target=work/"target"
        self.linked=work/"linked-test";self.checkpoint=work/"parent-snapshot";self.keys=work/"key-profile";self.keys.mkdir()
        roles=sdk.install(out,work/"media",work/"installed");self.cargo=roles["signed"]/"bin/cargo";self.compiler=roles["rebased"];self.rustc=self.compiler/"bin/rustc"
        need(sha(self.cargo)==P["sdk"]["signed"]["cargo"] and sha(self.rustc)==P["sdk"]["rebased"]["rustc"],"effective toolchain")
        self.cpu=earlier().cpu_receipt(out);need(self.cpu==read(out/"host.json"),"boot/CPU changed")
        source(self.src);self.changed=self.src/U["file"];self.parent_time=self.changed.stat().st_mtime_ns
        self.old=self.changed.read_bytes();self.new=git(self.src,"show",B+":"+U["file"]);self.home=work/"cargo-home"
        for item in(self.home,work/"home",work/"tmp"):item.mkdir()
        self.env={"PATH":str(self.compiler/"bin")+":/usr/bin:/bin","LD_LIBRARY_PATH":str(self.compiler/"lib"),"RUSTC":str(self.rustc),"RUSTDOC":str(self.compiler/"bin/rustdoc"),"HOME":str(work/"home"),"TMPDIR":str(work/"tmp"),"CARGO_HOME":str(self.home),"CARGO_TARGET_DIR":str(self.target),"CARGO_NET_OFFLINE":"true","CARGO_TERM_COLOR":"never","LC_ALL":"C","LANG":"C"}
        write(out/"environment.json",self.env);self.command("material","fetch",[self.cargo,"fetch","--locked"],self.env|{"CARGO_NET_OFFLINE":"false"})
        write(out/"registry-verified.json",material(self.src,self.home))
        data,_=self.command("material","metadata",[self.cargo,"metadata","--no-deps","--locked","--offline","--format-version=1"])
        meta=json.loads(data);self.members=set(meta["workspace_members"]);pkg,=[p for p in meta["packages"]if p["name"]=="uv-lock"]
        need(pkg["id"]in self.members and not pkg["features"] and any(t["name"]=="uv_lock"and t["kind"]==["lib"]for t in pkg["targets"]),"real target/features")
    def command(self,label,name,args,env=None,timeout=900):
        out=self.out/label;out.mkdir(exist_ok=True);cmd=list(map(str,args));write(out/(name+"-command.json"),cmd)
        need(sorted(os.sched_getaffinity(0))==self.cpu["cpus"] and Path("/proc/sys/kernel/random/boot_id").read_text().strip()==self.cpu["boot"],"changed mask or boot")
        start=time.monotonic_ns();p=subprocess.run(cmd,cwd=self.src,env=self.env if env is None else env,capture_output=True,timeout=timeout);stop=time.monotonic_ns()
        (out/(name+".stdout")).write_bytes(p.stdout);(out/(name+".stderr")).write_bytes(p.stderr)
        write(out/(name+"-exit.json"),{"exit":p.returncode,"ns":stop-start,"clock":"monotonic_ns","scope":name})
        need(p.returncode==0,(label,name,p.returncode,p.stderr.decode(errors="replace")[-1800:]));return p.stdout,p.stderr
    def clean(self,path):
        need(path in(self.target,self.linked)and path.parent==self.work and not path.is_symlink(),"private scratch only")
        if path.exists():shutil.rmtree(path)
    def phase(self,rev):
        self.changed.write_bytes(self.old if rev==A else self.new)
        if rev==A:os.utime(self.changed,ns=(self.parent_time,self.parent_time))
        check_source(self.src,rev)
    def restore(self):
        self.clean(self.target);self.phase(A);clone(self.checkpoint,self.target);need(fileset(self.target)==self.seal,"wrong checkpoint")
        probe=self.checkpoint/self.consumer_member;other=self.target/self.consumer_member
        need(probe.stat().st_ino!=other.stat().st_ino,"cross-visit target inode");self.phase(B)
    def behavior(self,rev,label,fresh):
        if fresh:self.clean(self.linked)
        args=[self.cargo,"test","--locked","--offline","-j8","-p","uv-distribution-types","--lib",P["test"],"--","--exact"]
        stdout,_=self.command(label,"linked-upstream-test",args,self.env|{"CARGO_TARGET_DIR":str(self.linked)},1200)
        need(("test "+P["test"]+" ... ok")in stdout.decode()and re.search(rb"test result: ok\. 1 passed; 0 failed;",stdout),"actual single upstream behavioral test")
        check_source(self.src,rev)
    def typed(self,label,rev,keyed=False):
        check_source(self.src,rev)
        where=self.out/label;where.mkdir(exist_ok=True);execdir=where/"executions";env=self.env
        flags=["-Zself-profile="+str(self.keys),"-Zself-profile-events="+P["profile"]]
        if keyed:
            need(not list(self.keys.iterdir()),"stale profile");execdir.mkdir()
            wrapper=H/"profile-wrapper.py";need(os.access(wrapper,os.X_OK),"registered wrapper not executable")
            env=self.env|{"RUSTC_WRAPPER":str(wrapper),"OHM_EXPECTED_RUSTC":str(self.rustc),"OHM_PROFILE_DIR":str(self.keys),"OHM_PROFILE_EVENTS":P["profile"],"OHM_PROFILE_ARGV":str(execdir)}
        args=[self.cargo,*P["command"],"-vv","--message-format=json"]
        stdout,stderr=self.command(label,"typed",args,env);form=observe(stdout,stderr,self.rustc,self.target,self.members)
        if keyed:
            receipt,=execdir.glob("*.json");actual=execution(receipt,form["argv"],flags)
            form.update(pid=actual["pid"],executed_argv=actual["executed"])
        write(where/"typed.json",form)
        for name in ("uv_lock","uv_distribution_types"):
            product,=[self.target/k for k in form["workspace_rmeta"]if Path(k).name.startswith("lib"+name+"-")]
            packed(product,where/(name+".rmeta.gz"),self.target)
        if keyed:
            graph(self.target,form["argv"],where)
            profile,=self.keys.iterdir();match=re.fullmatch(r"uv_lock-([0-9]+)\.mm_profdata",profile.name)
            need(match and int(match[1])==form["pid"],"missing unique matching PID of selected consumer")
            write(where/"profile.json",dict(packed(profile,where/"uv-lock.mm_profdata.gz",self.keys),pid=int(match[1])));profile.unlink()
        witness.run("A" if rev==A else "B",self.rustc,form["argv"],self.src,where/"witness",self.env)
        return form
    def plain(self,label,rev,expected,mode="plain"):
        check_source(self.src,rev);args=[str(self.cargo),*P["command"]]
        if mode=="pmu":
            cal=read(self.out/"calibration.json");meter=Path(cal["ready"]["plain"])
            need(sha(meter)==cal["sha256"] and cal["ready"]["boot"]==self.cpu["boot"],"changed calibrated observer")
            clock=self.out/label/"whole-clock.json";args=[str(meter),str(clock),*args]
        stdout,err=self.command(label,mode,args);need(not stdout,"ordinary cargo stdout")
        dirty=progress(err);need("uv-lock"in dirty and "uv-distribution-types"in dirty,"real dirty consumer and definition")
        write(self.out/label/(mode+"-progress.json"),dirty)
        actual=live_meta(self.target,expected["workspace_rmeta"]);write(self.out/label/(mode+"-workspace-rmeta.json"),actual)
        need(actual==expected["workspace_rmeta"],"ordinary metadata differs from typed/cold")
        if mode=="plain":graph(self.target,expected["argv"],self.out/label)
        else:
            m=module(roots()[0]/"pilot/scripts/branch-return-pmu/meter.py","measured_counter")
            row=m.clock(clock,0);need(row["enabled"]==row["running"]>0,"multiplexed inherited instructions");return row
        return read(self.out/label/(mode+"-exit.json"))
def run():
    s=Study();O=s.out
    a=s.typed("ordinary-A",A);s.consumer_member,=[k for k in a["workspace_rmeta"]if Path(k).name.startswith("libuv_lock-")];s.behavior(A,"ordinary-A",True)
    s.clean(s.target);s.plain("ordinary-A",A,a)
    s.seal=fileset(s.target);write(O/"parent-snapshot.json",s.seal)
    storage(s.work,3*s.seal["bytes"]+(8<<30));s.target.rename(s.checkpoint)
    s.restore();b=s.typed("ordinary-warm-B",B);s.behavior(B,"ordinary-warm-B",False)
    s.clean(s.target);cold=s.typed("ordinary-cold-B",B);s.behavior(B,"ordinary-cold-B",True)
    warm_cold={"units_equal":b["units"]==cold["units"],"diagnostics_equal":b["workspace_diagnostics"]==cold["workspace_diagnostics"],"rmeta_differences":{k:[b["workspace_rmeta"].get(k),cold["workspace_rmeta"].get(k)]for k in sorted(b["workspace_rmeta"].keys()|cold["workspace_rmeta"].keys())if b["workspace_rmeta"].get(k)!=cold["workspace_rmeta"].get(k)}}
    write(O/"ordinary-warm-cold.json",warm_cold)
    need(a["units"]==b["units"] and same_result(b,cold),"changed workload/independent B metadata or diagnostic mismatch")
    defining=[k for k in b["workspace_rmeta"]if "libuv_distribution_types-"in k];need(len(defining)==1 and a["workspace_rmeta"][defining[0]]!=b["workspace_rmeta"][defining[0]],"unchanged defining crate unexpectedly")
    s.clean(s.target);s.plain("ordinary-cold-B",B,cold)
    s.restore();wall=s.plain("ordinary-warm-B",B,b)
    s.restore();meter=s.plain("ordinary-warm-B-pmu",B,b,"pmu")
    actual=progress((O/"ordinary-warm-B/typed.stderr").read_bytes())
    need(actual==read(O/"ordinary-warm-B/plain-progress.json")==read(O/"ordinary-warm-B-pmu/pmu-progress.json"),"different first-edit native/typed/PMU progress roster")
    need(fileset(s.checkpoint)==s.seal,"parent changed across first visits")
    write(O/"qualified-observations.json",{"role":P["source_rust"],"signed_cargo_sha256":sha(s.cargo),"uv":U,"normal_first_edit_wall_ns":wall["ns"],"separate_whole_command_userspace_instructions":meter["instructions"],"counter":meter,"dirty_packages":actual,"workspace_rmeta":len(b["workspace_rmeta"]),"complete_units":len(b["units"]),"repetitions":1,"comparison":None,"scope":"one production compiler, independent restored first-edits; no effect size"})
    # A separate Cargo check-mode diagnostic only. Finish all three products before
    # deciding if provider keys and normal artifacts can be related across modes.
    s.clean(s.target);s.phase(A);ka=s.typed("keyed-A",A,True);s.phase(B);kb=s.typed("keyed-warm-B",B,True)
    s.clean(s.target);kc=s.typed("keyed-cold-B",B,True)
    extra=["-Zself-profile="+str(s.keys),"-Zself-profile-events="+P["profile"]]
    alignment={}
    for label,normal,profiled in (("A",a,ka),("warm-B",b,kb),("cold-B",cold,kc)):
        argv=profiled["argv"]
        alignment[label]={"units":normal["units"]==profiled["units"],"workspace_rmeta":normal["workspace_rmeta"]==profiled["workspace_rmeta"],"workspace_diagnostics":normal["workspace_diagnostics"]==profiled["workspace_diagnostics"],"all_original_rustcs":sorted(normal["rustcs"])==sorted(profiled["rustcs"]),"only_selected_extra_flags":argv==normal["argv"] and profiled["executed_argv"]==normal["argv"]+extra}
    ok=same_result(kb,kc)and all(all(row.values())for row in alignment.values())
    write(O/"keyed-ordinary-alignment.json",{"checks":alignment,"keyed_warm_cold_full":same_result(kb,kc),"eligible_for_direct_ordinary_attribution":ok,"limitation":"Prior reader and executed provider are an upper bound unless the actual first veto is independently proven."})
    # A refusal here keeps the qualified separate ordinary result and the raw profile.
    need(ok,"independent keyed diagnostic differs from the ordinary workspace/consumer")
if __name__=="__main__":
    need(__debug__ and len(sys.argv)==2,"optimized mode/usage")
    admission();{"calibrate":calibrate,"intake":intake,"run":run}[sys.argv[1]]()
