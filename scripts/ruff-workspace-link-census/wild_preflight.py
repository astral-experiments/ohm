"""Measure one physically requested Wild link with its original, source-pinned observation prototype."""
from pathlib import Path
from itertools import permutations
import hashlib
import json
import mmap
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bisect330 as b
import census
import paired
from constructors_inputs import native_value,physical

H=Path(__file__).resolve().parent
M=H/"wild-diagnostic"
W,E,SDK=census.paths()
D=W/"native-diagnostic"
R=E/"preflight"
V="e856d81f6683cad80b9fe0ebf1a0c3c403c6fe11"
T="0c43bc675e3d3df3e3b0d4692638822ee34f8a8d"
LINK=SDK/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
STOCK="0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
SCHEDULE=(("stock","off","active"),("off","active","stock"),("active","stock","off"),
          ("active","off","stock"),("off","stock","active"),("stock","active","off"))


def put(p,v):return census.put(p,v)
def load(p):return json.loads(p.read_bytes())


def inject(src):
    dst=src/"libwild/src/observation_replay.rs"
    assert census.sha(M/"install-hooks.py")=="e49e12cb9636886512421a54247ee6ee6e324da64de5b46186e7efe087cda6a9"
    assert census.sha(M/"observation_replay.rs")=="d03d7fef6872bc3246e4aa98bbfb7c5dac3504ffb5847540f162cbacfe57bf8c"
    shutil.copyfile(M/"observation_replay.rs",dst)
    subprocess.run([sys.executable,"-IB",M/"install-hooks.py",src],check=True)
    with dst.open("a") as f:
        f.write('''\n// Isolated QA rendezvous for the same loader/resolver cut on full and returning links.
pub(crate) fn qa_checkpoint(cut: &str) {
    let Some(root)=std::env::var_os("OHM_DIAGNOSTIC_BARRIER") else { return };
    let dir=PathBuf::from(root);
    std::fs::write(dir.join("entered"),format!("{} {cut}\\n",std::process::id())).unwrap();
    let mut b=[0u8;1];File::open(dir.join("continue")).unwrap().read_exact(&mut b).unwrap();
    assert_eq!(b,[1]);
}\n''')
    lib=src/"libwild/src/lib.rs";s=lib.read_text()
    for old,new in [
        ("            file_loader.verify_inputs_unchanged()?;\n            output.publish_proven_bytes","            observation_replay::qa_checkpoint(\"receipt-hit\");\n            file_loader.verify_inputs_unchanged()?;\n            output.publish_proven_bytes"),
        ("        let layout_rules = layout_rules_builder.build::<P>(args);","        observation_replay::qa_checkpoint(\"full-layout\");\n        let layout_rules = layout_rules_builder.build::<P>(args);")]:
        assert s.count(old)==1;s=s.replace(old,new)
    lib.write_text(s)


