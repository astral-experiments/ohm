"""Reopen both uploaded capsules by immutable job outputs and report actual providers."""
from pathlib import Path,PurePosixPath
import os,re,stat,sys,tempfile,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import stage as s
g=s.g;probe=s.probe
def extract(packet,dest,inner):
    assert packet.is_file() and not packet.is_symlink() and packet.stat().st_size<96<<20 and g.file_hash(packet)==inner
    with zipfile.ZipFile(packet) as z:
        rows=z.infolist();assert rows and len(rows)<4096 and sum(x.file_size for x in rows)<160<<20 and len(rows)==len({v.filename for v in rows})
        for x in rows:
            p=PurePosixPath(x.filename);assert p.parts and not p.is_absolute() and p.as_posix()==x.filename and ".." not in p.parts and "\\" not in x.filename
            assert not x.is_dir() and stat.S_IFMT(x.external_attr>>16) in (0,stat.S_IFREG) and x.file_size<32<<20
            target=dest/p;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("xb") as f:f.write(z.read(x))
    v=g.load(dest/"role.json");assert v["files"]=={p.relative_to(dest).as_posix():g.file_hash(p) for p in dest.rglob("*") if p.is_file() and p!=dest/"role.json"}
    return v
def check_role(dest,rec,role,ctx):
    assert rec["schema"]==1 and rec["role"]==role and rec["context"]==ctx and rec["files_manifest"]==s.file_map() and rec["role_source"]==s.S["arms"][role]
    src=g.load(dest/"source.json");s.match_source(src,role,ctx);ident=g.load(dest/"identity.json")
    assert ident["source_label"]==src["source"]["commit"]
    assert (dest/"rustc-vV.txt").read_bytes()==ident["rustc_vV"].encode()
    s.verified_version(ident["rustc_vV"],src["source"]["commit"])
    assert (dest/"bootstrap.toml").read_text()==s.config(Path(ident["path"]).parents[1])
    root=dest/"observed";obs=g.load(root/"probe.json")
    assert ident["path"]==obs["sdk"] and "rustc "+obs["version"]==ident["rustc_vV"].splitlines()[0]
    sdk=Path(obs["sdk"]);build=sdk.parents[1];assert (dest/"bootstrap.toml").read_text()==s.config(build)
    cmds=g.load(dest/"commands.json");assert set(cmds)=={"build","unit","run-make"}
    opts=cmds["build"][:-2];assert opts[-8:]==["build","--stage","1","-j8","--host",s.HOST,"--target",s.HOST] and cmds["build"][-2:]==["compiler/rustc","library"]
    for key,extras in (("unit",["compiler/rustc_middle","--test-args",s.UNIT]),("run-make",s.suites(role))):
        assert cmds[key]==opts[:-8]+["test",*opts[-7:],*extras];s.passed((dest/(key+".log")).read_bytes(),key,role)
    methods=g.load(dest/"methods.json");expect=g.load(s.H/"methods.json")["states"];assert len(methods)==len(expect)==7
    for i,(row,exp) in enumerate(zip(methods,expect,strict=True)):
        assert {k:row[k] for k in exp}==exp and set(row["binaries"])=={"history","cold-"+str(i)} and len(set(row["binaries"].values()))==1
    counts=probe.verify(root);assert counts==rec["observed"];return counts,obs,src,ident
def evidence():
    ctx=s.context();w=Path(os.environ["GITHUB_WORKSPACE"]);out=w/"paired-proof";out.mkdir();data={};inputs={};ids=set()
    with tempfile.TemporaryDirectory() as tmp:
        for name,role in (("BASE",s.BASE),("CHILD",s.CAND)):
            ident,outer,inner=[os.environ[name+"_"+v].removeprefix("sha256:") for v in ("ID","SHA","INNER")]
            assert re.fullmatch("[1-9][0-9]*",ident) and ident not in ids and all(re.fullmatch("[0-9a-f]{64}",v) for v in (outer,inner));ids.add(ident)
            packet=w/"intake"/name/"qualified-role.zip";dest=Path(tmp)/name;rec=extract(packet,dest,inner)
            data[name]=check_role(dest,rec,role,ctx);inputs[role]={"actions_id":int(ident),"actions_zip_sha256":outer,"verified_inner_zip_sha256":inner,"role_manifest_sha256":g.file_hash(dest/"role.json")}
        (left,lobs,lsrc,lid),(right,robs,rsrc,rid)=(data[n] for n in ("BASE","CHILD"))
        assert left.keys()==right.keys() and lid["driver_sha256"]!=rid["driver_sha256"] and lsrc["source"]["commit"]==rsrc["source"]["parent"] and lsrc["source"]["tree"]==rsrc["source"]["parent_tree"]
        assert all(lid[k]==rid[k] for k in ("stage0","bootstrap_objects","resolved_llvm"))
        assert all(lsrc[k]==rsrc[k] for k in ("training_objects","recipe","component_git","signed_manifest_sha256","source_pack_sha256"))
        changes=[]
        for seed in ("01","02"):
            for case in probe.CASES:
                for crate in probe.CRATES:
                    a,b=[rec["seeds"][seed]["cases"][case]["ordinary"]["rows"][crate] for rec in (lobs,robs)]
                    assert all(a[k]==b[k] for k in ("exit","codes","external","stderr")),(seed,case,crate,"cross-role diagnostics")
                    dif=[k for k in ("metadata","root") if a[k]!=b[k]]
                    if dif:changes.append([seed,case,crate,dif])
        rows=[{"case":k.split("/")[0],"crate":k.split("/")[1],"provider":q,"before":vs[q],"after":right[k][q]} for k,vs in left.items() for q in sorted(vs)]
        factorial=[r for r in rows if r["case"] in ("offset","trait","both") and r["provider"]=="typeck_root"]
        g.put(out/"result.json",{"scope":"synthetic stage1 provider execution diagnostics on exact private compiler source; no timing or instruction measurements","context":ctx,"enrollment":s.file_map(),"artifacts":inputs,"providers":rows,"factorial_cases_reproducing_parent_provider":sum(x["before"] for x in factorial),"factorial_suppressed":sum(x["before"]==1 and x["after"]==0 for x in factorial),"cross_role_metadata_differences":changes,"normalization":"none within a compiler; exact raw diagnostics across compilers; per-role rmeta and metadata roots preserved","semantic_edit_requires_provider":True})
if __name__=="__main__":assert __debug__;evidence()
