from pathlib import Path
import gzip,hashlib,json,os,subprocess as sp,sys
sys.path.insert(0,str(Path('scripts/ruff-combined-apple').resolve()))
import macho
run=int(sys.argv[1]);p=Path(sys.argv[2]).resolve()
read=lambda f:json.loads(f.read_bytes())
sha=lambda b:hashlib.sha256(b).hexdigest()
sources={'cargo':'abc70d60a6fd89c10d5f65cf85820d9b78d5affe','rust':'c3aa3a605e56878669c745a9dd3ba09c9ccfa1ef'}
results={}
for target in ('x86_64-unknown-linux-gnu','aarch64-apple-darwin'):
 osx=target.startswith('aarch64');r=p/f'integrated-release-verdicts-{target}-{run}';c=p/f'integrated-release-cargo-{target}-{run}'/'candidate-cargo'
 accepted=read(r/'accepted-combined.json');candidate=read(r/'candidate.json'); src=read(r/'sources.json'); sm=read(r/'smoke.json')
 for rec in (accepted,candidate,src):assert all(rec[k]==v for k,v in sources.items())
 assert sha(c.read_bytes())==accepted['tools']['C']['bin/cargo'] and accepted['tools']['C']==candidate['tools']
 assert accepted['summaries']==sha((r/'smoke.json').read_bytes()) and accepted['prerequisite_commands']==14
 trace={}
 for f in sorted([*r.glob('[CP]-*.stdout'),*r.glob('prerequisite-*.jsonl')]):
  rows=[json.loads(line)for line in f.read_bytes().splitlines()]; assert rows[-1]['reason']=='build-finished'
  codes=[z['message']['code']['code'] for z in rows if z['reason']=='compiler-message' and z['message'].get('code')]
  ok=rows[-1]['success'];trace[f.name]={'ok':ok,'codes':codes}
  assert ok==('E0308'not in codes),(f,codes)
  if 'prerequisite' in f.name:expected=('clean-refusal' not in f.name and 'fixed-changed' not in f.name)
  else:
   name=f.stem
   expected=not ('independent-clean' in name or name.endswith('-upgrade') or (name.startswith('C-') and name.endswith('-unchanged') and 'repair' not in name))
  assert ok==expected,(f.name,ok,expected)
 manifest=read(r/'source-manifest-for-qa.json')
 expected_manifest=read(Path(__file__).with_name('source-manifest.json'))
 assert manifest==expected_manifest
 proof=(r/'release-source-verifier.stdout').read_text()
 assert 'validated pinned release manifest for ohm-1.99.0-24'in proof and all(manifest['sources'][key]['revision'] in proof for key in ('rust','cargo','clippy','rustfmt'))
 assert len(trace)==75 and len(sm['ordinary_cargo_histories'])==45 and sum(len(x['rows'])for x in sm['controls'])==16
 groups=sm['repairs']+[[z['elf']for z in x['rows']]for x in sm['controls']]; comp=[]
 for group in groups:
  if group[0] is None:assert set(group)=={None};continue
  ext='.macho.gz' if osx else '.elf.gz'; binaries=[gzip.decompress((r/(v+ext)).read_bytes()) for v in group];assert [sha(b)for b in binaries]==group
  if osx: assert group[-1]==group[0];comp.append(macho.compare(binaries[0],binaries[-2]))
  else: assert len(set(binaries))==1;comp.append({'identical':group[0]})
 assert len(comp)==8 and comp==read(r/'native-comparisons.json')
 if not osx:
  for control in sm['controls']:
   z=control['rows'][0];exe=p/('replayed-'+z['elf']);exe.write_bytes(gzip.decompress((r/(z['elf']+'.elf.gz')).read_bytes()));exe.chmod(0o755)
   assert sp.check_output([str(exe)]+(['--list']if control['mode']=='test' else []),cwd=p).decode()==z['output']
 extra={}
 for directory in sorted(f for f in r.iterdir()if (f/'commands.json').is_file()):
  folder=directory.name;rows=read(directory/'commands.json');extra[folder]={}
  for z in rows:
   cmd=z['name'];pref='overlapping'if cmd=='original-during-rebuild' else cmd;o=(directory/(pref+'.stdout')).read_bytes();e=(directory/(pref+'.stderr')).read_bytes()
   assert (sha(o),sha(e))==(z['out'],z['err'])and z['argv'][:2]==['cargo','+ohm']
   extra[folder][cmd]=z['status']; body=o+e
   if ('docs-'in folder or folder=='cargo-only-upgrade')and z['status']==101:assert b'E0658'in body
   if cmd=='original-during-rebuild':assert (directory/'example-that-ran').read_bytes()==(b'old'if 'integrated'in folder else b'new')
  if folder.startswith('worktree-'):
   ids=read(directory/'git-heads.json');assert ids['other']!=ids['donor']and ids['child']==ids['donor'if folder.endswith('integrated')else'other']
 assert sum(len(v)for v in extra.values())==37
 for role in ('signed','integrated'):
  old=role=='signed';statuses=extra['docs-'+role];assert [v for k,v in statuses.items()if k.startswith(('bench','macro'))]==([0,0,101,0,0,101] if old else [101]*6)
  assert extra['overlap-'+role]=={'second-build-list':0,'original-during-rebuild':0 if old else 101,'new-examples':0}
 assert list(extra['native-integrated'].values())==[0,101,0] and list(extra['cargo-only-upgrade'].values())==[0,0,101,0,0,101,101,101,0,0]
 for key,(dev,inode,digest)in read(r/'cargo-only-upgrade/untouched-rust.json').items():assert dev>0 and inode>0 and accepted['tools']['P'][key]==digest
 results[target]={**sources,'release_cargo':sha(c.read_bytes()),'normal_commands':len(trace)+sum(map(len,extra.values())),'old_and_fixed_ordinary_commands':trace,'extra':extra,'native_comparisons':comp}
(p/'reopened.json').write_text(json.dumps(results,indent=2)+'\n')
print([(k,v['normal_commands'],len(v['native_comparisons']),v['release_cargo'])for k,v in results.items()])
