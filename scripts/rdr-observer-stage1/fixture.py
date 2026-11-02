"""Exercise the same source, output filename, and compiler with observations off and on."""
import hashlib,subprocess
SOURCE=b"""pub struct Witness;
pub(crate) mod inside { pub struct Hidden; impl Hidden { pub(crate) fn value(&self) -> u8 { 17 } } }
impl Witness { pub fn call(&self) -> u8 { inside::Hidden.value() } }
"""
def run(rustc,env,out,record):
    root=out.parent/'observer-fixture';root.mkdir();tr=root/'trace';tr.mkdir();src=root/'subject.rs';src.write_bytes(SOURCE)
    product=root/'fixture.rmeta';args=[str(rustc),str(src),'--edition','2024','--crate-name','fixture','--crate-type','lib','-Zpublic-api-hash=yes','--emit','metadata='+str(product)]
    hashes=[]
    for active in (False,True,False):
        applied=dict(env);assert 'OHM_RDR_OBSERVER_DIR' not in applied
        if active:applied['OHM_RDR_OBSERVER_DIR']=str(tr.resolve())
        done=subprocess.run(args,env=applied,cwd=root,capture_output=True,check=True,timeout=80)
        raw=product.read_bytes();assert len(raw)>1024 and not done.stdout and not done.stderr
        hashes.append(hashlib.sha256(raw).hexdigest())
        assert len(list(tr.glob('*.rdr')))==int(active or len(hashes)==3)
    obs,=list(tr.glob('*.rdr'));lines=obs.read_text().splitlines();assert lines[0].startswith('OHRDR1 ') and lines[-1]=='END' and len(lines)>8
    assert len(set(hashes))==1
    (out/'observer-fixture.rdr').write_bytes(obs.read_bytes())
    record(out/'observer-smoke.json',{'same_source_metadata_sha256':hashes[0],'visits':['native','observer','native'],'trace_sha256':hashlib.sha256(obs.read_bytes()).hexdigest(),'trace_bytes':obs.stat().st_size,'header':lines[0],'footer':lines[-1],'classification':'diagnostic SDK; no performance eligibility'})
