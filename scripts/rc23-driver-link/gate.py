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
PATHS=(
    'compiler/rustc_codegen_ssa/src/back/linker.rs',
    'src/bootstrap/src/core/build_steps/compile.rs',
    'src/tools/lld-wrapper/src/main.rs',
    'tests/run-make/ohm-driver-preemption-link-modes/driver.rs',
    'tests/run-make/ohm-driver-preemption-link-modes/rmake.rs',
    'tests/run-make/ohm-driver-preemption-link-modes/supplier.rs',
)
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
    assert reg.get("source_generation")=="rlink-and-old-cc-corrected"
    assert sha(HERE/"accepted-control.json")=="fc222a09c9c75b7d6ceb73160240c319a225214e610ed6cb4cb040736428d6bf"
    assert sha(HERE/"previous-treatment.json")=="ab78c2c2b5a97b89024310a3c2343ef58407edf300e81af08d96a079cfd90d66"
    assert reg["previous_same_source_run"]==41629356922 and reg["roles"]==["T"]
    assert sha(HERE/"previous-phase-refusal.json")=="fd4b328f9cebd51d0e84fe0a7697edf0e4bc4731111bf0821302c02f02047521"
    assert read(HERE/"previous-phase-refusal.json")["complete_refusal_receipt_sha256"]=="379d5f2b8369bafbc4533526f0aa95505f9c252f85d43f79f45f2891b408b0eb"
    role=read(HERE/"source.json")
    assert role["commit"] not in (BASE,"1e84052bab906c68e8d63eecc806198d299b55c4")
    assert (role["parent"],role["parent_tree"])==(BASE,TREE)
    assert list(sorted(role["files"]))==list(PATHS) and role["commit"]!=BASE and role["tree"]!=TREE
    assert sha(HERE/"source.pack")==role["packet"]["sha256"]
    assert role["changed_formats"]==[] and sha(HERE/"source.json")=="d7b91ced743d0f95d277bd99188cde04a5b0d257ca86b18a407301b841b11a2a"
    assert sha(HERE/"source-qualified.json")=="ef3fe572c2b94dc88b93edd881d613151b8ec64ec3286dbc87435ce696278b33"
    native=read(HERE/"source-native.json")
    assert native["source"]==reg["treatment"]==role["commit"] and native["tree"]==role["tree"] and native["actual_conditional_release_authorized"]
    assert reg["source_changed_files"]==len(PATHS)==6 and len(role["packet"]["objects"])==23
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
    assert role["actual_linker_executions_sha256"]==proofs["linker-executions.json"]["sha256"]
    assert role["link_modes_sha256"]==proofs["link-modes.json"]["sha256"] and "old-cc-inputs.json" in role["qa"]
    native=read(w/"trait-evidence/installed-native.json");assert native["source"]==src["commit"] and native["tree"]==src["tree"]
    assert native["archive_sha256"]==role["archive_sha256"] and all(sha(w/"trait-evidence"/n)==digest for n,digest in native["proofs"].items())
    shown=read(w/"trait-evidence/linker-executions.json")
    observed=shown["source_selection_before_lto"];early=observed["early"]
    assert observed==read(w/"trait-evidence/source-observation.json") and role["qa"]["source-observation.json"]==proofs["source-observation.json"]["sha256"]
    assert early["target_pid"]==shown["producing_rustc_pid"] and early["lld_pid"]==shown["final_lld_pid"]
    assert early["qualified_matches"] and early["protected_inputs"] and any(p["provenance"]["name"]=="blake3" for p in early["proven_foreign"])
    assert shown["prior_unmodified_driver_links"]>=2 and observed["after_lto"]["object_count"]>0
    assert native["proofs"]["link-modes.json"]==role["link_modes_sha256"] and native["proofs"]["driver-witness/actual-interposition.json"]==sha(w/"trait-evidence/driver-witness/actual-interposition.json")
    out=w/"trait-sdk"; assert set(x.name for x in out.iterdir())=={"ohm.tar.gz","source.json","role.json","component-inventory.json","sdk-inventory.json","SHA256SUMS"}
    sums=(out/"SHA256SUMS").read_text().splitlines()
    expect=("ohm.tar.gz","source.json","role.json","sdk-inventory.json","component-inventory.json")
    assert sums==[sha(out/x)+"  "+x for x in expect] and sha(out/"role.json")==proofs["role.json"]["sha256"]
if __name__=="__main__":
    stage=sys.argv[1];checkout(stage)
    if stage=="plan": print('roles=["T"]')
    else: assert stage=="build" and os.environ["BENCH_ARM"]=="T"
