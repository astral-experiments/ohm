"""Reopen the complete consumer traces, mutable-provider bytes and same-source empty ELFs."""
from collections import Counter
from pathlib import Path
from hashlib import sha256
import ast,gzip,io,json,re,sys,tarfile,zipfile
H=lambda b:sha256(b).hexdigest()
EXEC=re.compile(rb'^execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0$')
END=re.compile(rb'^\+\+\+ exited with (\d+) \+\+\+$',re.M)
SUCC=re.compile(r'= \d+$')
expect={'higher':'29 7','removed-higher':'17 7','same-inode-value':'29 7','real-Rust-edit':'29 11',
        'same-inode-malformed':None,'repaired-edit':'29 13','missing':None,'restored-edit':'17 19','restored-repeat':'17 19'}
class Directory:
 def __init__(self,p):self.p=p
 def read(self,n):return (self.p/n).read_bytes()
def logs(z,p,code,elf,expected,qemu):
 r=json.loads(z.read(p+'/result.json'));assert r['exit']==code and r['elf']==elf
 out=gzip.decompress(z.read(p+'/stdout.gz'));err=gzip.decompress(z.read(p+'/stderr.gz'))
 events=[json.loads(x) for x in out.splitlines()];assert events[-1]=={'reason':'build-finished','success':code==0}
 if code==0:
  c=json.loads(z.read(p+'/qemu/command.json'));b=gzip.decompress(z.read(p+'/qemu/stdout.gz'))
  assert c['exit']==0 and b==r['answer'].encode()+b'\n' and H(b)==c['stdout'] and c['argv'][0].endswith('/qemu-aarch64') and c['argv'][-1].endswith('/aarch64-unknown-linux-gnu/debug/qa_owned_test')
  assert H(gzip.decompress(z.read(p+'/qemu/stderr.gz')))==c['stderr']
  if elf not in qemu:
   raw=z.read('objects/'+elf+'.elf')
   assert H(raw)==elf and raw[:6]==b'\x7fELF\x02\x01' and int.from_bytes(raw[18:20],'little')==183
   qemu[elf]=len(raw)
 else:assert b'qa_owned_external' in out+err
 wire=z.read(p+'/trace.tar.gz');assert H(wire)==r['trace']
 lookups=[];candidates=[];ldp=[];counts=Counter()
 with tarfile.open(fileobj=io.BytesIO(wire)) as tar:
  for f in tar:
   if not f.isfile():continue
   body=tar.extractfile(f).read()
   successful=[]
   for line in body.splitlines():
    if not line.startswith((b'execve(',b'execveat(')) or not line.endswith(b'= 0'):continue
    m=EXEC.fullmatch(line);assert m,line[:200]
    true,av=(ast.literal_eval(b.decode()) for b in m.groups())
    successful.append((true,av));n=Path(true).name
    if true.endswith('/rustup/toolchains/ohm/bin/cargo'):
     assert r['argv'][0:2]==['cargo','+ohm'] and av[1:]==r['argv'][2:] and tuple(map(int,END.findall(body)))==(code,)
     counts['Cargo']+=1
    elif true.endswith('/rustup/toolchains/ohm/bin/rustc'):
     typ='link_only' if any(a.startswith('-Zlink-only') for a in av) else 'compile' if '--crate-name' in av and any(a=='--emit' or a.startswith('--emit=') for a in av) else 'compiler_probe'
     counts[typ]+=1
    elif n in ('aarch64-linux-gnu-gcc','aarch64-linux-gnu-gcc-14'):counts['cross_gcc']+=1
    elif n=='collect2':counts['collect2']+=1
    elif n in ('ld','ld.bfd','ld.lld','aarch64-linux-gnu-ld','aarch64-linux-gnu-ld.bfd'):counts['all_ld']+=1
   if not any(Path(t).name in ('ld','ld.bfd','ld.lld','aarch64-linux-gnu-ld','aarch64-linux-gnu-ld.bfd') for t,av in successful):continue
   l=[v.decode() for v in body.splitlines() if b'openat(' in v and b'libqa_owned_external.a' in v]
   ldp.append(f.name.split('/')[-1])
   if l:
    candidates.append(f.name);lookups.extend(l)
 assert counts['Cargo']==1 and sorted(ldp)==sorted(r['actual_GNU_linkers'])
 assert sorted(lookups)==sorted(r['native_lookup'])
 opens=[x for x in lookups if SUCC.search(x)];assert sorted(opens)==sorted(r['selected'])
 prov=sorted({'early' if '/early/' in x else 'late' if '/late/' in x else 'other' for x in opens})
 if expected:
  assert candidates and counts['cross_gcc']>=1 and counts['collect2']>=1
  assert any('/early/' in x for x in lookups)
 return {'cargo_exit':code,'answer':r['answer'],'elf':elf,'all_processes':dict(sorted(counts.items())),'actual_provider_ld':len(candidates),'selected_provider':prov,
         'earlier_negative':any('/early/' in v and 'ENOENT' in v for v in lookups),'later_negative':any('/late/' in v and 'ENOENT' in v for v in lookups),'opening_trace':H(wire),'receipt':H(z.read(p+'/result.json'))}
