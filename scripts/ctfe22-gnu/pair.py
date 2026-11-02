"""Verify two same-run SDKs and execute the original paired cache migration before admission."""
import os,re,sys
from pathlib import Path
H=Path(__file__).resolve().parent;sys.path.insert(0,str(H));import native,sdk as s,transition
ROLES=("stock_ctfe318","fa7a_stack_ctfe318")
def bindings(env,key):
 out={}
 for kind in ("SDK","QA"):
  ident=env[key+"_"+kind+"_ID"];dig=env[key+"_"+kind+"_SHA"].removeprefix("sha256:")
  assert re.fullmatch(r"[1-9]\d+",ident) and re.fullmatch(r"[a-f0-9]{64}",dig);out[kind.lower()]={"id":int(ident),"sha256":dig}
 return out
def source_identity(role,r,src,ctx):
 arm=native.S["arms"][role]
 assert r["role"]==src["role"]==role and src["source"]==arm and [r[k] for k in ("source_commit","source_tree","epoch")]==[arm[k] for k in ("commit","tree","epoch")]
 assert {k:src[k] for k in ctx}==ctx and src["released_coordinator"]==native.S["released_coordinator"] and src["signed_manifest_sha256"]==native.S["signed_manifest_sha256"] and src["source_pack_sha256"]==native.S["pack_sha256"]
 assert r["effective_benchmark_cargo_sha256"]==native.S["signed_cargo_binary_sha256"]
def validate(role,d,qa,root,ctx):
 src=s.read(d/"source.json");r=s.read(d/"role.json");source_identity(role,r,src,ctx)
 files={"ohm.tar.gz","source.json","role.json","sdk-inventory.json","component-inventory.json"}
 assert set(p.name for p in d.iterdir())==files|{"SHA256SUMS"}
 lines=(d/"SHA256SUMS").read_text().splitlines();names=[row[66:]for row in lines];assert len(names)==len(files) and set(names)==files
 for row,k in zip(lines,names):assert (d/k).is_file() and not (d/k).is_symlink() and row==s.sha(d/k)+"  "+k
 assert (d/"ohm.tar.gz").stat().st_size==r["archive_bytes"]
 for name,k in [("ohm.tar.gz","archive_sha256"),("source.json","source_sha256"),("sdk-inventory.json","sdk_inventory_sha256"),("component-inventory.json","component_inventory_sha256")]:assert s.sha(d/name)==r[k]
 for n in ("source.json","role.json"):assert s.sha(qa/n)==s.sha(d/n)
 for k in ("unit","run-make"):
  f=qa/(k+".log");assert s.sha(f)==r["unit_and_original_runmake"][k]["log_sha256"];text=f.read_text(errors="replace");native.gate_log(text,k)
  if k=="run-make":native.gate_suites(text,role)
 q=r["installed_original_runmake"];assert q["compiler_sha256"]==r["launcher"]["sha256"] and q["driver_sha256"]==r["driver"]["sha256"] and q["original_files"]==native.fixture(role,H/"fixture") and q["exit"]==0 and q["final_linked_output"]=="LShift Or false 17\n" and q["log_sha256"]==s.sha(qa/"optimized-run-make.log")
 assert r["execution_pgo"]==native.PGO and r["bolt_note"] is True and r["training_objects"]==src["training_objects"] and r["release_recipe"]==src["recipe"] and r["execution_pgo"] in (qa/"build.log").read_text(errors="replace").splitlines()
 installed,inv=s.extract(d/"ohm.tar.gz",root);assert s.sha(inv)==r["sdk_inventory_sha256"] and s.sha(root/"component-inventory.json")==r["component_inventory_sha256"]
 db=s.read(inv);assert len(db)>100
 for k in ("launcher","driver","llvm","bundled_cargo"):
  p=r[k]["path"];assert r[k]==db[p]|{"path":p} and s.sha(installed/p)==db[p]["sha256"]
 return r,src,installed
def main():
 e=os.environ;w=Path(e["GITHUB_WORKSPACE"]).resolve();archive=w/"intake";out=w/"pair-evidence";out.mkdir();tmp=w/"pair-native";tmp.mkdir()
 ctx={"evidence_repository":"astral-experiments/ohm","reviewed_head":e["GITHUB_SHA"],"workflow_ref":e["GITHUB_WORKFLOW_REF"],"run_id":int(e["GITHUB_RUN_ID"]),"run_attempt":int(e["GITHUB_RUN_ATTEMPT"])}
 assert e["GITHUB_EVENT_NAME"]=="workflow_dispatch" and e["GITHUB_REF"]=="refs/heads/charlie/codex-ctfe22-standard-20988" and ctx["reviewed_head"]==e["REVIEWED_HEAD"]
 arts={};roles={};roots={}
 for role,key in zip(ROLES,("STOCK","TRAITS")):
  root=tmp/role;root.mkdir();r,src,roots[role]=validate(role,archive/role,archive/(role+"-qa"),root,ctx);roles[role]={"role":r,"source":src};arts[role]=bindings(e,key)
 assert len({v["id"]for row in arts.values()for v in row.values()})==4 and len({v["sha256"]for row in arts.values()for v in row.values()})==4
 a,b=(roles[k] for k in ROLES)
 for k in ("recipe","training_objects","component_git"):assert a["source"][k]==b["source"][k]
 assert a["role"]["driver"]["sha256"]!=b["role"]["driver"]["sha256"] and a["role"]["archive_sha256"]!=b["role"]["archive_sha256"]
 transition.run(roots[ROLES[0]],roots[ROLES[1]],out/"cache-transition",tmp/"switch");q=s.read(out/"cache-transition/passed.json")
 assert q["native_processes"]==16 and set(q["modes"])=={"ordinary","shared-rustc-perf-version"} and all(set(q["modes"][mode])=={ROLES[0]+"-to-"+ROLES[1],ROLES[1]+"-to-"+ROLES[0]} for mode in q["modes"])
 s.save(out/"passed.json",{"classification":"unsigned matched GNU builds; source and native regression qualification only","github":ctx,"artifacts":arts,"roles":roles,"cross_sdk_cache_rejection_sha256":s.sha(out/"cache-transition/passed.json"),"required_benchmark_cargo_sha256":native.S["signed_cargo_binary_sha256"]})
if __name__=="__main__":main()
