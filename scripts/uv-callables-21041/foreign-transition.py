"""Exercise the unchanged incrementals' wire format bidirectionally, including source edits and a cold behavior oracle."""
from pathlib import Path
import hashlib, json, os, runpy, shutil, subprocess, sys, tempfile
S=runpy.run_path(str(Path(__file__).with_name("transition_sessions.py")))
assert hashlib.sha256(Path(__file__).with_name("transition_sessions.py").read_bytes()).hexdigest()=="b7ccb7c36b617d5de6b835df4e9e4752dbbf5a79ec939c69bc08d9470b79085a"
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main(control,candidate,fixture,output,self_test=False):
    control,candidate,fx,out=map(lambda s:Path(s).resolve(),(control,candidate,fixture,output));out.mkdir()
    sdks={"control":control,"candidate":candidate};banners={n:subprocess.check_output([str(s/"bin/rustc"),"--version"],text=True).strip().removeprefix("rustc ")for n,s in sdks.items()}
    assert len(set(banners.values()))==(1 if self_test else 2)
    reader=(fx/"reader.rs.in").read_text();result={}
    with tempfile.TemporaryDirectory(prefix="cross-",dir=out)as raw:
        for first,second in [("control","candidate"),("candidate","control")]:
            for shared in [False,True]:
                label=first+"-to-"+second+("-shared"if shared else"-natural")
                w=Path(raw)/label;w.mkdir();script=w/"provenance.ld";shutil.copyfile(Path(__file__).with_name("mixed-qualification.ld"),script);assert sha(script)=="29137d5dd9d562ba6f350596e9b829baf4efd5ccad7098bbd203f27a4c77cdee";slot=w/"sdk";vis=[];log=out/label;log.mkdir();previous=None
                def step(role,stage,state,fresh=False,signature=False):
                    nonlocal previous
                    if slot.is_symlink(): slot.unlink()
                    slot.symlink_to(sdks[role],target_is_directory=True)
                    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(slot/"lib")}
                    if shared:env["RUSTC_FORCE_RUSTC_VERSION"]="rustc-perf"
                    for n in ("roster","facade"):shutil.copyfile(fx/(n+".rs"),w/(n+".rs"))
                    (w/"reader.rs").write_text(reader)
                    if signature:
                        lib=w/"roster.rs";src=lib.read_text();edit=src.replace("fn seed()", "fn seed(_: u8)");assert edit!=src;lib.write_text(edit)
                    if fresh and (w/"cache").exists():(w/"cache").rename(w/("saved-before-"+stage.replace("/","-")))
                    before=S["inventory"](w/"cache"); rows={}
                    (log/(stage+"-before.json")).write_text(json.dumps(before,sort_keys=True))
                    for n in ("roster","facade","reader"):
                        cmd=[str(slot/"bin/rustc"),"--sysroot",str(slot),"--edition=2024","--crate-name",n,"--crate-type","bin"if n=="reader"else"rlib","--error-format=json","-Zthreads=1"]
                        if n=="roster"and stage!="A"and stage!="A-repeat":cmd+=["--cfg","copy_impl"]
                        if n!="roster":
                            d="roster" if n=="facade"else"facade";cmd+=["--extern",d+"=lib"+d+".rlib","-L","dependency=."]
                        if n!="reader":cmd+=["--emit=metadata,link"]
                        if n=="reader":cmd+=["-Clink-arg=-Wl,-T,provenance.ld","-Cmetadata=local-coroutine","-Cincremental=cache","-Zincremental-verify-ich=yes","-Zassert-incr-state="+state]
                        cmd+=[n+".rs"];q=subprocess.run(cmd,cwd=w,env=env,capture_output=True,timeout=30)
                        expected=int(signature and n=="reader")
                        assert q.returncode==expected and not q.stdout,(label,role,stage,n,q.stderr.decode()[:2000])
                        (log/(stage+'-'+n+'.stderr')).write_bytes(q.stderr)
                        ds=[json.loads(v)for v in q.stderr.splitlines()];codes=[j["code"]["code"]for j in ds if j.get("code")]
                        assert codes==(["E0061"] if expected else[]),(n,codes)
                        rows[n]={"rmeta":None if n=="reader"else sha(w/("lib"+n+".rmeta")),"argv":cmd,"exit":q.returncode,"codes":codes,"stderr_sha256":hashlib.sha256(q.stderr).hexdigest()}
                    after=S["inventory"](w/"cache");(log/(stage+"-after.json")).write_text(json.dumps(after,sort_keys=True));active=None;headers={}
                    if not signature:
                        version="rustc-perf"if shared else banners[role]
                        active=S["select"](before,after,version);headers=after["complete"][active]["files"]
                        if stage=="A" or fresh:
                            assert not before["complete"] and state=="not-loaded"
                        else:
                            assert previous
                            expect_same=shared or self_test or stage!="B"
                            S["check_switch"](before,after,previous,active,expect_same)
                            assert state==("loaded"if expect_same else"not-loaded")
                        previous=active
                        assert subprocess.check_output([str(w/"reader")],cwd=w,env=env)==b"7 7 5 6 4\n"
                    if not signature:
                        section_table=subprocess.check_output(["/usr/bin/readelf","-W","-S",str(w/"reader")],text=True)
                        assert ".comment "not in section_table and ".note.gnu.build-id "in section_table
                        shutil.copyfile(w/"reader",log/(stage+".binary"))
                    rec={"stage":stage,"role":role,"asserted_incremental_state":state,"active_session":active,"headers":headers,"binary":None if signature else sha(w/"reader"),"commands":rows}
                    (log/(stage+".actual.json")).write_text(json.dumps(rec,sort_keys=True));return rec
                vis.append(step(first,"A","not-loaded"))
                vis.append(step(first,"A-repeat","loaded"))
                vis.append(step(second,"B","loaded"if shared or self_test else"not-loaded"))
                vis.append(step(second,"B-repeat","loaded"))
                vis.append(step(second,"C-signature","loaded",signature=True))
                vis.append(step(second,"B-cold","not-loaded",fresh=True))
                vis.append(step(second,"C-cold","not-loaded",fresh=True,signature=True))
                assert vis[2]["binary"]==vis[3]["binary"]==vis[5]["binary"] and vis[4]["commands"]["reader"]["stderr_sha256"]==vis[6]["commands"]["reader"]["stderr_sha256"]
                for n in ("roster","facade"):assert len({vis[i]["commands"][n]["rmeta"]for i in (2,3,5)})==1 and vis[4]["commands"][n]["rmeta"]==vis[6]["commands"][n]["rmeta"]
                result[label]=vis
    (out/"passed.json").write_text(json.dumps({"banners":banners,"fixture_sha256":{n:sha(fx/n)for n in ("roster.rs","facade.rs","reader.rs.in")},"modes":result,"self_check":self_test},sort_keys=True,indent=2)+"\n")
    print("passed",len(result),"cross-routes",sum(len(s)for s in result.values()),"reader processes")
if __name__=="__main__":main(*sys.argv[1:5],self_test=sys.argv[5:]==["--self-check"])
