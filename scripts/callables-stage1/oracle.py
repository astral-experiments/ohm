"""Check actual typeck provider visits for the same unchanged coroutine after adding an unrelated Copy impl."""
from pathlib import Path
import collections, hashlib, json, os, runpy, shutil, struct, subprocess, sys, tempfile

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def main(sdk, fixture, out, role):
    sdk, fixture, out = map(lambda s: Path(s).resolve(), (sdk, fixture, out))
    assert role in ("control", "candidate") and fixture.is_dir()
    out.mkdir()
    compiler = sdk / "bin/rustc"
    env = {"PATH":"/usr/bin:/bin", "LC_ALL":"C","RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(sdk/"lib")}
    common = [str(compiler),"--sysroot",str(sdk),"--edition=2024","-Zthreads=1","-Zincremental-verify-ich=yes","--error-format=json"]
    base = (fixture/"reader.rs.in").read_text()
    label = "typeck_root\x1ereader::only_coroutine"
    profile = runpy.run_path(str(Path(__file__).with_name("profile_v9.py")))["Profile"]
    def analyze(path):
        data, = path.glob("*.mm_profdata")
        p=profile(data.read_bytes()); counters=collections.Counter();activity=0
        for typ,i,tid,lo,hi,flags in struct.iter_unpack("<QQIIII",memoryview(p.entries)[8:]):
            kind=p.label(typ);start=lo|((flags&0xffff0000)<<16);end=hi|((flags&0xffff)<<32)
            if start>=end or end>=0xfffffffffffe:continue
            if kind=="GenericActivity":activity+=1
            if kind=="Query" and p.label(i).startswith("typeck_root\x1e"):counters[p.label(i)]+=1
        assert activity>0
        return {"sha256":sha(data),"counts":dict(counters),"selected":counters[label]}
    def source(w, own_error=False):
        for name in ("roster.rs","facade.rs"):shutil.copyfile(fixture/name,w/name)
        (w/"reader.rs").write_text(base.replace("fn only_coroutine()", "fn only_coroutine(_: u8)") if own_error else base)
    def run(w,name,switched,where=None,expected=0):
        args=common+["--crate-name",name,"--crate-type","bin" if name=="reader"else"rlib","-Cincremental=inc-"+name]
        if name=="roster"and switched:args+=["--cfg","copy_impl"]
        if name in ("reader","facade"):
            dep="roster"if name=="facade"else"facade"
            args+=["--extern",dep+"=lib"+dep+".rlib","-L","dependency=."]
        if where:args+=["-Zself-profile="+str(where),"-Zself-profile-events=default,query-keys"]
        args.append(name+".rs")
        r=subprocess.run(args,cwd=w,env=env,capture_output=True,timeout=35)
        assert not r.stdout and r.returncode==expected,(name,r.returncode,r.stderr.decode()[:1500])
        messages=[json.loads(x) for x in r.stderr.splitlines()];codes=[v["code"]["code"] for v in messages if v.get("code")]
        assert codes==(["E0061"] if expected else []),(name,codes,messages)
        return {"command":args,"returncode":r.returncode,"stderr_sha256":hashlib.sha256(r.stderr).hexdigest(),"codes":codes}
    def check(w,changed,folder,own_error=False,prof=False):
        source(w,own_error)
        if prof:(folder/"profile").mkdir()
        rows={n:run(w,n,changed,folder/"profile" if prof and n=="reader"else None,int(own_error and n=="reader")) for n in ("roster","facade","reader")}
        rows["value"]=None if own_error else subprocess.check_output([str(w/"reader")],cwd=w,timeout=5,env=env).decode().strip()
        assert rows["value"]==(None if own_error else "7")
        rows["binary"]=None if own_error else sha(w/"reader")
        if prof:rows["read"]=analyze(folder/"profile")
        return rows
    result={"role":role,"rustc":sha(compiler),"compiler":subprocess.check_output([str(compiler),"-vV"],env=env,text=True),"files":{n:sha(fixture/n)for n in ("roster.rs","facade.rs","reader.rs.in")},"runs":{}}
    with tempfile.TemporaryDirectory(prefix="compiler-",dir=out)as tmp:
        root=Path(tmp);w=root/"live";seed=root/"seed";w.mkdir()
        initial=out/"a";initial.mkdir();result["runs"]["a"]=check(w,False,initial,prof=True)
        assert result["runs"]["a"]["read"]["selected"]==1
        w.rename(seed)
        for label2,switched,cold,error,prof in [
            ("same",False,False,False,True),("toggle-plain",True,False,False,False),
            ("toggle",True,False,False,True),("cold",True,True,False,True),
            ("signature",True,False,True,False),("signature-cold",True,True,True,False),
        ]:
            folder=out/label2;folder.mkdir()
            if cold:w.mkdir()
            else:shutil.copytree(seed,w)
            row=check(w,switched,folder,own_error=error,prof=prof);result["runs"][label2]=row;shutil.rmtree(w)
        runs=result["runs"]
        assert runs["same"]["read"]["selected"]==0 and runs["cold"]["read"]["selected"]==1
        for n in ("binary","value"):
            assert runs["toggle-plain"][n]==runs["toggle"][n]==runs["cold"][n],n
        assert runs["signature"]["reader"]["stderr_sha256"]==runs["signature-cold"]["reader"]["stderr_sha256"]
    (out/"observed.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    actual=result["runs"]["toggle"]["read"]["selected"]
    assert actual==int(role=="control"),("selected provider in unrelated A->B",role,actual)
    (out/"qualified.json").write_text(json.dumps({"role":role,"unrelated_typeck_provider_count":actual,"receipt_sha256":sha(out/"observed.json"),"genuine_signature_diagnostic":"E0061","warm_cold_binary":result["runs"]["toggle"]["binary"]},sort_keys=True,indent=2)+"\n")
    print("qualified",role,actual)
if __name__=="__main__":main(*sys.argv[1:])
