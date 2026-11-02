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
         and {k:source["source"][k] for k in expected}==expected and rv["epoch"]==43309
         and rv["driver"]["sha256"]==arm["driver"] and sha(qa/"role.json")==arm["role_sha256"]
         and sha(qa/"source.json")==arm["source_sha256"], "source, driver, or QA record does not match independent enrollment")
    ctx=dict(evidence_repository=REPO,reviewed_head=p["head"],workflow_ref=REPO+"/.github/workflows/ci.yml@refs/heads/"+p["branch"],
             run_id=p["run"],run_attempt=1)
    if role==ROLES[1]:
        spec=read(HERE/"production-source.json")
        cfg=read(compiler/"callable-source.json")
        prior=read(qa/"previous-production-source.json")
        need(cfg["source_role_sha256"]==sha(HERE/"production-source.json") and cfg["source"]==source["source"]
             and cfg["files"]==spec["files"] and cfg["pack_sha256"]==sha(compiler/"callable-production.pack")
             ==spec["sha256"][spec["pack_file"]]==source["source_pack_sha256"]
             and cfg["pack_objects"]==spec["pack_objects"]==38 and cfg["source"]["parent"]==spec["parent"]==read(HERE/"pair.json")["arms"][ROLES[0]]["source"]["commit"]
             and cfg["source"]["parent_tree"]==spec["parent_tree"]==read(HERE/"pair.json")["arms"][ROLES[0]]["source"]["tree"]
             and source["overlay_description_sha256"]==sha(compiler/"callable-source.json")
             and prior["source"]==pair.native.S["arms"][ROLES[0]] and prior["source_pack_sha256"]==pair.native.S["pack_sha256"]
             =="d2b0cf8e4623519d3870a4fc97d028c25f164bc0f52364a3be6945e682ea488f"
             and source["previous_qualified_source_sha256"]==sha(qa/"previous-production-source.json"),"unqualified overlaid production source")
        need({k:prior[k]for k in ctx}==ctx and all(prior[k]==source[k] for k in ("released_coordinator","training_objects","component_git","recipe","signed_manifest_sha256")),
             "overlay changed previously qualified components")
        # The two-role reader predates this single-role pack. Bind its source check to this producer's exact independently verified relative pack.
        pair.native.S = dict(pair.native.S,pack_sha256=cfg["pack_sha256"])
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
    if role==ROLES[1]:
        shutil.copyfile(qa/"previous-production-source.json",dest/"previous-production-source.json")
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
