"""Check actual derived, ordinary, generic, one-unit, and global-assembly placements on a tiny Cargo client."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys
source,root=map(lambda p:Path(p).resolve(),sys.argv[1:3]);role=sys.argv[3];assert role in ('P','C')
root.mkdir(parents=True);work=root/'src';work.mkdir()
for filename in ('Cargo.toml','Cargo.lock','make/Cargo.toml','make/src/lib.rs','owner_case/Cargo.toml','owner_case/src/main.rs'):
 p=work/filename;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/filename,p)
env={**os.environ,'CARGO_HOME':str(root/'home'),'CARGO_TARGET_DIR':str(root/'target'),'CARGO_BUILD_BUILD_DIR':str(root/'build'),'CARGO_NET_OFFLINE':'true','CARGO_BUILD_JOBS':'1'}
p=work/'owner_case/src/main.rs';base=p.read_text()
add='''
struct Manual(i64);
impl Score for Manual {
    #[inline(never)] fn twice(&self,y:i64)->i64 { std::hint::black_box(self.0*y) }
    #[inline(never)] fn add(&self,y:i64)->i64 { std::hint::black_box(self.0+y) }
}
struct Generic<T>(T);
#[automatically_derived]
impl<T: Copy + Into<i64>> Score for Generic<T> {
    #[inline(never)] fn twice(&self,y:i64)->i64 { std::hint::black_box(self.0.into()*y) }
    #[inline(never)] fn add(&self,y:i64)->i64 { std::hint::black_box(self.0.into()+y) }
}
'''
use='assert_eq!(Manual(2).twice(v)+Manual(2).add(v),3*v+2); assert_eq!(Generic(3i64).twice(v)+Generic(3i64).add(v),4*v+3);'
base=base.replace('    let value=',use+'\n    let value=')+add
asm='''std::arch::global_asm!(".global guard_native", ".type guard_native,@function", "guard_native:", "mov eax, 37", "ret");
unsafe extern "C" { fn guard_native()->i32; }'''
cases={}
for label,text,cap in [('ordinary',base,16),('asm',base.replace('    let value=','assert_eq!(unsafe{guard_native()},37);\n    let value=')+asm,16),('one',base,1)]:
 p.write_text(text);args=['cargo','+ohm','rustc','-p','owner_case','--offline','--','-Zprint-mono-items=yes','-Zhuman-readable-cgu-names=yes','-Ccodegen-units='+str(cap)]
 r=sp.run(args,cwd=work,env=env,capture_output=True);(root/(label+'.stdout')).write_bytes(r.stdout);(root/(label+'.stderr')).write_bytes(r.stderr);assert r.returncode==0,(label,r.stderr[-1500:])
 rows=[line for line in r.stdout.decode().splitlines()if line.startswith('MONO_ITEM ')];picked={}
 for ty in ('Alpha','Beta','Gamma','Manual','Generic<i64>'):
  matches=[s for s in rows if '<'+ty+' as Score>' in s and re.search(r'::(add|twice) @@ ',s)];assert len(matches)==2,(ty,matches)
  units={s.split(' @@ ',1)[1].split('[',1)[0].strip()for s in matches};assert len(units)==1,(label,ty,units);picked[ty]=units.pop()
  eligible=role=='C'and label=='ordinary'and ty in ('Alpha','Beta','Gamma');assert ('-ohm-derived-'in picked[ty])==eligible,(label,ty,eligible,picked)
 if role=='C'and label=='ordinary':assert len(set(picked[t]for t in('Alpha','Beta','Gamma')))==3,picked
 executable=root/'target/debug/owner_case';values=[sp.check_output([executable,str(x)],text=True,env=env).strip()for x in (4,9)];assert values==['119','179'],values
 total={a for s in rows for a in re.findall(r' ([^ ]+)\[(?:External|Available|OnceAny|OnceODR|WeakAny|WeakODR|Internal|ExternalWeak|Common)\]',s.split(' @@',1)[1])}
 assert 0<len(total)<=cap,(label,len(total),cap)
 cases[label]={'owners':picked,'actual_units':len(total),'cap':cap,'verdict':values,'mono_sha256':hashlib.sha256(r.stdout).hexdigest()}
(root/'guard-verdict.json').write_text(json.dumps({'role':role,'cases':cases},sort_keys=True,indent=2)+'\n')
