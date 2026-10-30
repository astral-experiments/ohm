"""Verify the captured 40 Cargo visits without Cargo, the original host, or network access."""
import argparse,ast,collections,copy,gzip,hashlib,json,re
from pathlib import Path
P=Path(__file__).resolve().parent
WILD='$CASE/rustup/toolchains/ohm/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld'
LIB=WILD+'/libutil.so'
STATES=['warm-absent','settled-absent','insert-83','same-inode-47','same-inode-bad','removed','empty-absent','empty-83','empty-47','empty-bad']
CODES={'absent':0,'83':83,'47':47}
ELF={0:'6738748375aac6ff9887274df1ce3f82d0fde476c0cd3cabc47274d4e1b048ff',83:'e41186890839bd0f7de32d667abcd04107744ba6084b8a9e0f163f2c39bd4c45',47:'b50f9383403d3d4c23d327f197ef7b181409e69bf83f1b1e6257b18b39b63cc8'}
def opened(p):return json.loads(gzip.decompress((P/p).read_bytes()))
def sha(b):return hashlib.sha256(b).hexdigest()
def procs(text):
 result={}
 for l in text.splitlines():
  m=re.match(r'^(\d+) execve\(("(?:\\.|[^"\\])*"), (\[.*\]), .*\)\s+= 0$',l)
  if m:result[int(m[1])]=(ast.literal_eval(m[2]),ast.literal_eval(m[3]))
 return result
def check(rows,lookup):
 assert len(rows)==40
 identities=json.loads((P/'identities.json').read_text())
 results={}
 by={(r['role'],r['phase']):r for r in rows};assert len(by)==40
 for role in ['signed','classic','aware','fd55']:
  strict=role in ('classic','aware');report=[]
  prior=by[role,'insert-83']['provider']
  for name in STATES:
   r=by[role,name];state=r['state']; control=name.startswith('empty-'); new=control or name=='warm-absent'
   expected_status=101 if state=='bad' and (control or strict) else 0
   assert r['status']==expected_status and r['cargo_terminal']==[{'reason':'build-finished','success':expected_status==0}]
   assert r['floor']>11*(1<<28)
   p=procs(r['executed_and_libutil']);assert p
   assert any(exe.endswith('/bin/cargo') and 'build' in argv for exe,argv in p.values())
   native=[(pid,exe,a) for pid,(exe,a) in p.items() if exe.endswith('/bin/rustc') and '--crate-name' in a and a[a.index('--crate-name')+1]!='___']
   names=[a[a.index('--crate-name')+1] for _,_,a in native]
   gen=[pid for pid,(exe,a) in p.items() if exe.rsplit('/',1)[-1]=='build_script_build' and '/ruff_unicode_names2/' in exe]
   ld=[(pid,a) for pid,(exe,a) in p.items() if exe==WILD+'/ld.bfd']
   gcc=[(pid,a) for pid,(exe,a) in p.items() if exe=='/usr/bin/cc']
   col=[a for pid,(exe,a) in p.items() if exe.endswith('/collect2')]
   assert len(ld)==len(gcc)==len(col)==int(strict or new)
   if ld:
    assert ('-B'+WILD) in gcc[0][1] and ('-L'+WILD) in ld[0][1] and ('-L'+WILD) in col[0]
    assert '-lutil' in ld[0][1] and '-fuse-ld=bfd' in gcc[0][1]
   if new:
    assert len(names)==(16 if expected_status else 17) and 'chacha20' in names and 'build_script_build' in names
   elif strict:
    assert names==(['build_script_build'] if name in ('settled-absent','same-inode-bad') else ['build_script_build','unicode_names2'])
   else:assert not names and not gen
   ls=r['executed_and_libutil'].splitlines()
   hits=[int(l.split()[0]) for l in ls if 'openat('in l and ('"'+LIB+'"')in l and re.search(r'= [0-9]+$',l)]
   if state not in ('absent','bad') and ld:
    assert len(gen)==1 and len(hits)>=2 and gen[0] in hits and any(pid!=gen[0] for pid in hits)
   if expected_status:
    assert ld and hits and not gen and not r['reader_sha256'] and r['reader_stdout'] is None
    assert any('wild: error: Failed to process' in s and LIB in s for s in r['cargo_messages'])
    value=None
   else:
    value=CODES[state] if (strict or new) else 0
    assert r['reader_stdout']==f'Some({value})\nSome(0)\n' and r['reader_sha256']==ELF[value]
    assert set(r['generated'])=={'generated.rs','generated_alias.rs','generated_phf.rs'}
    assert re.fullmatch('[0-9a-f]{64}',r['rlib'])
   if state in ('47','bad') and not new:
    cur=r['provider'];assert all(cur[k]==prior[k] for k in ['dev','ino','size','mtime'])
    assert cur['ctime']!=prior['ctime'] and cur['sha256']!=prior['sha256']
   if state in ('83','47'):
    assert r['provider']['sha256']==identities['native_provider_files'][f'observe-{state}.so']
   report.append([name,expected_status,value,len(native),len(ld),len(gen)])
  results[role]=report
 for v in (0,83,47):
  gens=[r['generated'] for r in rows if r.get('reader_sha256')==ELF[v]]
  assert gens and all(g==gens[0] for g in gens)
 g=[by['signed','empty-'+v]['generated'] for v in ('absent','83','47')]
 for name in ['generated.rs','generated_phf.rs']:assert len({m[name] for m in g})==1
 assert len({m['generated_alias.rs'] for m in g})==3
 for state in ['absent','inserted']:
  n=lookup[state];assert n['wild']==identities['wild_sha256']
  assert len(n['positive'])==69 and len(n['negative'])==(70 if state=='absent' else 65)
  assert (LIB in n['positive'])==(state=='inserted') and (LIB in n['negative'])==(state=='absent')
  assert WILD+'/ld.bfd'==n['command'][0] and '-L'+WILD in n['command'] and '-lutil' in n['command']
  group={n['wild_pid']}; todo=list(group)
  while todo:
   for pid in n['children'].get(str(todo.pop()),[]):
    if pid not in group:group.add(pid);todo.append(pid)
  assert group==set(n['group']) and len(group)==6
  edges=[l for l in n['transcript'] if int(l.split()[0]) in group and ('"'+LIB+'"') in l]
  if state=='absent':assert any('statx(' in l and '= -1 ENOENT' in l for l in edges) and not any('openat(' in l for l in edges)
  else:assert any('openat(' in l and re.search(r'= [0-9]+<',l) for l in edges)
  assert [Path(s['path']).name for s in n['system_scripts']]==['libc.so','libm.so','libgcc_s.so']
  assert all(sha(s['body'].encode())==s['digest'] for s in n['system_scripts'])
 return {'cargo_commands':40,'separately_empty':16,'signed_and_fd55_contrary_to_empty':6,'complete_reader_elf_by_NULL':ELF,'phases_status_NULL_rustc_Wild_generator':results,'wild_positive_negative':{s:[len(n['positive']),len(n['negative'])] for s,n in lookup.items()}}
