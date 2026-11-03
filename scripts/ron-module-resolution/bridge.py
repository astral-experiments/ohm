"""Reuse the preregistered signed bridge observer with an explicit nonzero exit arm."""
from pathlib import Path
import hashlib,json,os,shutil,signal,subprocess,zipfile
HERE=Path(__file__).resolve().parent
ROOT=Path(os.environ["RON_CONTROL_WORK"])
QA=HERE/"debugger"
REF="ff195d83bf4875d8a9df6b5098839e9597007769"
H=ROOT/"history"
J=lambda p:json.loads(p.read_bytes())
def put(p,v):p.write_text(json.dumps(v,sort_keys=True,indent=2)+"\n")
def run():
    board=ROOT/"debugger-01";board.mkdir()
    prior=J(H/"gdb-qualification.json")
    old=J(HERE/"bridge-registers.json")
    folder=board/"source";folder.mkdir()
    for rel in ("ruff-foreign-span-observer/observe.py","ruff-foreign-span-observer/unwind.c","ruff-original-ty-instructions/ron_jobserver.py"):
        shutil.copyfile(QA/Path(rel).name,folder/Path(rel).name)
    original=(folder/"observe.py").read_bytes();assert hashlib.sha256(original).hexdigest()==old["observer_sha256"]
    needle=b"assert exit_codes==[0],exit_codes"
    assert original.count(needle)==1
    observer=folder/"exit-qualified.py"
    observer.write_bytes(original.replace(needle,b'assert exit_codes==[int(os.environ["OHM_EXPECTED_CODE"])],exit_codes'))
    wrapper=folder/"ron_jobserver.py";wrapper.chmod(0o700)
    lib=folder/"unwind.so";subprocess.run(["cc","-Wall","-Werror","-shared","-fPIC","-O2",str(folder/"unwind.c"),"-o",str(lib),"-lunwind-ptrace","-lunwind-x86_64","-lunwind","-llzma"],check=True)
    argv=prior["argv"];sdk=Path(prior["sdk"]);driver,=(sdk/"lib").glob("librustc_driver*.so")
    argv=[str(sdk/"bin/rustc"),*argv[2:]]
    assert hashlib.sha256(driver.read_bytes()).hexdigest()==old["driver"]
    out=Path(prior["output"]);shadow=Path(prior["shadow"]);inp=Path(prior["input"])
    core,=inp.rglob("libserde_core-*.rmeta");macro,=inp.rglob("libserde_derive-*.so")
    results={}
    for name,expected in (("ordinary",0),("zero-byte-module",1)):
        arm=board/name;arm.mkdir();deep=arm/"deep-joins";deep.mkdir();logs=arm/"observations";logs.mkdir()
        if expected:shadow.touch(exist_ok=False)
        assert not list(out.iterdir())
        put(arm/"plan.json",{"argv":argv,"driver":{"path":str(driver),"sha":old["driver"]}})
        put(deep/"fn-offsets.json",old["bridge_offsets"]);shutil.copyfile(lib,deep/"unwind.so")
        env=dict(prior["env"],OHM_LICENSED_RUSTC=argv[0],OHM_F_SPAN_PY=str(observer),OHM_F_SPAN_LOG=str(logs/"hits.json"),
                 OHM_F_JOBSERVER_PROOF=str(arm/"jobserver.json"),OHM_EXPECTED_CODE=str(expected),OHM_SELECTED_CORE=str(core),OHM_SELECTED_MACRO=str(macro))
        script=arm/"control.gdb"
        script.write_text('''set confirm off
set pagination off
set python print-stack full
set disable-randomization off
set startup-with-shell on
set exec-wrapper '''+str(wrapper)+'''
set debuginfod enabled off
set auto-load off
set auto-solib-add off
set print thread-events off
handle SIGUSR1 nostop noprint pass
start
python
import os,gdb
exec(compile(open(os.environ["OHM_F_SPAN_PY"]).read(),os.environ["OHM_F_SPAN_PY"],"exec"))
maybe_macros=lambda:None
ordinary_scope_join=scope_join
extra=[]
def scope_join(req):
    ordinary_scope_join(req)
    row={}
    for var in ("OHM_SELECTED_CORE","OHM_SELECTED_MACRO"):
        path=Path(os.environ[var]); st=path.stat(); actual=[]
        for line in maps.read_text().splitlines():
            fields=line.split(maxsplit=5)
            if len(fields)==6 and fields[5]==str(path) and fields[2]=="00000000":
                major,minor=map(lambda s:int(s,16),fields[3].split(":"))
                assert (os.makedev(major,minor),int(fields[4]))==(st.st_dev,st.st_ino)
                addr=int(fields[0].split("-")[0],16); actual.append({"flags":fields[1],"inode":st.st_ino,"dev":st.st_dev,"memory_prefix":buf(addr,16).hex()})
        row[var]={"maps":actual,"path_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    extra.append(row)
end
continue
python
finish()
Path(os.environ["OHM_F_SPAN_LOG"]).with_name("selected-at-joins.json").write_text(json.dumps(extra))
end
''')
        try:
            with(arm/"stdout").open("xb")as so,(arm/"stderr").open("xb")as se:
                proc=subprocess.Popen(["gdb","-q","-nx","-nh","-batch","-x",str(script),"--args",*argv],env=env,cwd=prior["cwd"],stdout=so,stderr=se,start_new_session=True)
                try:rc=proc.wait(timeout=125)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGTERM);proc.wait();raise
            assert rc==0 and (logs/"hits.json").is_file(),(arm/"stderr").read_text()[-1200:]
            v=J(logs/"hits.json");assert v["exit_codes"]==[expected]
            outputs={}
            for f in out.iterdir():outputs[f.suffix]=hashlib.sha256(f.read_bytes()).hexdigest();f.rename(arm/f.name)
            if expected:assert b'E0761' in (arm/"stderr").read_bytes() and ".rlib"not in outputs
            else:assert outputs[".rlib"]==J(H/"ordinary.json")["arms"]["regular"]["outputs"][".rlib"]
            results[name]={"rc":expected,"events":v["events"],"returns":v["actual_returns"],"join_sources":v["join_sources"],"entry_counts":v["entry_counts"],"selected_at_joins":J(logs/"selected-at-joins.json"),"products":outputs,"hits_sha":hashlib.sha256((logs/"hits.json").read_bytes()).hexdigest()}
            print(name,results[name]["events"],len(v["actual_returns"]),v["entry_counts"],flush=True)
        finally:
            if expected:shadow.unlink(missing_ok=True)
    put(board/"readback.json",results)
if __name__=="__main__":run()
