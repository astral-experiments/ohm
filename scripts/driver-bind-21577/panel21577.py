"""Capture every opened Cargo history, including its independent cold control, before calculating prices."""
from common21577 import *
from source_intake import ROLES,check as check_sdk,prepare as prepare_sdk
import source_surface
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
def select(role,pool,proof,source=None):
    if SDK.exists():
        prev,=[n for n in ROLES if not (pool/n).exists()]
        SDK.rename(pool/prev)
    (pool/role).rename(SDK)
    expected=read(proof.parent.parent/"intake"/("effective-"+role+".json"))
    actual=check_sdk(role,expected,source)
    if proof.exists():assert actual==read(proof)
    else:save(proof,actual)
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
def run(out,donor,pool,label,local=False,sources=None):
    sources=sources or {}
    assert not (ROOT/"bank").exists() and not (out/"panel").exists()
    ROOT.mkdir(exist_ok=True);(ROOT/"bank").mkdir();(ROOT/"home").mkdir();(ROOT/"cargo").mkdir(exist_ok=local)
    source(SRC,"A",donor);panel=out/"panel";panel.mkdir();store=out/"blobs";store.mkdir()
    select("S",pool,panel/"selected-S.json",sources.get("S"))
    if not local:h.invoke([h.CARGO,"fetch","--locked"],SRC,dict(ENV,CARGO_NET_OFFLINE="false"))
    save(out/"registry.json",registry())
    openings={};linked={}
    for role in ROLES:
        select(role,pool,panel/("selected-"+role+".json"),sources.get(role))
        d=panel/("opening-"+role);openings[role]=visit(d,role,store,None,dry=local)
        linked[role]=behavior(role,d/"behavior",donor)
        source_surface.observe(read(panel/("selected-"+role+".json")),openings[role],store,d/"native-reader")
    selected={role:read(panel/("selected-"+role+".json"))for role in ROLES}
    witness=source_surface.joint(openings,selected,lambda n:(store/n).read_bytes(),
        lambda role,digest:(panel/("opening-"+role)/"native-reader"/(digest+".gz")).read_bytes())
    save(panel/"cross-role-metadata.json",witness)
    source_surface.require_equal(witness)
    msgs={role:{k:v["output"]for k,v in checks.items()}for role,checks in linked.items()}
    assert msgs["S"]==msgs["R"]==msgs["T"]
    save(panel/"joint.json",{"roles":list(ROLES),"all_39_native_item_inventories":True,
         "all_30_sidecars_bound_to_native_root":True,"same_kernel_argv_and_direct_extern_interfaces":True,
         "positive_A_B_outputs":msgs["S"],"native_digest":sha(panel/"cross-role-metadata.json"),
         "openings":{role:sha(panel/("opening-"+role)/"native.json") for role in ROLES}})
    if local:return
    tools=read(out/"boot-attestation.json")["tools"]
    for i,order in enumerate(PLAN["orders"][label],1):
        for role in order.split("/"):
            select(role,pool,panel/("selected-"+role+".json"),sources.get(role));visit(panel/(str(i)+"-"+role),role,store,openings[role],tools=tools)
    save(panel/"complete.json",{"label":label,"order":PLAN["orders"][label],"protocol":sha(HERE/"protocol.json"),"opening":sha(panel/"joint.json")})
