"""Exercise the explicit shard ceiling, including a true existing size split with derived roots."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,sys
fixture,root=map(lambda x:Path(x).resolve(),sys.argv[1:3]);role=sys.argv[3];assert role in ('P','C','prior')
root.mkdir();work=root/'fixture';work.mkdir()
for n in ('Cargo.toml','Cargo.lock','make/Cargo.toml','make/src/lib.rs','owner_case/Cargo.toml','owner_case/src/main.rs'):
 p=work/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(fixture/n,p)
env=dict(os.environ,CARGO_HOME=str(root/'registry'),CARGO_TARGET_DIR=str(root/'target'),CARGO_BUILD_BUILD_DIR=str(root/'build'),CARGO_NET_OFFLINE='true',CARGO_BUILD_JOBS='2')
src=work/'make/src/lib.rs';small=src.read_text();base=Path('owner_case/src/main.rs')
def run(label,limit):
 argv=['cargo','+ohm','rustc','-p','owner_case','--offline','--','-Zprint-mono-items=yes','-Zhuman-readable-cgu-names=yes','-Ccodegen-units=64']
 if limit is not None:argv+=['-Zohm-cgu-split-limit='+str(limit)]
 out=subprocess.run(argv,env=env,cwd=work,capture_output=True);(root/(label+'.out')).write_bytes(out.stdout);(root/(label+'.err')).write_bytes(out.stderr);assert out.returncode==0,(label,out.stderr[-1000:])
 found={}
 for ty in ('Alpha','Beta','Gamma'):
  rows=[s for s in out.stdout.decode().splitlines()if s.startswith('MONO_ITEM ')and '<'+ty+' as Score>'in s and re.search(r'::(add|twice) @@ ',s)];assert len(rows)==2,(label,ty,rows)
  found[ty]=sorted({s.split(' @@ ',1)[1].split('[',1)[0]for s in rows})
 allunits={n for s in out.stdout.decode().splitlines()if s.startswith('MONO_ITEM ')for n in re.findall(r' ([^ ]+)\[(?:Internal|External|Available|OnceAny|OnceODR|WeakAny|WeakODR|Common)\]',s.split(' @@',1)[1])}
 assert len(allunits)<=64
 binary=root/'target/debug/owner_case';vals=[subprocess.check_output([binary,str(v)],env=env,text=True).strip()for v in (4,9)];assert vals==['119','179']
 flat={u for group in found.values()for u in group};return {'owner_units':found,'all_units':sorted(allunits),'units_for_owners':len(flat),'derived_units':len({u for u in flat if '-ohm-derived-'in u}),'size_units':len({u for u in flat if '-ohm-split-'in u}),'combined':[u for u in sorted(allunits)if'-ohm-split-'in u and'-ohm-derived-'in u],'runtime':vals,'compiler_stdout_sha256':hashlib.sha256(out.stdout).hexdigest()}
cases={k:run(k,n)for k,n in [('default',None),('limit1',1),('limit2',2)]}
assert cases['default']['units_for_owners']==(1 if role=='P'else 3),cases
if role!='prior':assert cases['limit1']['units_for_owners']==1 and cases['limit1']['derived_units']==0 and cases['limit2']['units_for_owners']<=(1 if role=='P'else 2),cases
else:assert cases['limit1']['derived_units']>0,cases
# Preserve the observable score but make each genuine derive method large in *pre-LLVM* MIR.
# Its outer size partition must already have spent the complete limit of two shards.
stmt='let mut mix=(y as u64).wrapping_add(self.0 as u64);'+''.join(f'mix=mix.wrapping_mul(6364136223846793005).wrapping_add({i+1});'+('std::hint::black_box(mix);' if i%32==0 else '')for i in range(4096))+'std::hint::black_box(mix);'
assert small.count('std::hint::black_box(self.0')==2
src.write_text(small.replace('std::hint::black_box(self.0',stmt+'std::hint::black_box(self.0'))
cases['already-two']=run('already-two',2);raw=cases['already-two'];assert raw['size_units']>=2 or raw['combined'],cases
if role!='prior':assert raw['size_units']==2 and not raw['combined']and raw['units_for_owners']==2,raw
(root/'caps.json').write_text(json.dumps({'role':role,'cases':cases},sort_keys=True,indent=2)+'\n')
