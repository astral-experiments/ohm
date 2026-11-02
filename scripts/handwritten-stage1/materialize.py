"""Reconstruct signed −22, then verify the two exact private qualification source trees."""
import hashlib,importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
H=Path(__file__).resolve().parent;W=Path(os.environ["GITHUB_WORKSPACE"]).resolve();REF=W/"release-reference";R=W/"source/rust";QA=W/"trait-evidence";S=json.loads((H/"arms.json").read_bytes())
def git(p,*cmd):return subprocess.check_output(["git","-C",p,*cmd],text=True).strip()
def sha(p):
 with Path(p).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def write(p,o):
 with p.open("x") as f:json.dump(o,f,sort_keys=True,indent=2);f.write("\n")
def load(p):
 spec=importlib.util.spec_from_file_location("qa_source",p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def assert_sources(manifest,source):
 subprocess.run([REF/"scripts/verify-release-sources.sh",manifest,R,*[R/"src/tools"/key for key in ("cargo","clippy","rustfmt")]],check=True)
 heads={key:git(R/"src/tools"/key,"rev-parse","HEAD","HEAD^{tree}").splitlines() for key in ("cargo","clippy","rustfmt")}
 assert {k:v[0] for k,v in heads.items()}=={k:S["source_components"][k] for k in heads}
 assert [v[1] for v in heads.values()]==[S["cargo_tree"],"597138f8e9a24972dd23acd15a8eee063c3a39f9","48c3ccd52f999a69778e9af7930b1d0408c7213c"]
 assert git(R,"rev-parse","HEAD")==source and not git(R,"diff","--name-only","HEAD","--","compiler","tests","src/tools/opt-dist")
 return heads
def main(role):
 assert role in ("fa7a_stack_ctfe318", "fa7a_stack_ctfe318_handwritten")
 arm=S["arms"][role];event=os.environ
 assert event["GITHUB_EVENT_NAME"]=="workflow_dispatch" and event["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and event["GITHUB_REF"]=="refs/heads/charlie/codex-20988-handwritten-stage1"
 assert git(W,"rev-parse","HEAD")==event["REVIEWED_HEAD"]==event["GITHUB_SHA"] and git(REF,"rev-parse","HEAD")==S["released_coordinator"]
 for path,oid in {"scripts/integrated-dist-qa":"2c2e6387acb6d2ac12ba7b35d337f02243447faa","scripts/dep-graph-slots":"40a553983d5d79b49f042af27b5816999860caf4","scripts/verify-release-sources.sh":"6d2652796e16b3152e181eedb772d725a42975dd","toolchains/manifest.schema.json":"47956809e9a9942075dae8456c757f5516f41950","toolchains/1.99.0/22.json":"e3e1e9b6bdd08cba01773237ae14a341670b2598"}.items():assert git(W,"rev-parse","HEAD:"+path)==oid
 manifest=REF/"toolchains/1.99.0/22.json";assert sha(manifest)==S["signed_manifest_sha256"]
 original=json.loads(manifest.read_bytes());assert {k:v["revision"] for k,v in original["sources"].items()}==S["source_components"]
 assert QA.is_dir() and not (QA/"source.json").exists();subprocess.run([sys.executable,"-IB",W/"scripts/integrated-dist-qa/sources.py"],check=True)
 donor=load(W/"scripts/dep-graph-slots/qualify.py");donor.install_source(W,R,W/"source/reports");donor.verify_live(R)
 (QA/"original-signed-source-verifier.log").write_bytes((W/"source/reports/verify-22.json.log").read_bytes())
 for root,rev in ((R,S["signed_rust"]),(R/"src/tools/cargo",S["source_components"]["cargo"])):git(root,"checkout","--no-recurse-submodules","--quiet","--detach",rev)
 assert git(R,"rev-parse","HEAD^{tree}")==S["signed_tree"]
 heads=assert_sources(manifest,S["signed_rust"])
 training={p:git(R,"rev-parse","HEAD:"+p) for p in ("src/tools/opt-dist","src/tools/rustc-perf","src/llvm-project","src/stage0","src/bootstrap")}
 packet=H/"candidates.pack";assert packet.stat().st_size==S["pack_bytes"] and sha(packet)==S["pack_sha256"]
 with packet.open("rb") as stream:
  receipt=subprocess.check_output(["git","-C",R,"index-pack","--strict","--stdin"],stdin=stream,text=True).split()
 idx=Path(git(R,"rev-parse","--absolute-git-dir"))/"objects/pack"/("pack-"+receipt[-1]+".idx")
 names=sorted(row.split()[0] for row in subprocess.check_output(["git","verify-pack","-v",idx],text=True).splitlines() if row and len(row.split()[0])==40)
 assert len(names)==len(set(names))==S["pack_objects"] and hashlib.sha256("".join(n+"\n" for n in names).encode()).hexdigest()==S["object_list_sha256"]
 assert git(R,"rev-parse",S["trait_commits"][0]+"^")==S["signed_rust"] and git(R,"rev-parse",S["trait_commits"][1]+"^")==S["trait_commits"][0]
 for item in S["arms"].values():
  rev=item["commit"];assert git(R,"rev-parse",rev+"^{tree}",rev+"^",rev+"^"+"^{tree}").splitlines()==[item["tree"],item["parent"],item["parent_tree"]]
  assert set(git(R,"diff","--name-only",item["parent"],rev).splitlines())==set(item.get("query_change_blobs",item["ctfe_blob_ids"])) and git(R,"diff","--name-only",S["signed_rust"],rev).splitlines()==item["paths_from_signed"]
  for p,oid in (item["ctfe_blob_ids"]|item.get("query_change_blobs",{})).items():assert git(R,"rev-parse",rev+":"+p)==oid
  for p,oid in training.items():assert git(R,"rev-parse",rev+":"+p)==oid
 git(R,"checkout","--no-recurse-submodules","--quiet","--detach",arm["commit"])
 assert all(git(R,"hash-object",p)==oid for p,oid in (arm["ctfe_blob_ids"]|arm.get("query_change_blobs",{})).items())
 header=(R/"compiler/rustc_incremental/src/persist/file_format.rs").read_text();assert "const HEADER_FORMAT_VERSION: u16 = "+str(arm["epoch"])+";" in header
 assert "const OHM_METADATA_EPOCH: u32 = "+str(S["metadata_epochs"][role])+";" in (R/"compiler/rustc_metadata/src/rmeta/mod.rs").read_text()
 original["sources"]["rust"]["revision"]=arm["commit"]
 with tempfile.TemporaryDirectory() as tmp:
  d=Path(tmp);(d/"1.99.0").mkdir();(d/"manifest.schema.json").write_bytes((REF/"toolchains/manifest.schema.json").read_bytes());m=d/"1.99.0/22.json";write(m,original)
  assert heads==assert_sources(m,arm["commit"])
 recipes={p:sha(REF/p) for p in ("release/bootstrap.toml","scripts/build-optimized-dist.sh","scripts/prepare-wild.py")}
 write(QA/"source.json",{"role":role,"source":arm,"signed_manifest_sha256":sha(manifest),"released_coordinator":S["released_coordinator"],"recipe":recipes,"training_objects":training,"component_git":heads,"source_pack_sha256":sha(packet),"evidence_repository":event["GITHUB_REPOSITORY"],"reviewed_head":event["GITHUB_SHA"],"workflow_ref":event["GITHUB_WORKFLOW_REF"],"run_id":int(event["GITHUB_RUN_ID"]),"run_attempt":int(event["GITHUB_RUN_ATTEMPT"]),"classification":"private optimized stage1 first-edit screen"})
if __name__=="__main__":main(*sys.argv[1:])
