"""Run the correct producer's original distribution reader in a clean interpreter for this role."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from production_service import PRODUCERS, ROLES, REPO, need

def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()

def read(p):
    return json.loads(p.read_bytes())

def save(p,v):
    p.write_text(json.dumps(v,sort_keys=True,indent=2)+"\n")

def main(role, builder, image, qa, scratch, fixed, dest, pool):
    p=PRODUCERS[role]
    arm=read(HERE/"pair.json")["arms"][role]
    service=arm["service"]
    need(__debug__ and not sys.flags.optimize,"producer assertions disabled")
    need(subprocess.check_output(["git","-C",builder,"rev-parse","HEAD"],text=True).strip()==p["head"]
         and subprocess.check_output(["git","-C",builder,"rev-parse","HEAD:scripts/ctfe22-gnu"],text=True).strip()==arm["builder_tree"]
         and not subprocess.check_output(["git","-C",builder,"status","--porcelain","--untracked-files=no"]), "wrong producer checkout or source")
    compiler=builder/"scripts/ctfe22-gnu"
    sys.path.insert(0,str(compiler))
    import pair
    for module in (pair,pair.native,pair.s,pair.transition):
        need(Path(module.__file__).resolve().parent==compiler,"mixed producer modules")
    expected=arm["source"]
    source=read(qa/"source.json")
    rv=read(qa/"role.json")
    need(all(rv[k]==expected[v] for k,v in (("source_commit","commit"),("source_tree","tree"),("epoch","epoch")))
         and {k:source["source"][k] for k in expected}==expected and rv["epoch"]==(43317 if role==ROLES[0] else 43319)
         and rv["driver"]["sha256"]==arm["driver"] and sha(qa/"role.json")==arm["role_sha256"]
         and sha(qa/"source.json")==arm["source_sha256"], "source, driver, or QA record does not match independent enrollment")
    ctx=dict(evidence_repository=REPO,reviewed_head=p["head"],workflow_ref=REPO+"/.github/workflows/ci.yml@refs/heads/"+p["branch"],
             run_id=p["run"],run_attempt=1)
    shared=("recipe","released_coordinator","training_objects","component_git","signed_manifest_sha256")
    original=read(qa/"previous-production-source.json")
    need({k:original[k]for k in ctx}==ctx and original["source"]==pair.native.S["arms"]["fa7a_stack_ctfe318"] and original["source_pack_sha256"]=="d2b0cf8e4623519d3870a4fc97d028c25f164bc0f52364a3be6945e682ea488f","wrong older compiler reconstruction")
    old_config=read(compiler/"callable-source.json");spec=read(HERE/"production-source.json")
    old=read(qa/"previous-callable-source.json")
    need(old["source"]==old_config["source"] and old["source"]["commit"]=="f53496e2dd363b1455fc7e0a9d2dedea1bf7650e" and old["role"]=="callables_ctfe318" and old["source"]["parent"]==original["source"]["commit"],"different base compiler")
    need(old_config["source_role_sha256"]==sha(HERE/"production-source.json")and old_config["files"]==spec["files"]and old_config["pack_sha256"]==sha(compiler/"callable-production.pack")==spec["sha256"][spec["pack_file"]]==old["source_pack_sha256"]and old["overlay_description_sha256"]==sha(compiler/"callable-source.json")and old["previous_qualified_source_sha256"]==sha(qa/"previous-production-source.json")and old_config["pack_objects"]==spec["pack_objects"]==38,"different official original compiler overlay")
    need(all(old[k]==original[k]==source[k]for k in shared)and {k:old[k]for k in ctx}==ctx,"unmatched release material")
    domain=source if role==ROLES[0] else read(qa/"previous-domain-source.json")
    config=read(compiler/"domain-source.json");spec=read(HERE/"domain/source-role.json");previous_f534_record="e63c4063f2c855674444e11d9fc1018e032540e936a4b43c77c497c50c44540e"
    need(config["source"]==domain["source"] and config["source_role_sha256"]==sha(HERE/"domain/source-role.json") and config["files"]==spec["delta"] and config["pack_objects"]==spec["pack_objects"]==35 and config["pack_sha256"]==sha(compiler/"domain-production.pack")==spec["pack_sha256"]==domain["source_pack_sha256"]and domain["source"]["parent"]==old["source"]["commit"] and domain["source"]["parent_tree"]==old["source"]["tree"],"different fourteen-file production treatment")
    need(domain["previous_callable_source_sha256"]==sha(qa/"previous-callable-source.json")and domain["overlay_description_sha256"]==sha(compiler/"domain-source.json")and config["published_parent_source_sha256"]==previous_f534_record and config["stage1_qualification_sha256"]==sha(HERE/"stage1-qualified.json")==sha(compiler/"stage1-qualified.json"),"different admitted parent, source or independent evidence")
    ancestry=("role","source","component_git","recipe","training_objects","signed_manifest_sha256","released_coordinator","source_pack_sha256","overlay_description_sha256")
    rebased=hashlib.sha256(json.dumps({k:old[k]for k in ancestry},sort_keys=True,separators=(",",":")).encode()).hexdigest()
    need(rebased==domain["published_parent_projection_sha256"]==config["published_parent_projection_sha256"],"actual parent source projection")
    d=rv["installed_crate_domain_test"]
    fixture={p:v for p,v in config["files"].items()if p.startswith("tests/run-make/crate-incoherent-impl-domain/")}
    need(len(fixture)==5 and d["fixture_blobs"]==fixture and d["exit"]==0 and d["driver_sha256"]==rv["driver"]["sha256"]and d["log_sha256"]==sha(qa/"optimized-crate-incoherent-impl-domain.log")and d["final_outputs"]=={"reader":"11 0 0","local":"0"}and d["both_solvers"]is True and d["diagnostic"]=="E0061"and [d[k]for k in ("foreign_states","foreign_transitions","local_states","local_transitions")]==[10,9,3,2],"installed production regression incomplete")
    need(domain["source"]["commit"]=="77ce0545653df71f43e601c28dde01a5e4f02b09" and domain["role"]==ROLES[0] and all(domain[k]==original[k]==source[k] for k in shared) and all(domain[k]==v for k,v in ctx.items()),"wrong crate-domain compiler or worker ancestry")
    if role==ROLES[1]:
        config=read(compiler/"derive-source.json")
        spec=read(HERE/"derive/source-role.json")
        expected_parent=read(HERE/"pair.json")["arms"][ROLES[0]]
        need(source["role"]==role and source["source"]==config["source"] and all(source["source"][k]==v for k,v in expected.items()) and config["parent"]==domain["source"] and all(domain["source"][k]==v for k,v in expected_parent["source"].items()),"generated compiler parent or role differs")
        need(spec["commit"]==expected["commit"]=="ac67101cb973e35ce8ff044cc8014c2c76bab69e" and spec["tree"]==expected["tree"] and spec["parent"]==domain["source"]["commit"] and source["source"]["parent_tree"]==domain["source"]["tree"] and expected["epoch"]==source["source"]["metadata_epoch"]==43319,"wrong native source or epoch")
        need(config["production_source_role"]==sha(HERE/"derive/source-role.json") and config["files"]==spec["files"] and len(spec["files"])==15 and sum(n.startswith("compiler/") for n in spec["files"])==9 and config["format_versions"]=={"incremental":[43317,43319],"metadata":[3,43319]},"wrong source delta, metadata or incremental format")
        need(config["pack_objects"]==spec["pack_objects"]==36 and config["pack_sha256"]==sha(compiler/"derive-production.pack")==source["source_pack_sha256"] and config["stage1_protocol"]==sha(HERE/"derive/stage1-protocol.json"),"source pack, stage1 protocol or object list")
        need(source["previous_domain_source_sha256"]==sha(qa/"previous-domain-source.json") and source["overlay_description_sha256"]==sha(compiler/"derive-source.json") and source["published_parent_source_sha256"]==config["published_parent_source_sha256"]==expected_parent["source_sha256"],"wrong re-enrolled prior SDK")
        anchor=("role","source","component_git","recipe","training_objects","signed_manifest_sha256","released_coordinator","source_pack_sha256","overlay_description_sha256")
        need(hashlib.sha256(json.dumps({k:domain[k]for k in anchor},sort_keys=True,separators=(",",":")).encode()).hexdigest()==source["published_parent_projection_sha256"]==config["published_parent_projection_sha256"],"different actual parent role/source recipe")
        generated=rv["installed_generated_impl_test"]
        fixture={k:v["after"]["oid"]for k,v in config["files"].items() if k.startswith("tests/run-make/proc-derive-impl-identity/")}
        need(len(fixture)==6 and generated["fixture_blobs"]==fixture and generated["exit"]==0 and generated["driver_sha256"]==rv["driver"]["sha256"] and generated["log_sha256"]==sha(qa/"optimized-proc-derive-impl-identity.log") and generated["final_linked_output"]=="(5, 11, 7)","missing native generated-derive linked and fixture checks")
        prerequisite=runpy.run_path(str(compiler/"derive-prerequisite.py"))["verified"]
        prerequisite(read(compiler/"derive-qualified.json"),config)
        need(sha(compiler/"derive-qualified.json")==arm["generated_prerequisite_sha256"]==config["derive_screen_sha256"],"different actual generated-derive prerequisite")
    names={"trait-impl-bucket-callables","trait-impl-bucket-coroutine","trait-impl-bucket-sparse-foreign"}
    need(set(rv["installed_callable_tests"])==names and all(row["exit"]==0 and row["driver_sha256"]==rv["driver"]["sha256"]and row["log_sha256"]==sha(qa/("optimized-"+n+".log"))for n,row in rv["installed_callable_tests"].items()),"prior production fixture has not qualified")
    pair.native.S=dict(pair.native.S,pack_sha256=config["pack_sha256"])
    qualified,sources,installed=pair.validate(role,image,qa,scratch,ctx)
    need(rv==qualified and source==sources,"different native QA reader")
    data=runpy.run_path(str(compiler/"capacity-audit.py")); authority="52779265edb1486bceb9f6abf0c7a24dfc0f234caea4a067653b0eceb514772b"
    floor=data["authority"](compiler/"capacity-admission.json",authority,compiler/"capacity-selector.py")
    limits=data["role"](qa,role,floor,authority,{"GITHUB_SHA":p["head"],"GITHUB_RUN_ID":str(p["run"]),"GITHUB_RUN_ATTEMPT":"1"},source["source"])
    need(floor==250<<30 and limits["runner"]==service["runner_name"],"capacity on a different producer")
    # Load the unchanged original archive reader only after the two unrelated producers have been process-isolated.
    from production_archive import runtime_files
    import core as c
    c.m.P["roles"]={role:expected}
    runtime=runtime_files(role,installed,scratch/"sdk-inventory.json",rv)
    dest.mkdir()
    for name in ("SHA256SUMS","role.json","source.json","sdk-inventory.json","component-inventory.json"):
        shutil.copyfile(image/name,dest/name)
    shutil.copyfile(qa/"previous-production-source.json",dest/"previous-production-source.json")
    shutil.copyfile(qa/"previous-callable-source.json",dest/"previous-callable-source.json")
    if role==ROLES[1]:shutil.copyfile(qa/"previous-domain-source.json",dest/"previous-domain-source.json")
    save(dest/"resource-replay.json",limits)
    (installed/"bin/cargo").unlink()
    shutil.copy2(fixed,installed/"bin/cargo")
    runtime["bin/cargo"]=sha(installed/"bin/cargo")
    need(runtime["bin/cargo"]==rv["effective_benchmark_cargo_sha256"]==c.m.P["signed_cargo_sha256"],"unsigned benchmark Cargo")
    for name in ("rustc","rustdoc","cargo"):
        need((installed/"bin"/name).is_file(),"incomplete installed SDK")
    rustc=installed/"bin/rustc"
    banner=subprocess.check_output([rustc,"-vV"],env={"PATH":"/usr/bin:/bin"},text=True)
    (dest/"rustc-vV.txt").write_text(banner)
    need("commit-hash: "+expected["commit"] in banner.splitlines(),"different physical compiler")
    loader=subprocess.check_output(["/usr/bin/ldd",rustc],env={"PATH":"/usr/bin:/bin"},text=True)
    (dest/"ldd.txt").write_text(loader)
    need(all(str((installed/rv[k]["path"]).resolve()) in [str(Path(x.split(" => ")[1].split()[0]).resolve()) for x in loader.splitlines() if " => /" in x]
             for k in ("driver","llvm")),"unrelated native driver or LLVM")
    installed.rename(pool/role)
    save(dest/"registered.json",dict(runtime=runtime,server=arm["artifact"],source=expected,
        production_archive=rv["archive_sha256"],original_bundled_cargo=rv["bundled_cargo"]["sha256"],
        unmodified_component_inventory=sha(scratch/"sdk-inventory.json"),producer_job_id=service["job"]))

if __name__=="__main__":
    main(sys.argv[1],*(Path(p).resolve()for p in sys.argv[2:]))