def build(src):
    assert census.git(src,"rev-parse","HEAD")==V and census.git(src,"rev-parse","HEAD^{tree}")==T and not census.git(src,"status","--porcelain=v1")
    assert shutil.disk_usage(W).free>40*2**30 and census.sha(LINK)==STOCK
    D.mkdir();R.mkdir()
    env=census.environment(W,SDK);put(D/"base-env.json",env)
    source=D/"source"
    shutil.copytree(src,source,symlinks=True,ignore=shutil.ignore_patterns(".git"))
    before={str(p.relative_to(source)):census.sha(p) for p in source.rglob("*") if p.is_file()}
    inject(source)
    changes={str(p.relative_to(source)):[before.get(str(p.relative_to(source))),census.sha(p)] for p in source.rglob("*") if p.is_file() and before.get(str(p.relative_to(source)))!=census.sha(p)}
    assert set(changes)=={"libwild/src/"+n for n in ("lib.rs","fs.rs","file_writer.rs","args.rs","input_data.rs","observation_replay.rs")}
    e=dict(env,HOME=str(D/"build-home"),CARGO_HOME=str(D/"cargo-home"),CARGO_BUILD_BUILD_DIR=str(D/"build"),CARGO_TARGET_DIR=str(D/"target"))
    Path(e["HOME"]).mkdir()
    cmd=["cargo","+ohm","-Zohm-defaults=no","build","--locked","--release","-p","wild-linker","--bin","wild","-j8"]
    with (R/"build.log").open("xb") as f:ret=subprocess.run(cmd,cwd=source,env=e,stdout=f,stderr=f,timeout=2400)
    if ret.returncode:print((R/"build.log").read_text()[-9000:],flush=True)
    assert ret.returncode==0
    path=D/"matched-wild";shutil.copy2(D/"target/release/wild",path);assert path.read_bytes()[:4]==b"\x7fELF"
    put(R/"build.json",{"upstream":V,"tree":T,"changed_source":changes,"cargo":cmd,"sdk":load(E/"identity.json")["sdk"]["bin/rustc"][0],"official_wild":STOCK,"matched_wild":census.sha(path),"matched_bytes":path.stat().st_size,"lock":census.sha(source/"Cargo.lock")})
    print("wild build",census.sha(path),flush=True)


def measured(f):
    if (f/"counter.json").exists():
        x=load(f/"counter.json");assert x["status"]==0 and x["instructions"]>0 and x["enabled"]>0 and x["running"]>=0.99*x["enabled"]
        return x["instructions"]
    profiles=list(f.glob("callgrind.*"));assert profiles
    vals=[]
    for p in profiles:
        data=p.read_text(errors="strict");names=re.search(r"^events: (.+)$",data,re.M)[1].split()
        value=re.search(r"^totals: ([0-9 ]+)$",data,re.M)
        if value is None:value=re.search(r"^summary: ([0-9 ]+)$",data,re.M)
        assert value is not None,(p,data[-500:]);vals.append(int(value[1].split()[names.index("Ir")]))
    return sum(vals)


def calibrate():
    count=D/"count";toy=D/"toy";v=shutil.which("valgrind")
    for file,exe,opt in [("count.c",count,[]),("calibrate.c",toy,["-pthread"])]:
        subprocess.run(["/usr/bin/cc","-O2","-Wall",*opt,M/file,"-o",exe],check=True)
    base=R/"calibration";base.mkdir()
    probe=subprocess.run([count,base/"hardware-entry.json",toy,toy,"empty"],capture_output=True);(base/"hardware.stderr").write_bytes(probe.stderr)
    assert probe.returncode in (0,126)
    sel="hardware" if probe.returncode==0 else "callgrind";data={}
    for case in ("empty","loop","thread","fork"):
        f=base/case;f.mkdir()
        args=[count,f/"counter.json",toy,toy,case] if sel=="hardware" else [v,"--tool=callgrind","--trace-children=no","--callgrind-out-file="+str(f/"callgrind.%p"),"--log-file="+str(f/"valgrind.%p"),toy,case]
        subprocess.run(args,check=True)
        data[case]=measured(f)
    for case in ("loop","thread","fork"):assert 3_800_000<=data[case]-data["empty"]<=4_400_000,(sel,data)
    put(base/"verified.json",{"counter":sel,"measured":data,"toy":census.sha(toy),"launcher":census.sha(count),"valgrind":subprocess.check_output([v,"--version"],text=True).strip()})
    return sel,v


