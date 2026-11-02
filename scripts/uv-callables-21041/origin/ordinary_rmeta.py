"""Exact standalone ordinary reader from the original production QA. No modified metadata."""
from pathlib import Path
import hashlib, json, subprocess
from derive.metadata_epoch import banner_and_epoch as banner
def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()
def save(p,data):
    with p.open("x") as f:
        json.dump(data,f,sort_keys=True,indent=2);f.write("\n")

def metadata(roles, out):
    out.mkdir()
    (out/"dep.rs").write_text("pub struct Width(pub usize);\npub const VALUE: Width = Width(43);\n")
    (out/"reader.rs").write_text("extern crate directory_origin_dep as dep;\npub const N: usize = dep::VALUE.0;\n")
    (out/"bad.rs").write_text("extern crate directory_origin_dep as dep;\npub const N: bool = dep::VALUE.0;\n")
    env={"LC_ALL":"C","PATH":"/usr/bin:/bin"}
    headers={};traces={}
    def invoke(label, compiler, args, ok):
        cmd=[compiler,"--edition=2024","--error-format=json",*args]
        cp=subprocess.run(cmd,cwd=out,env=env,capture_output=True)
        assert (cp.returncode==0)==ok and cp.stdout==b"", (label,cp.returncode,cp.stderr[:700])
        (out/(label+".stderr")).write_bytes(cp.stderr)
        rows=[json.loads(t) for t in cp.stderr.splitlines()]
        traces[label]={"args":list(map(str,cmd)),"exit":cp.returncode,"stderr":hashlib.sha256(cp.stderr).hexdigest(),"codes":[r["code"]["code"] for r in rows if r.get("code")]}
        return rows
    for name,d in roles.items():
        root=Path(d["physical_sdk"]);rc=root/"bin/rustc"
        true=subprocess.check_output([rc,"--version"],text=True,env=env).strip()
        assert d["source"]["commit"][:9] in true and d["source"]["commit"] in subprocess.check_output([rc,"-vV"],text=True,env=env)
        sub=out/name;sub.mkdir();p=sub/"libdirectory_origin_dep.rmeta"
        invoke("write-"+name,rc,["--sysroot",root,"--crate-type=lib","--crate-name","directory_origin_dep","--emit=metadata","-Cmetadata=origin-wire","-o",p,"dep.rs"],True)
        v=banner(p);assert v==true+" (Ohm metadata "+str(d["rmeta_epoch"])+")", v
        headers[name]={"path":str(p),"sha256":sha(p),"bytes":p.stat().st_size,"encoded":v,"native":true,"epoch":d["rmeta_epoch"]}
    for reader,d in roles.items():
        root=Path(d["physical_sdk"]);rc=root/"bin/rustc"
        for writer,h in headers.items():
            label=writer+"-to-"+reader
            path=Path(h["path"]);ok=h["encoded"]==headers[reader]["encoded"]
            result=out/(label+".rmeta")
            base=["--sysroot",root,"--crate-type=lib","--crate-name","origin_reader","--emit=metadata","--extern","directory_origin_dep="+str(path)]
            rows=invoke(label,rc,[*base,"-o",result,"reader.rs"],ok)
            coded=[r for r in rows if r.get("code")]
            if ok:
                assert not rows and result.is_file() and banner(result)==headers[reader]["encoded"]
                bad=invoke(label+"-semantic-type-error",rc,[*base,"-o",out/(label+"-bad.rmeta"),"bad.rs"],False)
                assert [r["code"]["code"] for r in bad if r.get("code")]==["E0308"]
            else:
                assert not result.exists() and [r["code"]["code"] for r in coded]==["E0514"]
                assert h["encoded"] in coded[0]["rendered"] and headers[reader]["encoded"] in coded[0]["rendered"]
            assert sha(path)==h["sha256"]
    result={"ordinary_headers":headers,"real_compilations":traces,"two_immutable_originals":True,
            "file_edits":False,"compiler_version_overrides":False,"actual_compatible_pairs":[k for k,t in traces.items() if "-to-" in k and t["exit"]==0],
            "actual_version_rejections":[k for k,t in traces.items() if t["codes"]==["E0514"]]}
    save(out/"passed.json",result)
    return result
