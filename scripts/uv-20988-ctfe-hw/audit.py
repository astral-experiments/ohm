"""Verify source, original typed/exec streams, byte and semantic oracles before emitting the score."""
import gzip,json,sys,tempfile,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m, enroll, run, score
def journal(path,kind,ref,o,api):
    vals=(gzip.decompress((path/("cargo."+k+".gz")).read_bytes()) for k in ("stdout","stderr"))
    shape,actual=run.typed_events(*vals,kind,ref,o,api)
    m.guard(actual==m.read(path/"observed.json") and shape==m.shape(),"raw Cargo/argv journal or immutable graph changed")
def audit(out,opening):
    m.guard(m.read(out/"panel-finished.json")=={"observed_pairs":12,"primary_unscored_until_independent_replay":True},"incomplete panel")
    p=out/"intake";lock=enroll.lock(*[m.read(p/(k+".json")) for k in ("run","jobs","artifacts")]);m.guard(lock==m.read(p/"sdk-lock.json"),"hosted build metadata changed")
    pair=m.read(p/"pair-passed.json");m.guard(m.filesha(p/"cache-transition.json")==pair["cross_sdk_cache_rejection_sha256"],"migration proof")
    for role in score.ROLES:
        origin=p/"role-material"/role
        m.guard(pair["roles"][role]=={k:m.read(origin/(k+".json")) for k in ("role","source")},"producer qualification receipt changed")
        inventory={k:v["sha256"] for k,v in m.read(origin/"sdk-inventory.json").items()};inventory["bin/cargo"]=m.P["signed_cargo_sha256"]
        r=m.read(out/"final-sdk.json")[role];m.guard(r["files"]==len(inventory) and r["effective_inventory_sha256"]==m.digest(m.canon(inventory)),"final whole installed SDK")
    with tempfile.TemporaryDirectory() as td:
        o,api,decoder,trace=m.readers(opening,Path(td));shape=m.shape();ref=m.reference()
        trace.replay(out/"trace-calibration");m.guard(len(trace.mutations(out/"trace-calibration"))==4,"trace hostile checks")
        for role in score.ROLES:
            q=out/("qualification-"+role);proof=m.read(q/"four-state.json")["comparisons"]
            for n in ("settled-A","cold-B1-typed","cold-B2-typed"):journal(q/n,"background",ref,o,api)
            for k,l,h in (("cold-B1","A-to-B","cold-B1"),("cold-B2","A-to-B","cold-B2"),("both-independent-cold","cold-B1","cold-B2")):
                m.guard(run.compared(q/l,q/h,shape,api,decoder)==proof[k],"full cold root/definition/allocation oracle")
            for design in m.P["orders"]:
                path=out/f"hold{design['hold']}-pair{design['pair']:02d}-{role}"
                journal(path/"settled-A","background",ref,o,api);journal(path/"typed","edit",ref,o,api);trace.replay(path/"scoped")
                m.guard(run.compared(path/"native",q/"cold-B1",shape,api,decoder)==m.read(path/"accepted.json")["independent_cold"],"per-seed independent cold semantics")
    return score.report(out)
if __name__=="__main__":
    if len(sys.argv)==3:
        r=audit(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve());print(json.dumps(r,sort_keys=True,indent=2))
    elif sys.argv[1:]==["hosted"]:
        w,tmp=m.host();p=w/"trait-results";opening,_=m.check_sources(w)
        try:m.save(p/"result.json",audit(p,opening))
        except Exception:
            if not (p/"refusal.txt").exists():(p/"refusal.txt").write_text(traceback.format_exc())
            raise
    else:raise SystemExit("audit.py RESULTS PINNED_ROOT_READERS | hosted")