def worker(src,work,label,mode):
    assert work==W and os.geteuid()==(W/"cargo-child").stat().st_uid!=0
    conf=load(D/"route.json");assert os.readlink("/proc/self/ns/mnt")!=conf["namespace"]
    mount=subprocess.check_output(["findmnt","-rn","-T",conf["gcc"],"-o","TARGET,SOURCE,FSTYPE,OPTIONS"],text=True).strip()
    assert 'overlay' in mount and 'ro,' in mount
    phase=R/label;put(phase/"view.json",{"uid":os.getuid(),"mnt":os.readlink("/proc/self/ns/mnt"),"gcc":mount,"provider":physical(Path(conf["gcc"])/"libutil.so")})
    env=dict(load(D/"base-env.json"),WILD_DIAG_JOB=str(D),WILD_DIAG_PHASE=str(phase),WILD_DIAG_SUBJECT=mode)
    if "-count" not in mode:
        res=b.visit(phase/"native",b.CONSTRUCTORS,src,env,"constructors")
    else:
        with (phase/"stdout.jsonl").open("xb") as out,(phase/"stderr").open("xb") as err:
            ret=subprocess.run(b.CONSTRUCTORS,cwd=src,env=env,stdout=out,stderr=err,timeout=300)
        assert ret.returncode==0,(phase,(phase/"stderr").read_text()[-4000:])
        rows=[json.loads(l) for l in (phase/"stdout.jsonl").read_bytes().splitlines()];assert rows[-1]=={"reason":"build-finished","success":True}
        arts=[r for r in rows if r["reason"]=="compiler-artifact"];a,=[r for r in arts if r["target"]["name"]=="constructors"]
        assert len(arts)==53 and [r["target"]["name"] for r in arts if not r["fresh"]]==["constructors"]
        exe=Path(a["executable"]);native=subprocess.run([exe,"--exact","main","--nocapture"],cwd=src,env=env,capture_output=True,check=True);(phase/"native.stdout").write_bytes(native.stdout)
        res={"exit":0,"typed":len(arts),"dirty":["constructors"],"elf":census.sha(exe),"native":native.stdout.decode(),"features":a["features"],"instructions":measured(phase)}
        if load(D/"dispatch.json")["counter"]=="callgrind":assert len(list(phase.glob("callgrind.*")))==1
    actual=sorted((load(p) for p in phase.glob("link-selection.[0-9]*.json")),key=lambda x:x["observed_ns"])
    if len(actual)>1:
        assert mode=="stock" and (label=="cold" or "empty" in label)
        assert len({x["output"] for x in actual})==1 and all(not x["owning_rustc_is_link_only"] for x in actual)
    selected=actual[-1] if actual else None
    if selected is not None:put(phase/"link-selection.json",selected)
    ev=(phase/"events").read_text().splitlines() if (phase/"events").exists() else []
    kinds=CounterEvents(ev)
    if res["exit"]==0:
        native_value(res);assert selected is not None
        exe=Path(selected["output"]);key=census.sha(exe);assert key==res["elf"]
        escrow=R/"native-bodies"/key
        if not escrow.exists():shutil.copyfile(exe,escrow)
        assert census.sha(escrow)==key
    if "-count" in mode:assert selected["owning_rustc_is_link_only"]
    res.update(events=kinds,selection=selected is not None,actual_link_requests=len(actual));put(phase/"verified.json",res);print(label,mode,res["exit"],res.get("instructions"),res.get("elf"),kinds,flush=True)


def CounterEvents(rows):
    values={}
    for l in rows:
        pid,k=l.split();assert pid.isdigit()
        values[k]=values.get(k,0)+1
    return values


