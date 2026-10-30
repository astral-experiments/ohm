"""Independently recompute a native whole-Cargo pilot or held-out instruction block."""
import argparse
import shutil
import collections
import functools
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

p=argparse.ArgumentParser();p.add_argument('artifact',type=int);p.add_argument('sha');p.add_argument('out',type=Path);p.add_argument('--qa',required=True);p.add_argument('--candidate',required=True)
args=p.parse_args()
here=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(here/'scripts/ohm-aarch64-linux'))
import qualify as q
H=lambda b:hashlib.sha256(b).hexdigest()
gold=json.loads((here/'scripts/ohm-cgu-reuse/counter-golden.json').read_text())
fd=os.memfd_create('whole-cargo-profiles')
with os.fdopen(os.dup(fd),'wb') as stream:subprocess.run([(shutil.which('gh-auto') or shutil.which('gh') or 'gh'),'api',f'repos/astral-experiments/ohm/actions/artifacts/{args.artifact}/zip'],stdout=stream,check=True)
archive=Path('/proc/self/fd')/str(fd)
with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==args.sha
def native_inventory(a):
 assert len(a['objects'])==95
 return H(json.dumps([[n,size,k] for n,original,size,k in a['objects']]).encode())
def load_set(payload,expected_pid,command):
 pid=[];events=[];sums=[];cmd=[];edge=False;local=0
 for line in io.BytesIO(payload):
  if line.startswith(b'pid:'):pid.append(int(line.split()[1]))
  elif line.startswith(b'events:'):events.append(line.split()[1:])
  elif line.startswith(b'cmd:'):cmd.append(line[4:].decode().strip())
  elif line.startswith(b'totals:'):sums.append(int(line.split()[1]))
  elif line.startswith(b'calls='):assert not edge;edge=True
  elif line.strip() and line[:1] in b'0123456789*+-':
   if edge:edge=False
   else:local+=int(line.split()[-1])
 assert not edge and pid==[expected_pid] and events==[[b'Ir']] and sums==[local] and local>0 and cmd==[' '.join(command)]
 return local
