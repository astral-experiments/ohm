"""Determine all physical Cargo compiler forms, including separate -Z and link-only arguments."""
from collections import Counter
from hashlib import sha256
import ast,io,json,re,subprocess,sys,tarfile,zipfile
from pathlib import Path
H=lambda b:sha256(b).hexdigest()
RE=re.compile(rb'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0$')
KITS={'signed':(12988097062,9880636,'49b6a7801f8f147e20df3052c5ed3ac4a978356f03a6552d38b3c8e11d6cabbe'),'293':(12987194256,9953970,'e3153c5b79d2a999c82ddd471599a3da4bde71febe0755bfd0bb514378a9c47c')}
def kind(argv):
 z=[]
 for i,value in enumerate(argv):
  if value=='-Z':
   assert i+1<len(argv);z.append(argv[i+1])
  elif value.startswith('-Z') and len(value)>2:z.append(value[2:])
 opts=[v for v in z if v=='link-only' or v.startswith('link-only=')]
 assert len(opts)<=1 and all(v in ('link-only','link-only=yes','link-only=no') for v in opts)
 native=bool(opts and opts[0]!='link-only=no')
 typed='--crate-name' in argv and any(v=='--emit' or v.startswith('--emit=') for v in argv)
 tag=next((argv[i+1] for i,v in enumerate(argv[:-1]) if v=='--target'),'host')
 if native:
  files=[v for v in argv if v.endswith('.rlink')];assert len(files)==1 and typed
  category='link_only';operand=files[0]
 elif typed:
  assert not any(v.endswith('.rlink') for v in argv)
  category='full_rustc';src=[v for v in argv if v.endswith('.rs')]
  assert len(src)==1,src;operand=src[0]
 else:category='probe';operand=None
 return category,tag,operand
def main(gh,out):
 endpoint='repos/astral-experiments/ohm/actions/'
 get=lambda n:subprocess.check_output([gh,'api',endpoint+n])
 meta={r['id']:r for r in json.loads(get('runs/41077287252/artifacts'))['artifacts']}
 result={}
 for mode,(id,length,key) in KITS.items():
  a=meta[id];assert (a['digest'],a['size_in_bytes'])==('sha256:'+key,length)
  b=get(f'artifacts/{id}/zip');assert H(b)==key and len(b)==length
  z=zipfile.ZipFile(io.BytesIO(b));old=json.loads(z.read('independent-native.json'))
  subjects={};sums=Counter()
  for label,rows in sorted(old['checks'].items()):
   phases={}
   for phase,pr in sorted(rows['physical_native'].items()):
    p=label+'/'+phase;data=z.read(p+'/trace.tar.gz');assert H(data)==pr['opening_trace']
    observed=Counter();targets=Counter();ev=[]
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
     for f in t:
      if not f.isfile():continue
      for line in t.extractfile(f).read().splitlines():
       if not line.startswith((b'execve(',b'execveat(')) or not line.endswith(b'= 0'):continue
       m=RE.fullmatch(line);assert m,line[:100]
       executable,argv=(ast.literal_eval(v.decode()) for v in m.groups())
       if not executable.endswith('/rustup/toolchains/ohm/bin/rustc'):continue
       k,target,operand=kind(argv);observed[k]+=1;targets[target+':'+k]+=1
       ev.append([f.name,int(f.name.rsplit('.',1)[1]),k,target,argv[argv.index('--crate-name')+1] if '--crate-name' in argv else None,H(json.dumps(argv,separators=(',',':')).encode()),operand])
    oc=pr['all_processes'];assert sum(observed.values())==sum(oc.get(n,0) for n in ('compile','link_only','compiler_probe'))
    assert observed['full_rustc']+observed['link_only']==oc.get('compile',0)+oc.get('link_only',0)
    sums.update(observed);phases[phase]={'physical':dict(sorted(observed.items())),'by_target':dict(sorted(targets.items())),'kernel_events':ev,'target_GNU_ld':pr['actual_provider_ld'],'opening_trace':H(data)}
   subjects[label]=phases
  assert sum(map(len,subjects.values()))==324
  result[mode]={'artifact':key,'original_counts_and_native':H(z.read('independent-native.json')),'total_Cargo':324,'physical_rustcs':dict(sums),'subjects':subjects}
 report={'run':41077287252,'scope':'Corrects only split -Z link-only classification in the two original 324-command provider arms. Every original Cargo verdict, ELF and actual GNU lookup remains preserved.','original_matched_safety':'23caaefad9facf7e5c400c15f77e6c18122dd81d0efae082d8989761dded7f94','modes':result}
 wire=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
 if out.exists():assert out.read_bytes()==wire
 else:out.open('xb').write(wire)
 print(H(wire),[(k,v['physical_rustcs']) for k,v in result.items()])
 for mode in ('signed','293'):
  for p in ('direct','library'):
   v=result[mode]['subjects']['M-undeclared-'+p]['higher']
   print(mode,p,v['physical'],v['target_GNU_ld'])
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]))
