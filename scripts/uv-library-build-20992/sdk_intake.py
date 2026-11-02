"""Use the two enrolled release-producer readers and the signed release's original Cargo verifier."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
def get(p):return json.loads(p.read_bytes())
def put(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def check(b,why):
    if not b:raise ValueError(why)
def git(path,*args):return subprocess.check_output(["git","-C",path,*args],text=True).strip()
def main():
    w=Path(os.environ["GITHUB_WORKSPACE"]);tmp=Path(os.environ["RUNNER_TEMP"])/"ohm-20992-release-custody";tmp.mkdir()
    out=Path(os.environ["OHM20992_RESULT"]);proof=out/"intake";proof.mkdir()
    check(os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF"]=="refs/heads/charlie/codex-20992-trait-origin-production-build-guard","wrong study")
    p=get(HERE/"protocol.json");lock=get(HERE/"physical-roles.json");metadata=w/"sdk-readers/scripts/uv-callables-21041"
    check(sha(metadata/"pair.json")==lock["pair_sha256"] and sha(metadata/"origin/services.json")==lock["services_sha256"],"SDK role inputs changed")
    for f,h in lock["reader_trees"].items():check(git(w/("sdk-readers" if f=="scripts/uv-callables-21041" else "measure"),"rev-parse","HEAD:"+f)==h,"release reader tree differs")
    sys.path.insert(0,str(metadata));import production_archive as archive
    from production_service import service,PRODUCERS,ROLES
    assert ROLES==[lock["roles"][x]["role"]for x in ("parent","candidate")]
    f=w/"measure/scripts/uv-resolver-whole-pmu/intake.py"
    spec=importlib.util.spec_from_file_location("signed_intake",f);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    repo="astral-experiments/ohm";latest=old.gh_json("api","repos/"+repo+"/releases/latest")
    check(latest["tag_name"]=="ohm-1.99.0-22" and not latest["draft"] and not latest["prerelease"],"latest qualified release changed")
    put(proof/"latest-release.json",{k:latest[k]for k in ("id","tag_name","published_at","prerelease","draft")})
    old.released(tmp,proof);signed,=(tmp/"signed").glob("*.tar.gz");fixed=archive.official_cargo(signed,tmp);check(sha(fixed)==p["signed_cargo_sha256"],"unexpected signed Cargo")
    pool=tmp/"pool";pool.mkdir();identities={};locations={}
    for name,bench_builder in (("parent","control-builder"),("candidate","treatment-builder")):
        check(shutil.disk_usage(tmp).free>64<<30,"insufficient space for the enrolled SDKs, scratch allowance and independent physical floor")
        admitted=lock["roles"][name];role=admitted["role"];arm=get(metadata/"pair.json")["arms"][role];pr=PRODUCERS[role]
        check(role in ROLES and arm==admitted["pair_arm"],"different verified two-role package")
        d=proof/name;d.mkdir();docs=[]
        for key,tail in (("run",""),("jobs","/attempts/1/jobs?per_page=100"),("artifacts","/artifacts?per_page=100")):
            doc=old.gh_json("api",f"repos/{repo}/actions/runs/{pr['run']}"+tail);put(d/(key+".json"),doc);docs.append(doc)
        authentic=service(role,*docs);check(authentic==arm["service"] and authentic["members"][pr["sdk"]]==arm["artifact"],"service identity changed")
        acquire=tmp/role;acquire.mkdir()
        for kind in ("sdk","qa"):
            mat=authentic["members"][pr[kind]];zipfile=acquire/(kind+".zip")
            old.gh_bytes(f"repos/{repo}/actions/artifacts/{mat['id']}/zip",zipfile,mat["bytes"],mat["sha256"])
            archive.unpack(zipfile,acquire/kind,kind)
        restored=acquire/"restored";restored.mkdir()
        subprocess.run([sys.executable,"-ISBu",metadata/"verify_role.py",role,w/bench_builder,acquire/"sdk",acquire/"qa",restored,fixed,d/"verified",pool],check=True)
        seal=get(d/"verified/registered.json");check(seal["server"]==arm["artifact"] and seal["source"]==arm["source"] and seal["producer_job_id"]==authentic["job"],"reader bound different physical source")
        check(sha(d/"verified/role.json")==admitted["role_sha256"],"captured release QA changed")
        raw=get(d/"verified/role.json");driver=pool/role/raw["driver"]["path"]
        check(sha(driver)==admitted["driver"]==raw["driver"]["sha256"] and sha(pool/role/"bin/cargo")==p["signed_cargo_sha256"],"wrong installed executables")
        identities[name]=dict(driver=admitted["driver"],source=arm["source"]["commit"],cargo=p["signed_cargo_sha256"],service=authentic["job"],original=arm["artifact"])
        locations[name]=str((pool/role).resolve())
    check(identities["parent"]["source"]==p["fixed_parent"]["source"]["commit"] and identities["candidate"]["source"]==p["candidate_source"],"different release graph")
    put(out/"sdk-identities.json",identities);put(out/"sdk-locations.json",locations)
if __name__=="__main__":main()

