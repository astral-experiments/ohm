"""Admit just this reviewed private build and its two recorded native sources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
PREVIOUS=HERE.parent/"rc23-22958-production"
ROOT=HERE.parents[1]
BASE="d57fd1515986dccecdcece8da85e651bfb4b81f9"
TREE="f5bf03d73f71243fb88e34ecb0b155ef11e99a47"
PATHS=("compiler/rustc_codegen_ssa/src/back/linker.rs","src/bootstrap/src/core/build_steps/compile.rs")
PGO="verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt"
def read(p): return json.loads(Path(p).read_bytes())
def save(p,x):
    with Path(p).open("x") as f: json.dump(x,f,indent=2,sort_keys=True);f.write("\n")
def sha(p):
    with Path(p).open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()
def git(repo,*cmd,input=None):
    return subprocess.check_output(["git","--no-lazy-fetch","-C",repo,*cmd], input=input)
def text(repo,*cmd): return git(repo,*cmd).decode().strip()
POLICY=read(PREVIOUS/"policy.json")
SIGNED=read(HERE/"signed.json")
def selected():
    reg=read(HERE/"registration.json")
    assert reg["baseline"]==BASE and reg["baseline_tree"]==TREE
    assert reg["recipe"]==POLICY["official_release"] and reg["cargo"]==SIGNED["cargo"]["sha256"]
    for path,digest in reg["files"].items():
        item=ROOT/path
        assert item.is_file() and not item.is_symlink() and sha(item)==digest,path
    inside={str(x.relative_to(ROOT)) for x in HERE.rglob("*") if x.is_file()}
    assert inside=={p for p in reg["files"] if p.startswith("scripts/rc23-driver-link/")}|{"scripts/rc23-driver-link/registration.json"}
    role=read(HERE/"source.json")
    assert (role["parent"],role["parent_tree"])==(BASE,TREE)
    assert list(sorted(role["files"]))==list(PATHS) and role["commit"]!=BASE and role["tree"]!=TREE
    assert sha(HERE/"source.pack")==role["packet"]["sha256"]
    assert role["changed_formats"]==[] and sha(HERE/"source.json")=="803287036690ab55e430be8c5710b5c11d61a73e2e67398ca2dd682248ffa423"
    assert sha(HERE/"source-qualified.json")=="53477907aedd7d2f4a4e9e44b1404cac920c3d7576e4a3dd7d6072b90d8c173f"
    q=PREVIOUS/"enrollment";intake=read(q/"intake.json");assert sha(q/"intake.json")==SIGNED["intake_sha256"]
    assert (intake["release_id"],intake["tag"],intake["tag_commit"],intake["manifest_rust"],intake["asset"])==(432227571,SIGNED["tag"],POLICY["official_release"],BASE,SIGNED["archive"])
    for name in ("verify.json","verify-asset.json"):
        result=read(q/name)["verificationResult"];statement=result["statement"];claim=statement["predicate"]
        subjects={s["name"]:s["digest"]["sha256"] for s in statement["subject"] if "name"in s}
        assert result["signature"]["certificate"]["subjectAlternativeName"]=="https://dotcom.releases.github.com"
        assert claim["repository"]==POLICY["repo"] and claim["tag"]==SIGNED["tag"] and int(claim["databaseId"])==432227571
        assert "sha256:"+subjects[SIGNED["archive"]["name"]]==SIGNED["archive"]["digest"]
        assert subjects[SIGNED["tag"]+".json"]==intake["manifest_sha256"]==sha(q/"published-manifest.json")
    return reg,role
def checkout(stage):
    e=os.environ;w=Path(e["GITHUB_WORKSPACE"]).resolve()
    assert (e["GITHUB_REPOSITORY"],e["GITHUB_REF"],e["GITHUB_EVENT_NAME"],e["GITHUB_ACTIONS"],e["GITHUB_RUN_ATTEMPT"],e["GITHUB_JOB"])==(POLICY["repo"],POLICY["branch"],"workflow_dispatch","true","1",stage)
    assert e["GITHUB_WORKFLOW_SHA"]==e["GITHUB_SHA"]==e["REVIEWED_HEAD"]==text(w,"rev-parse","HEAD")
    assert text(w,"rev-parse","HEAD^")==POLICY["coordinator_parent"]
    assert e["GITHUB_WORKFLOW_REF"]==POLICY["repo"]+"/.github/workflows/ci.yml@"+POLICY["branch"]
    reg,role=selected()
    changed=set(text(w,"diff-tree","--no-commit-id","-r","--no-renames","--name-only","HEAD^","HEAD").splitlines())
    assert changed==set(reg["changed_paths"])|{"scripts/rc23-driver-link/registration.json"}
    return w
def verify_sdk_receipts(w,src,role,proofs):
    reg,tt=selected();arm=os.environ["BENCH_ARM"]
    assert arm in ("R","T") and src["role"]==role["role"]==arm
    assert (src["commit"],src["tree"])==((BASE,TREE) if arm=="R" else (tt["commit"],tt["tree"]))
    assert (role["source_commit"],role["source_tree"])==(src["commit"],src["tree"])
    assert src["release_files"]==POLICY["release_files"] and role["execution_pgo"]==PGO
    assert role["source_sha256"]==proofs["source.json"]["sha256"] and role["effective_cargo"]==SIGNED["cargo"]
    assert all(proofs[k]["sha256"]==v for k,v in role["qa"].items())
    assert role["eii"]["normal"]==[11,12,13,14,11] and role["integrated"]["preloaded"]==([21,22,23,21,22,23] if arm=="R" else [11,22,23,21,22,23])
    assert role["pre_bolt"]["bolt_note"] is False and role["installed_elf"]["bolt_note"] is True and role["installed_elf"]["sha256"]==role["driver"]["sha256"]
    assert role["policy_evidence"]["arm"]==arm and role["signed_cargo_smoke"]["stdout"]=="ordinary cargo 19"
    out=w/"trait-sdk"; assert set(x.name for x in out.iterdir())=={"ohm.tar.gz","source.json","role.json","component-inventory.json","sdk-inventory.json","SHA256SUMS"}
    sums=(out/"SHA256SUMS").read_text().splitlines()
    expect=("ohm.tar.gz","source.json","role.json","sdk-inventory.json","component-inventory.json")
    assert sums==[sha(out/x)+"  "+x for x in expect] and sha(out/"role.json")==proofs["role.json"]["sha256"]
if __name__=="__main__":
    stage=sys.argv[1];checkout(stage)
    if stage=="plan": print('roles=["R","T"]')
    else: assert stage=="build" and os.environ["BENCH_ARM"] in ("R","T")
