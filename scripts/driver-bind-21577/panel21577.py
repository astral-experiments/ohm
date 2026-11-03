"""Capture every opened Cargo history, including its independent cold control, before calculating prices."""
from common21577 import *
from elf import produce
import time

def invoke_visit(dst,command,env=ENV):
    dst.mkdir(parents=True)
    cold=dst.name in ("cold-A","cold-B")
    if cold:assert not TARGET.exists()
    with (dst/"stdout").open("xb")as o,(dst/"stderr").open("xb")as e:
        start=time.monotonic_ns()
        proc=subprocess.Popen(command,cwd=SRC,env=env,stdout=o,stderr=e)
        pid,code=os.waitpid(proc.pid,0)
        stop=time.monotonic_ns();proc.returncode=os.waitstatus_to_exitcode(code)
    assert pid==proc.pid and proc.returncode==0 and stop>start and b"Finished" in (dst/"stderr").read_bytes()
    if cold:
        log=(dst/"stderr").read_text()
        checked=re.findall(r"^\s+(?:Checking|Compiling) (\S+) v",log,re.M)
        assert sorted(checked)==read(HERE/"cold-roster.json")
        save(dst/"clean-process.json",{"pid":pid,"started_ns":start,"finished_ns":stop,"exit":proc.returncode,"cwd":str(SRC),"command":command,"env":env,"checked_or_compiled":checked,"target_initially_absent":True,"separate_preparation":True})
def no_change(dst):
    assert h.kernel(dst,False)=={} and read(dst/"observed.json")["rows"]==[]
def commands(dst):
    forms=h.kernel(dst,True)
    assert set(forms)==NAMES and len(read(dst/"observed.json")["rows"])==2
    return forms
def externs(forms):
    result={}
    for name,argv in forms.items():
        assert str(h.RUSTC)==argv[0] and argv[argv.index("--crate-name")+1]==name
        result[name]={}
        for i,a in enumerate(argv):
            if a=="--extern":
                ident, path = argv[i+1].split("=",1)
                assert ident not in result[name] and Path(path).is_file()
                result[name][ident]={"path":path,"blob":blob(Path(path))}
        assert result[name]
    return result
def clean_target():
    assert TARGET==ROOT/"target" and not TARGET.is_symlink()
    if TARGET.exists():shutil.rmtree(TARGET)
def check_sdk(role):
    orig=read(HERE/"signed-sdk.json");rel=read(HERE/"layout.json")["driver"]
    expected={k:[v["bytes"],PLAN["prototype"] if k==rel and role=="P" else v["sha256"],v["mode"]] for k,v in orig.items()}
    assert len(expected)==142 and not any(f.is_symlink()for f in SDK.rglob("*"))
    assert {str(f.relative_to(SDK)):[*blob(f),f.stat().st_mode&0o777] for f in SDK.rglob("*")if f.is_file()}==expected
    banners=read(HERE/"signed-native.json")["banners"]
    for binary in ("cargo","rustc"):
        assert subprocess.check_output([SDK/"bin"/binary,"-vV"],env=ENV,text=True).strip()==banners[binary].strip()
    assert subprocess.check_output([h.RUSTC,"--print","sysroot"],env=ENV,text=True).strip()==str(SDK)
    libs=subprocess.check_output(["ldd",h.RUSTC],env=ENV,text=True);assert "not found" not in libs
    entry,=[s for s in libs.splitlines()if "librustc_driver-" in s];loaded=Path(entry.split("=>")[1].split()[0]).resolve()
    assert loaded==SDK/rel and blob(loaded)[1]==expected[rel][1]
    return {"role":role,"driver":expected[rel][1],"cargo":expected["bin/cargo"][1],"count":len(expected),"full_members":expected,"native_banners":banners,"loaded_driver":str(loaded)}
def select(role,pool,proof):
    if SDK.exists():
        prev,=[n for n in ("S","P") if not (pool/n).exists()]
        SDK.rename(pool/prev)
    (pool/role).rename(SDK)
    actual=check_sdk(role)
    if proof.exists():assert actual==read(proof)
    else:save(proof,actual)
def prepare_sdk(out,tmp):
    from media import Transport
    sys.path.insert(0,str(HERE.parent/"uv-client-22958"))
    os.environ.setdefault("UV_22958_CONTRAST","signed")
    import release23_package,release_intake
    proof=out/"intake";proof.mkdir();transfer=tmp/"driver-binding-transfer";transfer.mkdir()
    pool=tmp/"driver-binding-sdks";pool.mkdir()
    original=release23_package.official(Transport,proof,transfer)
    release_intake.install_archive(original,pool/"S","R")
    signed=release_intake.role_sdk("R",pool/"S",proof/"signed")
    assert signed["runtime"]==read(HERE/"signed-native.json")["runtime"] and signed["source"]==read(HERE/"signed-native.json")["source"]
    shutil.copytree(pool/"S",pool/"P",copy_function=os.link)
    rel=read(HERE/"layout.json")["driver"];dst=pool/"P"/rel;dst.unlink()
    record=produce(pool/"S"/rel,dst);save(proof/"transformation.json",record)
    assert blob(pool/"S"/rel)[1]==PLAN["signed"] and blob(dst)[1]==PLAN["prototype"]