def run(src):
    assert census.git(src,"rev-parse","HEAD")==census.RUFF and census.sha(src/"Cargo.lock")==census.LOCK and not census.git(src,"status","--porcelain=v1")
    assert os.geteuid()!=0 and not any(k in os.environ for k in ("GH_TOKEN","GITHUB_TOKEN","RUSTFLAGS","RUSTC_WRAPPER","LD_PRELOAD"))
    assert shutil.disk_usage(W).free>=32*2**30
    kit=load(E/"identity.json")["sdk"];assert census.acquire.verify_sdk(SDK)==kit
    env=load(D/"base-env.json");(W/"home").mkdir(exist_ok=True)
    cp=W/"system-copy";cp.mkdir()
    for d in ("earlier","lower","objects"):(cp/d).mkdir()
    gcc=Path(subprocess.check_output(["gcc","-print-file-name=libgcc.a"],text=True).strip()).resolve(strict=True).parent
    assert str(gcc).startswith("/usr/lib/gcc/x86_64-linux-gnu/") and gcc.name.isdigit()
    system=gcc/"libutil.so";assert not system.exists() and not system.is_symlink()
    system_id=physical(gcc);ns=os.readlink("/proc/self/ns/mnt")
    mount=["sudo","-n","unshare","--mount","--propagation","private","--","/bin/bash",str(H/"private-search.sh")]
    tail=[str(W),str(gcc),ns,str(os.getuid()),str(os.getgid())]
    probe=subprocess.run([*mount,"probe",*tail],text=True,capture_output=True)
    put(D/"route.json",{"gcc":str(gcc),"namespace":ns,"original_gccdir":system_id,"stdout":probe.stdout,"stderr":probe.stderr,"exit":probe.returncode})
    assert probe.returncode==0
    expected={x["name"]+"-"+x["version"]+".crate":x["checksum"] for x in tomllib.loads((src/"Cargo.lock").read_text())["package"] if "source" in x}
    assert len(expected)==498
    sel,valgrind=calibrate()
    witness=D/"witness";witness.mkdir(mode=0o700)
    stock=D/"stock-wild";matched=D/"matched-wild"
    assert census.sha(LINK)==STOCK and census.sha(matched)==load(R/"build.json")["matched_wild"]
    put(D/"dispatch.json",{"counter":sel,"stock":str(stock),"matched":str(matched),"witness":str(witness),"launcher":str(D/"count"),"valgrind":valgrind})
    original_cargo=D/"signed-cargo";os.rename(SDK/"bin/cargo",original_cargo);os.link(W/"cargo-child",SDK/"bin/cargo")
    assert census.sha(SDK/"bin/cargo")==b.SOURCE["child"][1] and b.SOURCE["child"][0] in subprocess.check_output(["cargo","+ohm","-vV"],env=env,text=True)
    with (R/"fetch.log").open("xb") as log:subprocess.run(["cargo","+ohm","fetch","--locked"],cwd=src,env=env,stdout=log,stderr=log,check=True)
    actual={p.name:census.sha(p) for p in (W/"cargo/registry/cache").glob("*/*.crate")};assert actual==expected;put(R/"registry.json",actual)
    os.rename(LINK,stock);shutil.copy2(M/"dispatch.py",LINK);assert census.sha(LINK)==census.sha(M/"dispatch.py")
    (R/"native-bodies").mkdir()
    results={};references={}
    def command(label,mode,barrier=None):
        f=R/label;f.mkdir()
        argv=[*mount,"visit",*tail,sys.executable,str(Path(__file__).resolve()),str(src),str(W),label,mode]
        if barrier is None:subprocess.run(argv,check=True,timeout=1000)
        else:
            d=f/"barrier";d.mkdir();os.mkfifo(d/"continue",0o600)
            p=subprocess.Popen(argv)
            try:
                end=time.monotonic()+120
                while not (d/"entered").is_file() and p.poll() is None and time.monotonic()<end:time.sleep(.005)
                assert p.poll() is not None or (d/"entered").is_file(),(label,"timeout before check")
                if (d/"entered").is_file():
                    s=(d/"entered").read_text().split();assert len(s)==2 and s[0].isdigit()
                    barrier(s[1],f)
                    with (d/"continue").open("wb",buffering=0) as fifo:fifo.write(bytes([1]))
                assert p.wait(timeout=180)==0
            finally:
                if p.poll() is None:p.kill();p.wait()
        assert physical(gcc)==system_id and not system.exists() and not system.is_symlink()
        record=load(f/"verified.json");results[label]=record
        return record
    def save(label,back=False):
        for n in ("target","build"):
            warm=W/n;park=D/(label+"-"+n)
            a,d=(park,warm) if back else (warm,park)
            if a.exists():assert not d.exists();os.rename(a,d)
    def empty(label,val):
        save("warm-"+label)
        x=command(label,"stock")
        assert native_value(x)==val and x["exit"]==(101 if val is None else 0)
        save("empty-"+label);save("warm-"+label,True)
        if val is not None:
            refs=references.setdefault(str(val),x["elf"]);assert x["elf"]==refs
        return x
    def check(label,mode,val):
        x=command(label,mode)
        assert native_value(x)==val and x["exit"]==(101 if val is None else 0)
        if val is not None:assert x["elf"]==references[str(val)],(label,x["elf"],references[str(val)])
        return x
    try:
        initial=command("cold","stock");assert native_value(initial)==0
        references["0"]=initial["elf"]
        check("stock-ordinary","stock",0);check("matched-ordinary","off",0)
        for i in range(3):check("native-train-"+str(i),"active",0)
        for i in range(2):check("meter-train-"+str(i),"active-count",0)
        for i,order in enumerate(SCHEDULE,1):
            for role in order:check(f"cost-{i:02d}-{role}",role+"-count",0)
        observed=Path(load(R/"stock-ordinary/link-selection.json")["output"])
        assert observed.resolve().is_relative_to(W/"target") and observed.stat().st_nlink==1 and observed.is_file()
        for role in ("stock","active"):
            original=observed.read_bytes();assert census.sha(observed)==references["0"]
            at=paired.elf(original)["sections"][".comment"][3]+3
            stat=observed.stat();before=physical(observed)
            with observed.open("r+b") as f:f.seek(at);f.write(bytes([original[at]^1]))
            os.utime(observed,ns=(stat.st_atime_ns,stat.st_mtime_ns));changed=physical(observed)
            assert before[:8]==changed[:8] and census.sha(observed)!=references["0"]
            put(R/(role+"-corruption.json"),{"offset":at,"byte_original":original[at],"byte_corrupt":original[at]^1,"digest_corrupt":census.sha(observed),"before":before,"changed":changed})
            x=check(role+"-corrupt-output",role,0);assert "hit" not in x["events"]
            for form in ("hardlink","symlink"):
                alias=D/(role+"-"+form+"-alias")
                if form=="hardlink":os.link(observed,alias)
                else:os.rename(observed,alias);observed.symlink_to(alias)
                a=(observed.lstat(),alias.stat())
                x=check(role+"-"+form+"-output",role,0)
                at_wild=load(R/(role+"-"+form+"-output")/"link-selection.json")["output_before"]
                # A verified actual original alias must conservatively pass through the stock full path.
                if at_wild and (at_wild[2]&0o170000==0o120000 or at_wild[4]!=1):assert "hit" not in x["events"]
                bstats=(observed.lstat(),alias.stat())
                def attrs(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
                put(R/(role+"-"+form+".json"),{"before":[attrs(s) for s in a],"after":[attrs(s) for s in bstats],"alias_final":census.sha(alias),"output_final":census.sha(observed)})
                if form=="symlink" and observed.is_symlink():observed.unlink();os.rename(alias,observed)
                else:alias.unlink()
            check(role+"-after-aliases",role,0)
        src_c=cp/"objects/hook.c";shutil.copy2(M/"hook.c",src_c)
        for val in (29,41):subprocess.run(["/usr/bin/cc","-c","-fPIC","-O2",f"-DVALUE={val}",src_c,"-o",cp/f"objects/hook{val}.o"],check=True)
        shutil.copytree(cp/"objects",R/"real-hook-source")
        inp=cp/"objects/active.o";script=("INPUT ( "+str(inp)+" )\n").encode();provider=cp/"earlier/libutil.so"
        shutil.copyfile(cp/"objects/hook29.o",inp);provider.write_bytes(script)
        empty("empty-29",29);check("shadow-29","active",29);check("shadow-29-train","active",29);check("shadow-29-hit","active",29)
        for name in ("malformed","missing"):
            if name=="malformed":
                st=provider.stat();before=physical(provider);provider.write_bytes(b"!"*len(script));os.utime(provider,ns=(st.st_atime_ns,st.st_mtime_ns));assert before[:8]==physical(provider)[:8]
            else:provider.write_bytes(script);inp.unlink()
            check(name,"active",None);empty(name+"-empty",None)
        shutil.copyfile(cp/"objects/hook41.o",inp);empty("empty-41",41);check("repair-41","active",41)
        f29=(cp/"objects/hook29.o").read_bytes();f41=(cp/"objects/hook41.o").read_bytes()
        diff=[i for i,(l,r) in enumerate(zip(f29,f41,strict=True)) if l!=r];assert 0<len(diff)<=4,(len(diff),len(f29))
        for role in ("off","active"):
            inp.write_bytes(f29)
            with inp.open("r+b") as file:view=mmap.mmap(file.fileno(),0,access=mmap.ACCESS_WRITE)
            with view:
                # Touch the same mapped writable page before training, with unchanged bytes, then close its original FD.
                for idx in diff:view[idx]=f29[idx]
                check(role+"-race-train0","active",29);check(role+"-race-train1","active",29);check(role+"-race-train2","active",29)
                def change(cut,f):
                    before=physical(inp);h=census.sha(inp)
                    for idx in diff:view[idx]=f41[idx]
                    after=physical(inp);hh=census.sha(inp);assert h==hashlib.sha256(f29).hexdigest() and hh==hashlib.sha256(f41).hexdigest()
                    put(f/"mutation.json",{"cut":cut,"before":before,"after":after,"all_stat_fields_equal":before==after,"old":h,"new":hh,"offsets":diff})
                rr=command(role+"-race",role+"-race",change)
                if view[:]==f41:
                    assert rr["exit"]==0 and native_value(rr) in (29,41)
                    check(role+"-race-current-stock","stock",41)
                else:
                    assert view[:]==f29 and "hit" not in rr["events"]
        provider.unlink();check("system-restored","active",0);empty("restored-fully-empty",0)
        proof={"source":census.RUFF,"lock":census.LOCK,"sdk_rust":kit["bin/rustc"][0],"cargo":b.SOURCE["child"],"counter":sel,"stock":STOCK,"matched":census.sha(matched),"witness_files":[[p.name,p.stat().st_size,census.sha(p)] for p in sorted(witness.iterdir())],"references":references,"rows":results,"schedule":SCHEDULE}
        assert all(row[1]==32 for row in proof["witness_files"])
        put(R/"study.json",proof)
    finally:
        if LINK.exists() and census.sha(LINK)==census.sha(M/"dispatch.py"):LINK.unlink();os.rename(stock,LINK)
        if SDK.joinpath("bin/cargo").samefile(W/"cargo-child"):(SDK/"bin/cargo").unlink();os.rename(original_cargo,SDK/"bin/cargo")
        assert physical(gcc)==system_id and not system.exists() and not system.is_symlink()
        again=census.acquire.verify_sdk(SDK);assert all(again[k][:6]==kit[k][:6] for k in kit)
        put(R/"final-binding.json",{"before":kit,"after":again,"original_source_status":census.git(src,"status","--porcelain=v1"),"restored_gcc":physical(gcc)})


if __name__=="__main__":
    if sys.argv[1]=="build":build(Path(sys.argv[2]).resolve(strict=True))
    elif sys.argv[1]=="run":run(Path(sys.argv[2]).resolve(strict=True))
    else:
        assert sys.argv[1]=="visit";worker(Path(sys.argv[2]),Path(sys.argv[3]),*sys.argv[4:])