def verify(z):
 j=lambda n:json.loads(z.read(n));info=j('native-group.json');tag=info['cargo'];assert tag in ('293','signed')
 assert len(info['all'])==18;res={};elfs={};rogue=[]
 for label,summary in sorted(info['all'].items()):
  role,watch,place=label.split('-');src=j(label+'/completed.json');mut=j(label+'/physical-provider-bytes.json')
  assert H(z.read(label+'/completed.json'))==summary['complete'] and H(z.read(label+'/physical-provider-bytes.json'))==summary['physical_mutations']
  assert src['source']==info['all_role_sources'][role] and src['placement']==place and src['defaults']
  for name in ('value','malformed','repair'):
   a,b=(mut[name][k] for k in ('before','after'))
   assert all(a[field]==b[field] for field in ('dev','ino','mtime_ns','size','mode','nlink')) and a['nlink']==1
   assert a['sha256']!=b['sha256'] and a['ctime_ns']<=b['ctime_ns']
   for h in (a['sha256'],b['sha256']):
    native=z.read('objects/'+h+'.a');assert H(native)==h and len(native)==a['size']
  assert mut['value']['before']['sha256']==mut['distinct_native_archives']['lower']['sha256']
  assert mut['value']['after']['sha256']==mut['distinct_native_archives']['higher']['sha256']
  assert mut['malformed']['before']['sha256']==mut['repair']['after']['sha256']==mut['value']['after']['sha256']
  jobs={r['name']:r for r in src['cases']};assert len(jobs)==len(src['cases'])==18
  native={}
  for n,rec in jobs.items():
   assert j(label+'/'+n+'/result.json')==rec
   native[n]=logs(z,label+'/'+n,rec['exit'],rec['elf'],n.startswith('empty-') or n=='cold-lower',elfs)
  mismatch=[]
  for n,answer in expect.items():
   empty='empty-'+('restored-edit' if n=='restored-repeat' else n);a,b=native[n],native[empty]
   want='early' if n=='higher' else 'late'
   assert b['answer']==answer and b['cargo_exit']==(101 if answer is None else 0) and b['actual_provider_ld']>=1
   if answer is not None:assert b['selected_provider']==[want]
   if n=='same-inode-malformed':assert 'late' in b['selected_provider']
   if n=='missing':assert not b['selected_provider'] and b['earlier_negative'] and b['later_negative']
   if (a['cargo_exit'],a['answer'],a['elf'])!=(b['cargo_exit'],b['answer'],b['elf']):mismatch.append(n)
   # The safety claim requires ordinary mutable searches to run the GNU linker and see exactly what the cold command saw.
   if tag=='293' and (a['actual_provider_ld']<1 or a['selected_provider']!=b['selected_provider'] or a['earlier_negative']!=b['earlier_negative'] or a['later_negative']!=b['later_negative']):rogue.append([label,n,'missing physical check'])
  assert mismatch==summary['relative_to_own_clean']
  if mismatch:rogue.append([label,mismatch,'different status/value/complete ELF'])
  res[label]={'physical_native':native,'differences_against_independent_clean':mismatch,'actual_mutations':mut}
 return {'cargo':info['cargo'],'cargo_source':info['cargo_commit'],'cargo_elf':info['cargo_sha'],'sources':info['all_role_sources'],'checks':res,
         'total_Cargo':sum(len(v['physical_native']) for v in res.values()),'all_real_elfs':elfs,'adverse_results':rogue,'source_terminal':H(z.read('native-group.json'))}
if __name__=='__main__':
 path,out=map(Path,sys.argv[1:]);z=Directory(path) if path.is_dir() else zipfile.ZipFile(path)
 result=verify(z);wire=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode();out.open('xb').write(wire)
 print(result['cargo'],result['total_Cargo'],'commands',len(result['adverse_results']),'adverse controls',H(wire))