def main():
 c=argparse.ArgumentParser();c.add_argument('--full',action='store_true');a=c.parse_args()
 rows=opened('commands.json.gz'); lookup=opened('search.json.gz')
 result=check(rows,lookup)
 smoke=json.loads((P/'portable-smoke.json').read_text())['records']
 assert set(smoke)=={'signed','classic'}
 for role,seen in smoke.items():
  assert len(seen)==10
  for name,rc,out,compiles,links,digest in seen:
   expected=next(row for row in result['phases_status_NULL_rustc_Wild_generator'][role] if row[0]==name)
   assert expected[1]==rc and expected[4]==links
   observed_compiles=2 if role=='classic' and name=='settled-absent' else expected[3]
   assert observed_compiles==compiles
   if rc:assert out is None and digest is None;continue
   assert out==[f'Some({expected[2]})','Some(0)']
   label={0:'absent',83:'83',47:'47'}[expected[2]]
   assert next(z[5] for z in seen if z[0]=='empty-'+label)==digest
 result['separate_portable_smoke_commands']=20
 def rejects(rows,lookup):
  try:check(rows,lookup)
  except (AssertionError,KeyError,ValueError):return
  raise AssertionError('corrupted witness accepted')
 for (r,n),key,v in [(('signed','insert-83'),'reader_sha256',ELF[83]),(('classic','same-inode-bad'),'status',0),(('fd55','same-inode-47'),'reader_stdout','Some(47)\nSome(0)\n')]:
  x=copy.deepcopy(rows);next(q for q in x if (q['role'],q['phase'])==(r,n))[key]=v;rejects(x,lookup)
 x=copy.deepcopy(lookup);x['absent']['negative'].remove(LIB);rejects(rows,x)
 x=copy.deepcopy(rows);q=next(q for q in x if q['role']=='classic' and q['phase']=='same-inode-47');q['provider']['mtime']+=1;rejects(x,lookup)
 if a.full:print(json.dumps(result,indent=2,sort_keys=True))
 else:print('Verified 40 actual Cargo commands, 16 independent empty references, six wrong warm verdicts, three distinct byte-identical-across-role reader digests, both kernel resolution traces, and five rejected corruptions.')
if __name__=='__main__':main()