def named_meter(d,forms,tools):
    path=d/"per-rustc";path.mkdir()
    req={"command":CHECK,"environment":ENV,"cwd":str(SRC),"compiler_path":str(h.RUSTC),"selectors":forms};save(d/"request.json",req)
    h.invoke([sys.executable,"-ISB",h.METER/"per_rustc.py","capture",d/"request.json",path,tools["library"]],SRC,{"PATH":"/usr/bin:/bin","LC_ALL":"C"})
    counted=read(path/"per-rustc.json");id=h.EV["file_id"](h.RUSTC);tree=h.EV["decode"](read(path/"kernel-events.json"))
    got,rows=h.forms_from_tree(tree,id);assert got==forms and len(rows)==2 and set(counted["targets"])==NAMES
    save(path/"observed.json",{"rustc_id":id,"cargo_id":h.EV["file_id"](h.CARGO),"forms":got,"all_actual_images":rows})
def visit(d,role,store,opening,tools=None,dry=False):
    d.mkdir();assert not d.is_symlink()
    a=source(SRC,"A");clean_target();invoke_visit(d/"cold-A",CHECK);cold_a=surface(d/"cold-A",store);no_change(d/"unchanged-A")
    seed=ROOT/"bank/current.tar.zst";stamp=h.fixed_seed(seed);save(d/"seed.json",{"bytes_sha256":stamp,"source":a,"products":sha(d/"cold-A/products.json"),"workspace_role":role})
    b=source(SRC,"B");k=d/"first-B"
    forms=commands(k);warm=surface(k,store);params=externs(forms);save(k/"externs.json",params)
    if opening:assert forms==opening["forms"] and warm==opening["B"] and cold_a==opening["A"] and params==opening["externs"]
    def restore():h.fixed_seed(seed,stamp)
    restore()
    if tools is None:invoke_visit(d/"bare",CHECK)
    else:h.ordinary(d/"bare")
    assert surface(d/"bare",store)==warm
    if tools:
        restore();whole=d/"whole";whole.mkdir()
        with (whole/"stdout").open("xb")as o,(whole/"stderr").open("xb")as e:h.invoke([tools["plain"],whole/"raw.json",*CHECK],SRC,ENV,stdout=o,stderr=e)
        assert b"Finished" in (whole/"stderr").read_bytes() and surface(whole,store)==warm
        restore();named_meter(d,forms,tools);assert surface(d/"per-rustc",store)==warm
    elif dry:
        restore();forms2=commands(d/"kernel-replay");assert forms2==forms and surface(d/"kernel-replay",store)==warm
    no_change(d/"unchanged-B")
    clean_target();invoke_visit(d/"cold-B",CHECK);cold=surface(d/"cold-B",store);seed.unlink()
    assert cold==warm and all(len(z)==k for z,k in ((warm["rmeta"],39),(warm["sidecars"],30),(warm["workspace"],4)))
    save(d/"native.json",{"source_A":a,"source_B":b,"A":sha(d/"cold-A/products.json"),"B":sha(k/"products.json"),"cold_B":sha(d/"cold-B/products.json"),"same_native_B":True,"same_held_bare":True,"role":role,"two_forms":sorted(forms),"externs_sha256":sha(k/"externs.json"),"matched_previous_opening":bool(opening),"captured_counters":tools is not None,"cold_A_seed":stamp})
    return {"forms":forms,"A":cold_a,"B":warm,"externs":params}
def run(out,donor,pool,label,local=False):
    assert not (ROOT/"bank").exists() and not (out/"panel").exists()
    ROOT.mkdir(exist_ok=True);(ROOT/"bank").mkdir();(ROOT/"home").mkdir();(ROOT/"cargo").mkdir(exist_ok=local)
    source(SRC,"A",donor);panel=out/"panel";panel.mkdir();store=out/"blobs";store.mkdir()
    select("S",pool,panel/"selected-S.json")
    if not local:h.invoke([h.CARGO,"fetch","--locked"],SRC,dict(ENV,CARGO_NET_OFFLINE="false"))
    save(out/"registry.json",registry())
    openings={};linked={}
    for role in "SP":
        select(role,pool,panel/("selected-"+role+".json"))
        d=panel/("opening-"+role);openings[role]=visit(d,role,store,None,dry=local)
        linked[role]=behavior(role,d/"behavior",donor)
    assert openings["S"]==openings["P"]
    assert {k:v["output"]for k,v in linked["S"].items()}=={k:v["output"]for k,v in linked["P"].items()}
    save(panel/"joint.json",{"both_full_native_cohorts_identical":True,"all_39_raw_rmeta_and_30_public":True,"both_two_argv_and_extern_material_agree":True,"positive_A_B_outputs":{k:v["output"]for k,v in linked["P"].items()},"opening_S":sha(panel/"opening-S/native.json"),"opening_P":sha(panel/"opening-P/native.json")})
    if local:return
    tools=read(out/"boot-attestation.json")["tools"]
    for i,order in enumerate(PLAN["orders"][label],1):
        for role in order.split("/"):
            select(role,pool,panel/("selected-"+role+".json"));visit(panel/(str(i)+"-"+role),role,store,openings[role],tools=tools)
    save(panel/"complete.json",{"label":label,"order":PLAN["orders"][label],"protocol":sha(HERE/"protocol.json"),"opening":sha(panel/"joint.json")})
