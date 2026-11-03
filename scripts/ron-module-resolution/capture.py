from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path(os.environ["RON_CONTROL_WORK"])
KIT=Path(os.environ["RON_CONTROL_KIT"])
sys.path.insert(0,str(KIT))
import replay
def read(p):return json.loads(p.read_bytes())
def put(p,r):p.write_text(json.dumps(r,sort_keys=True,indent=2)+"\n")
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def history():
    inv=read(KIT/"inputs/invocation.json")
    sdk=Path(os.environ["RON_CONTROL_SDK"])
    replay.physical_sdk(sdk)
    out=ROOT/"history";out.mkdir();(out/"events").mkdir();(out/"tmp").mkdir();target=out/"output";target.mkdir()
    inputs=out/"input";replay.materialize(inv,inputs)
    v=lambda s:s.replace("$ROLE",str(inputs))
    argv=list(map(v,inv["argv"]));argv[argv.index("--out-dir")+1]=str(target)
    env={k:os.environ[k]for k in ("HOME","PATH","USER","LANG")if k in os.environ}
    env.update({k:v(a)for k,a in inv["compiler_env"].items()})
    env.update(CARGO_MAKEFLAGS=inv["raw_jobserver"]["flags"],RUSTUP_HOME=str(ROOT/"rustup"),TMPDIR=str(out/"tmp"))
    r,w=os.pipe()
    assert (r,w)==(3,4)
    os.dup2(r,5,inheritable=True);os.dup2(w,7,inheritable=True);os.close(r);os.close(w);os.write(7,b"+++")
    cwd=Path(v(inv["cwd"]));baseline={n.relative_to(inputs).as_posix():sha(n)for n in sorted(inputs.rglob("*"))if n.is_file()}
    assert len(baseline)==555
    def affirm():
        for n,h in baseline.items():assert sha(inputs/n)==h,n
    dirs=[Path(a.split("=",1)[1])for i,a in enumerate(argv)if i and argv[i-1]=="-L"]
    selected,=dirs[2].glob("libserde_core-*.rmeta"); earlier=dirs[0]/selected.name; assert not earlier.exists()
    owner=cwd/"src/util.rs"; assert not owner.exists() and (cwd/"src/util/mod.rs").is_file()
    gn=out/"gdb-qualification.json";put(gn,{"argv":argv,"cwd":str(cwd),"env":env,"sdk":str(sdk),"output":str(target),"shadow":str(owner),"input":str(inputs)})
    result={}
    def run(name):
        affirm()
        root=out/"events"/name;root.mkdir()
        with(root/"stdout").open("xb")as so,(root/"stderr").open("xb")as se:
            v=subprocess.run(argv,cwd=cwd,env=env,pass_fds=(5,7),stdout=so,stderr=se,timeout=180)
        diag=[]
        for ln in (root/"stderr").read_bytes().splitlines():
            if ln.startswith(b"{"):
                o=json.loads(ln)
                if o.get("$message_type")=="diagnostic":
                    diag.append({"code":(o.get("code")or{}).get("code"),"message":o.get("message"),"level":o.get("level"),"spans":[[sp["file_name"],sp["line_start"],sp["column_start"]]for sp in o.get("spans",[])if sp["is_primary"]]})
        files={}
        for f in sorted(target.iterdir()):files[f.suffix]=sha(f);f.rename(root/f.name)
        row={"rc":v.returncode,"diag":diag,"outputs":files,"previous_file_count":len(baseline)};put(root/"result.json",row);result[name]=row
        print(name,v.returncode,[(e["code"],e["message"][:75])for e in diag if e["code"]][:3],flush=True)
    run("regular")
    earlier.write_bytes(selected.read_bytes());run("earlier-byte-equal-serde_core")
    with earlier.open("r+b",buffering=0)as f: f.write(b"R")
    run("earlier-bad-magic-serde_core");earlier.unlink();run("repair-earlier")
    owner.touch(exist_ok=False);run("new-zero-length-src-util-rs");owner.unlink();run("repair-util")
    inputs.rename(out/"closed-first-input");replay.materialize(inv,inputs);owner.touch(exist_ok=False);run("independent-empty-util");owner.unlink();run("independent-empty-valid")
    valid={k:v for k,v in result.items()if v["rc"]==0}
    for n in ("regular","repair-earlier","repair-util","independent-empty-valid"):assert n in valid
    ref=valid["regular"]["outputs"]
    assert all(r["outputs"][".rlib"]==ref[".rlib"]and r["outputs"][".d"]==ref[".d"]for r in valid.values())
    for n in ("new-zero-length-src-util-rs","independent-empty-util"):
        assert result[n]["rc"]!=0 and "E0761"in[e["code"]for e in result[n]["diag"]]and ".rlib" not in result[n]["outputs"]
    assert result["new-zero-length-src-util-rs"]["diag"]==result["independent-empty-util"]["diag"]
    consumers=replay.consumer.run(out/"consumer",env,[j for i,a in enumerate(argv)if a=="-L"for j in ("-L",argv[i+1])],{k:out/"events"/k for k in valid})
    assert len({v["ELF"]for v in consumers["physical_artifacts"].values()})==1
    affirm()
    put(out/"ordinary.json",{"arms":result,"consumer":consumers,"previous_input_sha256":baseline,"plan":sha(ROOT/"registration.json")})
if __name__=="__main__":history()
