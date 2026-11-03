"""Apply a finalized numeric-header overlay to the actual reconstructed four-source r2 distribution."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile

H=Path(__file__).resolve().parent
sys.path.insert(0,str(H))
import gate as s
P=s.POLICY
layers=s.read(H/"layers.json")


def apply_sources(repo, view, name, selected, directory=None):
    """Check both immutable templates and the exact post-selection delta using a one-commit base view."""
    base=layers["base"];template=layers["role_templates"][name]
    assert view.is_dir() and not tuple(view.iterdir())
    subprocess.run(["git","init","--bare","--template=","--quiet",view],check=True)
    assert s.text(view,"rev-parse","--path-format=absolute","--git-common-dir")==str(view.resolve())
    obj=s.text(repo,"rev-parse","--path-format=absolute","--git-path","objects")
    ordered=[];seen=set()
    def visit(path):
        path=path.resolve()
        if path in seen:return
        seen.add(path);ordered.append(str(path))
        alternate=path/"info/alternates"
        if alternate.is_file():
            for value in alternate.read_text().splitlines():visit(path/value)
    visit(Path(obj));(view/"objects/info/alternates").write_text("\n".join(ordered)+"\n")
    (view/"shallow").write_text(base+"\n")
    s.g(view,"update-ref","refs/heads/base",base)
    orig=runpy.run_path(str(H/"accept_packet.py"))
    signed=orig["open_packet"](view,name,layers,(H/"templates"/template["packet"]["path"]).read_bytes())
    r=selected["roles"][name];raw=((H/"enrollment" if directory is None else directory)/r["packet"]["path"]).read_bytes()
    s.need(s.text(repo,"rev-parse","HEAD","HEAD^{tree}").splitlines()==[base,layers["base_tree"]],"wrong reconstructed Rust checkout")
    p=r["packet"]
    s.need(0<len(raw)==p["bytes"]<=1<<20 and p["sha256"]==hashlib.sha256(raw).hexdigest()
           and raw[:4]==b"PACK" and raw[-20:]==hashlib.sha1(raw[:-20]).digest(),"final pack bytes")
    output=subprocess.check_output(["git","-C",view,"index-pack","--strict","--stdin"],input=raw).decode().split()
    s.need(output==["pack",raw[-20:].hex()],"native final pack index")
    index=view/"objects/pack"/("pack-"+output[1]+".idx")
    rows=[k.split() for k in s.text(view,"verify-pack","-v",str(index)).splitlines()]
    objects={k[0]:k[1]for k in rows if len(k)>=5 and len(k[0])==40}
    s.need(sorted(objects)==p["objects"] and len(objects)==int.from_bytes(raw[8:12],"big") and sum(v=="commit" for v in objects.values())==1
           and objects.get(r["commit"])=="commit", "final positive packet membership")
    s.need(s.text(view,"rev-parse",r["commit"]+"^",r["commit"]+"^{tree}").splitlines()==[base,r["tree"]],"final parent and tree")
    base_set=set(s.text(view,"rev-list","--objects","--no-object-names","--missing=error",base).splitlines())
    final_set=set(s.text(view,"rev-list","--objects","--no-object-names","--missing=error",r["commit"]).splitlines())
    s.need(final_set-base_set==set(objects) and len(base_set)==layers["complete_release_object_count"] and hashlib.sha256(("\n".join(sorted(base_set))+"\n").encode()).hexdigest()==layers["complete_release_objects_sha256"],"root plus exact final pack closure")
    changed=s.text(view,"diff-tree","--no-renames","--no-commit-id","-r","--name-only",r["template_commit"],r["commit"]).splitlines()
    formats=[s.INC]if name=="ctfe_control"else [s.INC,s.META]
    s.need(changed==sorted(formats),"only allocated format files may differ from reviewed template")
    for f in formats:
        a=s.text(view,"ls-tree",r["template_commit"],"--",f).split()
        b=s.text(view,"ls-tree",r["commit"],"--",f).split()
        s.need(a[0]==b[0]=="100644" and a[1]==b[1]=="blob" and a[3]==b[3]==f,"changed format file mode")
        old=s.g(view,"show",r["template_commit"]+":"+f)
        use=r["epoch"]if f==s.INC else r["metadata_epoch"]
        s.need(s.version(old,f,template["template_formats"][s.FORMAT[f]],use)==s.g(view,"show",r["commit"]+":"+f),"non-format source delta "+f)
    s.need(s.text(view,"diff-tree","--no-renames","--no-commit-id","-r","--name-only",base,r["commit"]).splitlines()==template["changed_files"],"full source roster")
    for f,v in template["file_oids"].items():
        if f not in formats:
            s.need(s.text(view,"rev-parse",r["commit"]+":"+f)==v,"template file "+f)
    return raw,{"source":r,"template":signed,"native_index_pack":output[1],"format_files":changed,"complete_objects":len(final_set)}


def assert_sources(official, manifest, rust):
    tools=[rust/"src/tools"/n for n in ("cargo","clippy","rustfmt")]
    subprocess.run([official/"scripts/verify-release-sources.sh",manifest,rust,*tools],check=True)
    for path,key in zip(tools,("cargo","clippy","rustfmt")):
        v=P["sources"][key]
        s.need(s.text(path,"rev-parse","HEAD","HEAD^{tree}").splitlines()==[v["revision"],v["tree"]],"component "+key)


def main():
    import candidate
    w=s.checkout("build");request=s.selected()
    assert os.environ["BENCH_ARM"] == "G"
    selected=s.baseline_selected();name="full_with_ctfe"
    assert name in selected["role_order"]
    src=w/"source/rust";official=w/"official-release";qa=w/"trait-evidence"
    for path,expected in P["release_files"].items():
        raw=(official/path).read_bytes()
        s.need(s.oid(raw)==expected["oid"] and s.h(official/path)==expected["sha256"] and
               s.text(official,"rev-parse","HEAD:"+path)==expected["oid"],"official source byte identity "+path)
    original=s.read(w/"cross-evidence/source.json");r=selected["roles"][name]
    s.need(original["source_trees"]==P["sources"] and original["manifest_sha256"]==P["release_files"]["toolchains/1.99.0/23.json"]["sha256"]
           and original["workflow"]==os.environ["GITHUB_SHA"] and original["coordinator"]==P["source_checkouts"]["release-candidate"],"qualified four-source materializer")
    fn=official/"toolchains/1.99.0/23.json";assert_sources(official,fn,src)
    with tempfile.TemporaryDirectory(dir=w) as scratch:
        tmp=Path(scratch);view=tmp/"proof.git";view.mkdir()
        raw,proof=apply_sources(src,view,name,selected)
        subprocess.run(["git","-C",src,"index-pack","--strict","--stdin"],input=raw,check=True)
        s.g(src,"checkout","--quiet","--detach","--no-recurse-submodules",r["commit"])
        s.need(s.text(src,"rev-parse","HEAD","HEAD^{tree}").splitlines()==[r["commit"],r["tree"]],"final native checkout")
        for f in layers["role_templates"][name]["changed_files"]:
            mode,kind,blob,leaf=s.text(src,"ls-tree","HEAD","--",f).split()
            s.need(leaf==f and kind=="blob" and mode==("100755"if (src/f).stat().st_mode&0o111 else "100644")
                   and s.oid((src/f).read_bytes())==blob and not (src/f).is_symlink(),"installed working source "+f)
        proposed=s.read(fn);proposed["sources"]["rust"]["revision"]=r["commit"]
        target=tmp/"1.99.0/23.json";target.parent.mkdir()
        shutil.copyfile(official/"toolchains/manifest.schema.json",tmp/"manifest.schema.json")
        s.write(target,proposed);assert_sources(official,target,src)
        parent_proof=proof
        selected=request;name="G";r=request["roles"][name]
        proof={"F":parent_proof,"G":candidate.install(src,r)}
        proposed["sources"]["rust"]["revision"]=r["commit"]
        candidate_root=tmp/"G";candidate_manifest=candidate_root/"1.99.0/23.json"
        candidate_manifest.parent.mkdir(parents=True)
        shutil.copyfile(official/"toolchains/manifest.schema.json",candidate_root/"manifest.schema.json")
        s.write(candidate_manifest,proposed);assert_sources(official,candidate_manifest,src)
    track=("src/tools/rustc-perf","src/tools/opt-dist","src/tools/opt-dist/component-pgo-v1","src/bootstrap","src/llvm-project","library")
    training={}
    for f in track:
        a=s.text(src,"rev-parse",layers["base"]+":"+f)
        s.need(s.text(src,"rev-parse",r["commit"]+":"+f)==a,"same production training "+f)
        training[f]=a
    s.write(qa/"source.json",{"role":name,"source":r,"classification":"private unsigned production-recipe qualification",
           "reviewed_head":os.environ["GITHUB_SHA"],"qualified_parent":P["coordinator_parent"],"original_release":P["official_release"],
           "release_files":P["release_files"],"training_objects":training,"original_four_sources":original,
           "strict_source":proof,"signed_cargo_sha256":selected["signed_cargo_sha256"],
           "baseline_eligibility_sha256":s.h(H/"enrollment/enrollment.json"),"eligibility_sha256":candidate.AUTHORIZATION_SHA256,"literal_build_command":P["gnulinux_build_command"]})

if __name__=="__main__":main()
