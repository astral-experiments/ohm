"""Exercise all shared-cache directions, linked coherence and intrinsic crate metadata epoch rejection."""
import os,re,shutil,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import material as m
import transition
from enroll import ROLES
def invoke(sdk,folder,name,args,expect,evidence):
    env={'HOME':str(folder),'PATH':str(sdk/'bin')+':/usr/bin:/bin','LC_ALL':'C.UTF-8','RUSTC_BOOTSTRAP':'1'}
    argv=[str(sdk/'bin/rustc'),'--sysroot',str(sdk),'--edition=2024','--error-format=json',*args]
    r=subprocess.run(argv,cwd=folder,env=env,capture_output=True,timeout=120)
    (evidence/(name+'.stdout')).write_bytes(r.stdout);(evidence/(name+'.stderr')).write_bytes(r.stderr)
    codes=[x['code']['code']for ln in r.stderr.splitlines()if (x:=__import__('json').loads(ln))['code']]
    assert r.returncode==(0 if expect is None else 1) and ((not codes)if expect is None else codes==[expect]),(name,r.returncode,codes,r.stderr[-700:])
    return {'argv':argv,'codes':codes,'rc':r.returncode,'stdout':m.digest(r.stdout),'stderr':m.digest(r.stderr)}
def run():
    w,tmp=m.host();out=w/'trait-results/intake';pool=tmp/'ctfe22-root-sdks';sdks={r:pool/r for r in ROLES}
    transition.run(*(sdks.values()),out/'cache-transition',tmp/'handwritten-cache-wire')
    trans=m.read(out/'cache-transition/passed.json');assert trans['native_processes']==16
    scratch=tmp/'handwritten-epoch-wire';scratch.mkdir();proof=out/'metadata-transition';proof.mkdir();rows={}
    (scratch/'wire.rs').write_text('pub struct Plain; impl Plain { pub fn value(&self) -> i32 { 17 } }\n')
    (scratch/'check_wire.rs').write_text('extern crate wire; fn main() { assert_eq!(wire::Plain.value(), 17); }\n')
    for r in ROLES:
        sdk=sdks[r];tag='old'if r==ROLES[0]else 'new';epoch=3 if tag=='old' else 43311;lib=scratch/('libwire_'+tag+'.rmeta')
        rows[tag+'-produce']=invoke(sdk,scratch,tag+'-produce',['--crate-name','wire','--crate-type=lib','--emit=metadata','wire.rs','-o',str(lib)],None,proof)
        link=['--crate-name','consumer','--emit=metadata','check_wire.rs']
        rows[tag+'-own']=invoke(sdk,scratch,tag+'-own',[*link,'--extern','wire='+str(lib)],None,proof)
        other=next(s for s in ROLES if s!=r);rows[tag+'-foreign']=invoke(sdks[other],scratch,tag+'-foreign',[*link,'--extern','wire='+str(lib)],'E0514',proof)
        raw=lib.read_bytes();mark=('(Ohm metadata '+str(epoch)+')').encode();where=raw.find(mark);assert raw.startswith(b'rust') and 0<where<256
        # Flip only the final digit of this compiler's own crate's version marker.
        index=where+len(mark)-2;new=bytes([raw[index]^1]);assert new.isdigit()
        mutated=raw[:index]+new+raw[index+1:];assert len(raw)==len(mutated) and sum(x!=y for x,y in zip(raw,mutated,strict=True))==1
        wrong=scratch/('libwire_'+tag+'_mutated.rmeta');wrong.write_bytes(mutated)
        rows[tag+'-intrinsic']=invoke(sdk,scratch,tag+'-intrinsic',[*link,'--extern','wire='+str(wrong)],'E0514',proof)
        shutil.copyfile(lib,proof/lib.name);shutil.copyfile(wrong,proof/wrong.name)
    m.save(proof/'passed.json',{'native_processes':len(rows),'cache_native_processes':trans['native_processes'],'rows':rows,'one_byte_per_role':True})
if __name__=='__main__':run()