with zipfile.ZipFile(archive) as z:
 names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
 read=lambda n:json.loads(z.read(n));plain=lambda n:gzip.decompress(z.read(n))
 @functools.lru_cache(maxsize=100)
 def library(h):
  b=z.read('objects/'+h+'.rlib');assert H(b)==h
  return q.archive(b)
 def native(prefix,mode):
  r=read(prefix+'/verified.json');obs=read(prefix+'/native.json');assert H(z.read(prefix+'/native.json'))==r['native']
  stdout=plain(prefix+'/cargo/stdout.gz')
  if mode=='invalid':
   rows=[json.loads(line) for line in stdout.splitlines()];assert rows[-1]=={'reason':'build-finished','success':False}
   assert r['error']=='E0425' and b'apple_zmij_missing_name' in stdout
   assert any((s['message'].get('code') or {}).get('code')=='E0425' for s in rows if s['reason']=='compiler-message')
   return
  fromzip=library(r['archive']['raw']);assert fromzip==r['archive'] and native_inventory(fromzip)==gold[mode]['object_set']
  exe=z.read('objects/'+r['reader']+'.elf');assert H(exe)==gold[mode]['reader']==r['reader'] and exe[18:20]==b'\xb7\x00'
  value='3.14 3.14 3.10' if mode=='old' else '3.15 3.15 3.11'
  assert value==r['value']
  argv=obs['rustcs'];ast,=[a for a in argv if a['crate']=='ruff_python_ast'];av=ast['argv']
  opts=[v for k,v in zip(av,av[1:]) if k=='-C']
  assert 'lto=off' in opts and sum(s.startswith('incremental=') for s in opts)==1
  assert r['marker']['hard'] and not r['marker']['recheck'] and H(z.read(prefix+'/zmij.d'))==r['marker']['sha256']
  assert q.typed(stdout,True)[1:3]==(r['typed'],r['dirty'])
  for c,expected in [('correct',0),('contrary',1)]:
   cmd=read(prefix+'/'+c+'/command.json');assert cmd['exit']==expected
   if expected:assert b'E0308' in plain(prefix+'/contrary/stderr.gz')
  return r
 def measured(directory,expected_native):
  receipt=read(directory+'/observed.json')
  pipes=read(directory+'/command/physical-jobserver.json')
  cmd=read(directory+'/command/command.json')
  stdout=plain(directory+'/command/stdout.gz');stderr=plain(directory+'/command/stderr.gz')
  assert cmd['exit']==0 and H(stdout)==cmd['stdout'] and H(stderr)==cmd['stderr']
  expected={a['crate']:a['argv'] for a in expected_native['rustcs']};expected['cargo']=expected_native['cargo'][0]['argv']
  assert set(expected)=={'cargo','ruff_python_ast','zmij','compact_str'} and not expected_native['link_tools'] and not expected_native['compiler_probes']
  assert pipes.keys()==set(expected)-{'cargo'}
  roster=receipt['processes'];assert roster.keys()==expected.keys()
  for name,ev in roster.items():
   pid=ev['pid'];av=ev['argv'];assert av==expected[name]
   logs=z.read(directory+f'/profiles/log.{pid}');data=plain(directory+f'/profiles/cg.{pid}.gz')
   assert H(logs)==ev['log'] and H(data)==ev['profile']
   raw_ir=load_set(data,pid,av)
   matches=re.findall(rb'^=='+str(pid).encode()+rb'== Collected\s+:\s+([\d,]+)\s*$',logs,re.M)
   assert len(matches)==1 and int(matches[0].replace(b',',b''))==ev['Ir']==raw_ir
   if name!='cargo':
    a=pipes[name];assert a['pid']==pid and re.fullmatch(r'pipe:\[\d+\]',a['pipe']) and 'callgrind-amd64-linux' in a['kernel_image']
    assert a['full_compiler_argv']==av and not a['developer_overrides'] and len(a['descriptor_numbers'])==2
  assert receipt['Ir']==sum(x['Ir'] for x in roster.values())
  return receipt['Ir'],{k:v['Ir'] for k,v in roster.items()},q.typed(stdout,True)[1:3]
 qa=z.read('qa-head').decode().strip();assert qa==args.qa
 signature=json.loads(Path(__file__).resolve().with_name('final-source-built-sdk-manifests.json').read_text())
 assert qa==signature['qa'] and args.candidate==signature['candidate']
 regenerated={arm: H(json.dumps(read(arm+'-sdk.json')['files'],sort_keys=True,separators=(',',':')).encode()) for arm in 'PC'}
 assert regenerated==signature['sdk_file_inventories'] and all(len(read(arm+'-sdk.json')['files'])==signature['file_count'] for arm in 'PC')
 transferred=read('received.json');assert transferred['manifest']==signature['transfer_manifest_sha256'] and transferred['source']==signature['distribution']['source']
 assert all(signature['distribution']['sdk_receipt'][k]==v for k,v in transferred['proof'].items())
 for n in ('counter-plan.md','SHA256SUMS'):
  assert z.read(n)==(here/'scripts/ohm-cgu-reuse'/n).read_bytes()
 assert read('P-sdk.json')['source']=='82911b516fb35608fd70ada4deb6f8429277f410' and read('C-sdk.json')['source']==args.candidate
 assert read('pair.json')['changed_paths']==[p for p in read('P-sdk.json')['files'] if read('P-sdk.json')['files'][p]!=read('C-sdk.json')['files'][p]]
 assert len(read('pair.json')['changed_paths'])==1 and read('pair.json')['changed_paths'][0].startswith('lib/librustc_driver')
 calibration=read('counter-calibrated.json')['subjects'];base=calibration['ordinary']
 assert calibration['parent-thread']['parent']-base['parent']>3_000_000 and calibration['child-only']['child']-base['child']>3_000_000
 blocks={}
 for fname in names:
  match=re.fullmatch(r'result-(-?\d+).json',fname)
  if not match:continue
  i=int(match.group(1));r=read(fname);assert r['block']==i and qa==r['qa'] and r['sources']==['82911b516fb35608fd70ada4deb6f8429277f410',args.candidate]
  arms={}
  for pos,role in enumerate(r['order']):
   root=f'pair-{i}-arm-{pos}-{role}'
   flanks={}
   for phase in ['old-empty','edit','unchanged-1','unchanged-2','invalid','repair','empty-edited']:
    flanks[phase]=native(root+'/'+phase, 'old' if phase=='old-empty' else 'invalid' if phase=='invalid' else 'new')
   cycle=root+'-edit-cycle';native(cycle+'/old-empty','old');native(cycle+'/post-settled','new')
   votes={}
   for endpoint,phase in [('first-real-edit','edit'),('immediate-repeat','unchanged-1'),('settled','unchanged-1')]:
    directory=root+'/counter/whole' if endpoint=='settled' else cycle+'/'+endpoint
    c,crates,types=measured(directory,read(root+'/'+phase+'/native.json'))
    assert list(types)==[flanks[phase]['typed'],flanks[phase]['dirty']] and c==r['arms'][role]['Ir'][endpoint]
    proof=read(root+'/counter/verified.json' if endpoint=='settled' else directory+'/verified.json')
    assert c==proof['Ir']
    if endpoint!='settled':
     assert library(proof['archive']['raw'])==proof['archive'] and native_inventory(proof['archive'])==gold['new']['object_set']
    votes[endpoint]={'Ir':c,'processes':crates}
   assert r['arms'][role]['Ir']['edit-plus-repeat']==votes['first-real-edit']['Ir']+votes['immediate-repeat']['Ir']
   assert read(cycle+'/allocated.json')==r['arms'][role]['alloc'] and r['arms'][role]['alloc']['allocated_bytes']>0
   arms[role]={'observed':votes,'allocated_bytes':r['arms'][role]['alloc']['allocated_bytes']}
  for k,ratio in r['ratios'].items():assert ratio==r['arms']['P']['Ir'][k]/r['arms']['C']['Ir'][k]
  blocks[i]={'order':r['order'],'matched':arms,'ratios':r['ratios']}
 assert len(blocks) in (1,2)
 receipt={'qa':qa,'source':args.candidate,'artifact':args.artifact,'sha':args.sha,'archive_bytes':archive.stat().st_size,'blocks':blocks,'sdk_file_inventories':regenerated,'transferred':transferred['manifest']}
 with args.out.open('x') as f:json.dump(receipt,f,indent=2);f.write('\n')
 print({i:k['ratios'] for i,k in blocks.items()})
