"""Validate the reviewed source choice before reserving a production runner or admitting its SDK."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
POLICY = json.loads((HERE / "policy.json").read_bytes())
CTFE = "rdr-public-hash-ctfe-literal-identity"
CALLABLE = ("trait-impl-bucket-coroutine", "trait-impl-bucket-callables", "trait-impl-bucket-sparse-foreign")
DOMAIN = "crate-incoherent-impl-domain"
DERIVE = "proc-derive-impl-identity"
UNIT = "only_the_original_ctfe_literal_id_is_restored"
DERIVE_UNIT = "a_derived_slot_reserves_the_dense_ordinal_and_preserves_full_hash_collision_errors"
PGO = "verified executed PGO profile coverage for rustc, rustdoc, Cargo, Clippy, rustfmt, and cargo-fmt"
INC = "compiler/rustc_incremental/src/persist/file_format.rs"
META = "compiler/rustc_metadata/src/rmeta/mod.rs"
FORMAT = {INC:"HEADER_FORMAT_VERSION", META:"OHM_METADATA_EPOCH"}

def need(ok, error):
    if not ok:
        raise ValueError(error)

def h(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def oid(raw):
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()

def read(path):
    return json.loads(Path(path).read_bytes())

def write(path, record):
    with Path(path).open("x") as f:
        json.dump(record, f, indent=2, sort_keys=True)
        f.write("\n")

def g(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], env=os.environ | {"GIT_NO_LAZY_FETCH":"1"})

def text(repo, *args):
    return g(repo,*args).decode().strip()

def cargo_digest(s):
    need(isinstance(s,str) and re.fullmatch(r"[0-9a-f]{64}",s), "signed Cargo SHA")
    return s

def scopes(role):
    if role == "G":
        return scopes("full_with_ctfe") + [selected()["roles"]["G"]["run_make"]]
    need(role in POLICY["default_stock"] + POLICY["matched_recorded_ctfe"], "unknown role")
    cases=["rdr-public-hash-native-exports", "trait-impl-bucket-projection"]
    if role != "full_without_ctfe":
        cases.append(CTFE)
    if role != "ctfe_control":
        cases.extend([*CALLABLE,DOMAIN,DERIVE])
    return cases

def version(raw,path,old,value):
    need(type(value) is int and 0 < value <= 65535, "externally assigned format")
    sym=FORMAT[path]
    pat=rb"(?m)^(const "+sym.encode()+rb": u(?:16|32) = )"+str(old).encode()+rb"(;)$"
    changed,n=re.subn(pat,lambda m:m[1]+str(value).encode()+m[2],raw)
    need(n==1,"exactly one original format declaration "+sym)
    return changed

def baseline_selected(q=None):
    q=HERE/"enrollment" if q is None else Path(q)
    enrollment=read(q/"enrollment.json")
    from split_choice import make_choice
    choice=make_choice(q)
    need(choice==read(q/"signed-23-split-choice.json"),"split case choice differs from raw receipts")
    role=read(q/"signed-role.json")
    alloc=read(q/"assigned.json")
    raw_signed=read(q/"published-manifest.json")
    expected=POLICY["sources"]
    need(enrollment["schema"]==2 and enrollment["authorization_sha256"]==h(q/"assigned.json"),"split assignment digest")
    need({v.name for v in q.glob("*.pack")}=={"ctfe_control.pack","full_with_ctfe.pack"},"unexpected production packs")
    digests=enrollment["gates"]
    named={p.name for p in q.iterdir() if p.is_file() and p.name!="enrollment.json" and p.suffix!=".pack"}
    need(set(digests)==named and all(h(q/name)==value for name,value in digests.items()),"split enrollment input change")
    need(raw_signed["sources"]=={n:{"repository":v["repository"],"revision":expected[n]["revision"]} for n,v in raw_signed["sources"].items()}
         and set(raw_signed["sources"])==set(expected) and h(q/"published-manifest.json")==read(q/"intake.json")["manifest_sha256"]==POLICY["release_files"]["toolchains/1.99.0/23.json"]["sha256"],
         "wrong signed source manifest")
    intake=read(q/"intake.json")
    need(choice["commits"]=={n:expected[n]["revision"] for n in ("rust","cargo")} and role["tag"]==POLICY["tag"],"unexpected released sources")
    for name in ("verify.json","verify-asset.json"):
        signed=read(q/name)["verificationResult"];statement=signed["statement"];pred=statement["predicate"]
        subjects={v["name"]:v["digest"]["sha256"]for v in statement["subject"]if "name"in v}
        need(signed["signature"]["certificate"]["subjectAlternativeName"]=="https://dotcom.releases.github.com"
             and pred["repository"]==POLICY["repo"] and pred["tag"]==POLICY["tag"] and int(pred["databaseId"])==int(role["release_id"])
             and subjects[POLICY["tag"]+".json"]==intake["manifest_sha256"]
             and "sha256:"+subjects[role["signed_archive"]["name"]]==choice["signed_archive"],"signed subjects")
    roles=choice["roles_after_actual_23_intake"]
    need(roles==["ctfe_control","full_with_ctfe"]==enrollment["role_order"] and set(enrollment["roles"])==set(roles),"unqualified split roles")
    need(cargo_digest(role["runtime"]["bin/cargo"])==enrollment["signed_cargo_sha256"],"wrong signed Cargo")
    need(set(alloc["role_epochs"])==set(roles) and len(set(alloc["role_epochs"].values()))==len(roles),"namespace/role mismatch")
    survey=read(q/"survey.json")
    need(alloc["schema"]==2 and alloc["registration_sha256"]==choice["registration_sha256"] and alloc["release_rust"]==survey["release_rust"]==expected["rust"]["revision"]
         and alloc["pair_sha256"]==choice["pair_sha256"] and alloc["split_choice_sha256"]==h(q/"signed-23-split-choice.json") and
         alloc["live_upstream_survey"]["sha256"]==h(q/"survey.json") and survey["viewer"]=="charliermarsh" and not survey["nonliteral_expressions"],
         "externally approved namespace survey")
    need(alloc["local_census_sha256"]==digests["local-epochs.json"]==h(q/"local-epochs.json"),"actual task source epochs")
    used=set(survey["used_literals"])|set(read(q/"local-epochs.json")["excluded_integers_at_least"])|set(alloc["additional_live_task_reservations"])|{26655,26656,43322}
    need(used and all(type(k)is int and max(used)<k<=65535 for k in alloc["role_epochs"].values()),"occupied/wrong epoch")
    layers=read(HERE/"layers.json")
    need(survey["owning_heads"]==layers["owning_heads"],"owning head census")
    need(h(HERE/"layers.json")==POLICY["input_layers_sha256"] and h(HERE/"accept_packet.py")==POLICY["semantic_source_receiver_sha256"],"wrong semantic inputs")
    for label in roles:
        r=enrollment["roles"][label];temp=layers["role_templates"][label];v=alloc["role_epochs"][label]
        need(type(v)is int and 0<v<=65535 and r["epoch"]==v and r["metadata_epoch"]==(3 if label=="ctfe_control"else v)
             and r["parent"]==layers["base"] and r["template_tree"]==temp["tree"] and r["template_commit"]==temp["template_commit"]
             and r["commit"]!=r["template_commit"] and r["tree"]!=r["template_tree"],"unapproved source allocation")
        need(r["packet"]["path"]==label+".pack" and h(q/r["packet"]["path"])==r["packet"]["sha256"]
             and h(HERE/"templates"/r["packet"]["path"])==temp["packet"]["sha256"],"wrong selected packet")
    return enrollment

def selected():
    from candidate import selected as one_candidate
    return one_candidate(baseline_selected())

def checkout(stage):
    e=os.environ;w=Path(e["GITHUB_WORKSPACE"]).resolve()
    need(e["GITHUB_REPOSITORY"]==POLICY["repo"] and e["GITHUB_REF"]==POLICY["branch"] and e["GITHUB_EVENT_NAME"]=="workflow_dispatch"
         and e["GITHUB_ACTIONS"]=="true" and e["GITHUB_RUN_ATTEMPT"]=="1" and e["GITHUB_JOB"]==stage
         and e["GITHUB_WORKFLOW_SHA"]==e["GITHUB_SHA"]==e["REVIEWED_HEAD"]==text(w,"rev-parse","HEAD")
         and text(w,"rev-parse","HEAD^")==POLICY["coordinator_parent"],"unreviewed workflow context")
    need(e["GITHUB_WORKFLOW_REF"]==POLICY["repo"]+"/.github/workflows/ci.yml@"+POLICY["branch"],"workflow ref")
    remote_paths=text(w,"diff-tree","--no-commit-id","-r","--no-renames","--name-only","HEAD^","HEAD").splitlines()
    need(".github/workflows/ci.yml"in remote_paths and "scripts/rc23-22958-production/candidate.py"in remote_paths and
         all(p == ".github/workflows/ci.yml"or p.startswith("scripts/rc23-22958-production/")for p in remote_paths),"unregistered coordinator delta")
    return w

def verify_sdk_receipts(w,src,role,proofs):
    e=selected();name=os.environ["BENCH_ARM"];arm=e["roles"][name]
    need(src["role"]==role["role"]==name and src["source"]==arm and role["source_sha256"]==proofs["source.json"]["sha256"],"source/SDK role")
    for field, src_field in (("source_commit","commit"),("source_tree","tree"),("epoch","epoch"),("metadata_epoch","metadata_epoch")):
        need(role[field]==arm[src_field],field)
    need(role["effective_benchmark_cargo_sha256"]==e["signed_cargo_sha256"] and role["bolt_note"] and role["execution_pgo"]==PGO
         and role["relocated_dependencies"] and src["release_files"]==POLICY["release_files"],"release recipe")
    expected=scopes(name)
    need(set(role["installed_runmake"])==set(expected) and set(role["native_unit_and_runmake"])==
         ({"run-make"} | ({"ctfe-unit"}if name!="full_without_ctfe"else set()) | ({"derive-unit"}if name!="ctfe_control"else set())),"native test roster")
    new_test=role["installed_runmake"][arm["run_make"]]
    llvm_nm=w/"rc23-test-build"/POLICY["target"]/"ci-llvm/bin/llvm-nm"
    need(new_test["llvm_nm"]["path"]==str(llvm_nm) and new_test["llvm_nm"]["sha256"]==h(llvm_nm)
         and new_test["llvm_nm"]["version"] and new_test["linked_outputs"]==arm["linked_outputs"],"installed handwritten symbol tool or linked output")
    for group in (role["installed_runmake"],role["native_unit_and_runmake"]):
        for record in group.values():
            need(record["exit"]==0 and record["log_sha256"]==proofs[record["log"]]["sha256"],"native test log")
    for record in role["installed_runmake"].values():
        need(record["driver_sha256"]==role["driver"]["sha256"],"wrong installed native driver")
    need(role["archive_sha256"]==h(w/"trait-sdk/ohm.tar.gz") and role["archive_bytes"]==(w/"trait-sdk/ohm.tar.gz").stat().st_size,"archive custody")

if __name__=="__main__":
    mode,=sys.argv[1:];w=checkout(mode);record=selected()
    if mode=="plan":
        print("roles="+json.dumps(record["role_order"],separators=(",",":")))
    else:
        need(mode=="build" and os.environ["BENCH_ARM"] in record["role_order"],"worker role")
        for path,expected in POLICY["source_checkouts"].items():
            need(text(w/path,"rev-parse","HEAD")==expected,"source carrier revision "+path)
        need(text(w/"official-release","rev-parse","HEAD")==POLICY["official_release"],"release build coordinator")
