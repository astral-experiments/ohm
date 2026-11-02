"""Exercise the unchanged incrementals' wire format bidirectionally, including source edits and a cold behavior oracle."""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, tempfile
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
                w=Path(raw)/label;w.mkdir();slot=w/"sdk";vis=[]
                def step(role,stage,state,fresh=False,signature=False):
                    if slot.is_symlink(): slot.unlink()
                    slot.symlink_to(sdks[role],target_is_directory=True)
                    env={"PATH":"/usr/bin:/bin","LC_ALL":"C","RUSTC_BOOTSTRAP":"1","LD_LIBRARY_PATH":str(slot/"lib")}
                    if shared:env["RUSTC_FORCE_RUSTC_VERSION"]="rustc-perf"
                    for n in ("roster","facade"):shutil.copyfile(fx/(n+".rs"),w/(n+".rs"))
                    (w/"reader.rs").write_text(reader.replace("fn only_coroutine()","fn only_coroutine(_: u8)")if signature else reader)
                    if fresh and (w/"cache").exists():(w/"cache").rename(w/("saved-before-"+stage.replace("/","-")))
                    rows={}
                    for n in ("roster","facade","reader"):
                        cmd=[str(slot/"bin/rustc"),"--sysroot",str(slot),"--edition=2024","--crate-name",n,"--crate-type","bin"if n=="reader"else"rlib","--error-format=json","-Zthreads=1"]
                        if n=="roster"and stage!="A"and stage!="A-repeat":cmd+=["--cfg","copy_impl"]
                        if n!="roster":
                            d="roster" if n=="facade"else"facade";cmd+=["--extern",d+"=lib"+d+".rlib","-L","dependency=."]
                        if n=="reader":cmd+=["-Cmetadata=local-coroutine","-Cincremental=cache","-Zincremental-verify-ich=yes","-Zassert-incr-state="+state]
                        cmd+=[n+".rs"];q=subprocess.run(cmd,cwd=w,env=env,capture_output=True,timeout=30)
                        expected=int(signature and n=="reader")
                        assert q.returncode==expected and not q.stdout,(label,role,stage,n,q.stderr.decode()[:2000])
                        ds=[json.loads(v)for v in q.stderr.splitlines()];codes=[j["code"]["code"]for j in ds if j.get("code")]
                        assert codes==(["E0061"] if expected else[]),(n,codes)
                        rows[n]={"argv":cmd,"exit":q.returncode,"codes":codes,"stderr_sha256":hashlib.sha256(q.stderr).hexdigest()}
                    headers={}
                    if not signature:
                        for name in ("dep-graph.bin","query-cache.bin"):
                            p,=(w/"cache").glob("reader-*/s-*/"+name)
                            with p.open("rb")as f:
                                prefix=f.read(7);version=f.read(prefix[6]).decode()
                            assert prefix[:4]==b'RSIC'and int.from_bytes(prefix[4:6],"little")==43311 and version==("rustc-perf"if shared else banners[role])
                            headers[name]=[43311,version,sha(p)]
                        assert subprocess.check_output([str(w/"reader")],cwd=w,env=env)==b"7\n"
                    return {"stage":stage,"role":role,"asserted_incremental_state":state,"headers":headers,"binary":None if signature else sha(w/"reader"),"commands":rows}
                vis.append(step(first,"A","not-loaded"))
                vis.append(step(first,"A-repeat","loaded"))
                vis.append(step(second,"B","loaded"if shared or self_test else"not-loaded"))
                vis.append(step(second,"B-repeat","loaded"))
                vis.append(step(second,"C-signature","loaded",signature=True))
                vis.append(step(second,"B-cold","not-loaded",fresh=True))
                vis.append(step(second,"C-cold","not-loaded",fresh=True,signature=True))
                assert vis[2]["binary"]==vis[3]["binary"]==vis[5]["binary"] and vis[4]["commands"]["reader"]["stderr_sha256"]==vis[6]["commands"]["reader"]["stderr_sha256"]
                result[label]=vis
    (out/"passed.json").write_text(json.dumps({"banners":banners,"fixture_sha256":{n:sha(fx/n)for n in ("roster.rs","facade.rs","reader.rs.in")},"modes":result,"self_check":self_test},sort_keys=True,indent=2)+"\n")
    print("passed",len(result),"cross-routes",sum(len(s)for s in result.values()),"reader processes")
if __name__=="__main__":main(*sys.argv[1:5],self_test=sys.argv[5:]==["--self-check"])
