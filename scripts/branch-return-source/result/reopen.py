"""Independently open the two official ZIPs; stream native archives rather than installing the compiler."""
import argparse
import collections
import gzip
import hashlib
import io
import json
import os
from pathlib import Path,PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import zipfile
SRC=Path(__file__).resolve().parents[1]
HEAD='caef389ed580829583f1a63df129b7b649e43508'
RUN=41199659076
JOB=124532776606
CARGO='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'
WILD='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
V=Path(__file__).resolve().with_name('independent-fd.py')
import runpy
verify_fds=runpy.run_path(str(V))['verify']
WILD_MEMBER='lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
F='c6fe8ecda65452c105f85367a009af80cbb5efbc'
K='0afbeff303d3658bff52582d8f1a996d59e6c8ce'
PROVIDER={'cold':17,'repeat':17,'higher':29,'same-stat':47,'malformed':None,'repeat-malformed':None,'repair':29,'removed':17}
def requirement(ok,msg):
 if not ok:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def filehash(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def digeststream(f):return hashlib.file_digest(f,'sha256').hexdigest()
def admitzip(path,row):
 requirement(path.stat().st_size==row[1] and filehash(path)==row[2],f'official bytes {path}')
 z=zipfile.ZipFile(path)
 names=[i.filename for i in z.infolist()]; requirement(len(names)==len(set(names)) and all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names),'unsafe ZIP member')
 return z
def inventory(z,name,expected):
 reader=z.open(name); ph=hashlib.sha256(); compressed=0; failure=[]
 with subprocess.Popen(['zstd','--decompress','--stdout','--quiet'],stdin=subprocess.PIPE,stdout=subprocess.PIPE) as p:
  def feed():
   nonlocal compressed
   try:
    while b:=reader.read(1048576):compressed+=len(b);ph.update(b);p.stdin.write(b)
    p.stdin.close()
   except BaseException as err:failure.append(err)
   finally:reader.close()
  t=threading.Thread(target=feed);t.start();members={}
  with tarfile.open(fileobj=p.stdout,mode='r|') as tar:
   for m in tar:
    requirement(m.isreg() and m.name in expected and m.name not in members,'unregistered native member')
    with tar.extractfile(m) as f:h=digeststream(f)
    members[m.name]=[h,m.size,m.mode]
  requirement(not p.stdout.read().strip(b'\0'),'extra native payload');t.join()
  requirement(p.wait()==0 and not failure and members==expected,'native inventory or zstd corrupted')
 return [ph.hexdigest(),compressed]
def last_json(b):return [json.loads(x) for x in b.splitlines() if x.startswith(b'{')]
def main(folder,official):
 fingers=json.loads(official.read_bytes());requirement((fingers['qa'],fingers['run'],fingers['attempt'],fingers['job'])==(HEAD,RUN,1,JOB),'incorrect authentic run')
 arms={'F':F,'K':K};outer={}
 for key in ('sdk','observations'):
  name='branch-return-source-'+key;outer[key]=admitzip(folder/(name+'.zip'),fingers['artifacts'][name])
 sdk,ob=outer['sdk'],outer['observations']
 try:
  names=ob.namelist()
  def suffix(s):
   found=[p for p in names if p==s or p.endswith('/'+s)];requirement(len(found)==1,'missing or duplicate '+s);return found[0]
  def raw(s):return ob.read(suffix(s))
  def obj(s):return json.loads(raw(s))
  original_sha=lambda s:sha(raw(s))
  done=obj('receipts/qualified.json');manifest=sdk.read('manifest.json');m=json.loads(manifest)
  requirement(set(sdk.namelist())=={'F-sdk.tar.zst','K-delta.tar.zst','manifest.json'},'unregistered transfer')
  requirement((done['qa'],done['run'],done['attempt'],done['manifest'])==(HEAD,str(RUN),'1',sha(manifest)),'different qualification')
  requirement((m['qa'],m['run'],m['attempt'],m['qualified'])==(HEAD,str(RUN),'1',True),'improper source certification')
  src=obj('receipts/source-transplant.json');requirement(src==json.loads((SRC/'roles.json').read_bytes()),'source pack registration differs')
  requirement(m['roles']=={r:src['roles'][r] for r in arms} and (m['roles']['F']['commit'],m['roles']['K']['commit'])==(F,K),'source role mismatch')
  fs=m['files'];needkeys=set(fs['F']);requirement(set(fs['K'])==needkeys and len(needkeys)==81,'incomplete native SDK')
  changes=sorted(k for k in needkeys if fs['F'][k]!=fs['K'][k])
  requirement(changes==m['delta']==done['changed'] and m['driver'] in changes and set(changes)<={m['driver'],'bin/rustdoc'},'unexpected native drift')
  requirement(len(needkeys)-len(changes)==done['common'],'wrong common size')
  products={'F-sdk.tar.zst':inventory(sdk,'F-sdk.tar.zst',fs['F']),'K-delta.tar.zst':inventory(sdk,'K-delta.tar.zst',{k:fs['K'][k] for k in changes})}
  requirement(products==m['products']==done['products'],'compressed native member mismatch')
  source_display=obj('receipts/source-delta-presentation.json')
  frozen=json.loads((SRC/'delta.json').read_bytes())
  retained_patch=gzip.decompress((SRC/'original-full-index.patch.gz').read_bytes())
  requirement(sha(retained_patch)==source_display['historical_reference']==src['patch_sha256'],'original patch mismatch')
  for key,role in [('live','K'),('historical','old_packed')]:
   r=source_display['pairs'][key]
   requirement(obj('receipts/'+key+'-actual-delta.json')==frozen and r['raw_sha256']==frozen['raw_sha256'] and r['verified_tree']==src['roles'][role]['tree'] and r['rendered_sha256']==original_sha('receipts/'+key+'-actual-full-index.patch'),'checked-in source bytes or role mismatch')
  requirement(raw('receipts/live-actual-full-index.patch')==raw('receipts/historical-actual-full-index.patch'),'worker did not reproduce exact source change')
  builds=obj('receipts/strict-cargo-build.json');requirement(original_sha('receipts/strict-cargo-build.json')=='d54bc38a259b60b17168c745fa19389d81f9d861b7be42ef04e09b4de4e8ea4c' and builds['compiled']==builds['delivered']==CARGO and builds['candidate']==m['strict_cargo']=='761ea115605c34f11a1cd29afd68812c1e1359dd','donor Cargo mismatch')
  origins=m['source_builds'];f_origin=origins['F']
  requirement(origins==done['source_builds'] and (f_origin['run'],f_origin['attempt'],f_origin['job'],f_origin['qa'],f_origin['original_run_conclusion'],f_origin['source'])==(41198740643,1,124530126763,'172164400c7e99ed2bfcf074ae55c76cf92023db','failure',m['roles']['F']) and origins['K']=={'qa':HEAD,'run':str(RUN),'attempt':'1','built_here':True,'source':K},'source provenance mismatch')
  requirement(f_origin==obj('receipts/full-source-origin/origin.json')==obj('receipts/F/build-origin.json') and original_sha('receipts/full-source-origin/previous-observations.zip')=='897962e3c24957f9b80c5e96d1ac2b99e9c4f665569a7f1db0169dc563c7786d' and products['F-sdk.tar.zst']==['fbc494b4706cdbc171b61df3db3c18071322e0bb8aaad0f64643a254bdb7674e',234444818] and original_sha('receipts/F/inventory.json')=='c008008a6b483c3613c0f7f3089cb95383016fc5ca3943dedee0ec9e37aeacf6','inconsistent original Full attestation')
  nested=zipfile.ZipFile(io.BytesIO(raw('receipts/full-source-origin/previous-observations.zip')))
  for phase in ['bootstrap','reassemble','rustc-units',*obj('receipts/F/checked-in-tests.json')['run_make']]:
   for extension in ['.log','.command.json','.log.resource']:
    path='receipts/F/'+phase+extension;requirement(raw(path)==nested.read(path),'rewritten Full original '+path)
  nested.close()
  calib=obj('receipts/lineage-calibration.json')
  requirement(calib['negative']['refused']=='no authentic Cargo, Wild or read by that inherited image' and calib['negative']['physically_read'] and calib['positive']['linux_fd_evidence'],'unchecked exec barrier')
  for pid,record in calib['negative']['physically_read']:
   L=raw('receipts/lineage-calibration/negative/pid.'+str(pid)).decode().splitlines();ix=L.index(record)
   requirement(any(x.startswith('execve("/usr/bin/cat",') and re.search(r'= 0$',x) for x in L[:ix]),'no actual foreign exec before opening the original archive')
  receipt={'source_builds':origins,'sdk_files':len(needkeys),'identical':done['common'],'changed':changes,'fixture_hashes':{},'roles':{},'products':products,'manifest_sha256':sha(manifest),'official':fingers}
  for role,head in arms.items():
   p='receipts/'+role+'/'
   requirement(fs[role]==obj(p+'before-tests.json')==obj(p+'inventory.json') and fs[role]['bin/cargo'][0]==CARGO and fs[role][WILD_MEMBER][0]==WILD,'native SDK does not match phase receipts')
   rr=obj(p+'restored.json');requirement(rr['role']==role and rr['commit']==head and rr['driver']==fs[role][m['driver']] and rr['rustdoc']==fs[role]['bin/rustdoc'],'restored product mismatch')
   tests=obj(p+'checked-in-tests.json');requirement(len(tests['unit'])=={'F':8,'K':10}[role] and len(tests['run_make'])==7 and original_sha(p+'checked-in-tests.json')==m['tests'][role],'wrong original test inventory')
   platforms=obj(p+'unit-platforms.json');requirement(platforms['linux_fs_util']==0 and platforms['linux_incremental_names']==tests['unit'] and len(platforms['mac_only_source_names'])==3 and platforms['historical_full_only']['source']==F and platforms['historical_full_only']['job']==124343467588,'incorrect qualified platform scope')
   unit=raw(p+'rustc-units.log').decode(errors='strict').splitlines();rrx=[]
   for n in tests['unit']:
    requirement(unit.count('test '+n+' ... ok')==1,'unit not physically executed '+n)
   for n in tests['run_make']:
    body=raw(p+n+'.log').decode(errors='strict').splitlines();requirement(body.count('test [run-make] tests/run-make/'+n+' ... ok')==1 and body.count('running 1 tests')==1 and any('test result: ok. 1 passed; 0 failed; 0 ignored;' in l for l in body),'run-make selection mismatch')
    rrx.append([n,original_sha(p+n+'.log')])
   requirement(raw(p+'build-exec.log')==b'native\n' and b'native_case: test\n' in raw(p+'test-exec.log'),'Rustup normal entrypoint failed')
   for step in ('build','test'):
    requirewild=obj(p+step+'-linkers.json');requirement(requirewild and all(row['sha256']==WILD for row in requirewild),'native Wild not present')
   require_doc=raw(p+'rustdoc-invalid.log');requirement(obj(p+'rustdoc-invalid.command.json')['returncode']==1 and require_doc.count(b'error[E0425]: cannot find type `UnavailableBranchQaType` in this scope')==1 and b'aborting due to 1 previous error' in require_doc and b'internal compiler error' not in require_doc,'missing exact rustdoc diagnostic')
   sb=p+'native-shadow/';sg=obj(sb+'complete.json');requirement(sg['visits']==16 and sg['physical_cargo']==CARGO and sg['physical_wild']==WILD,'missing strict native history')
   native={};programs={}
   for label,want in PROVIDER.items():
    both=[]
    for kind in ('warm','empty'):
     ds=sb+label+'-'+kind+'/';terminal=obj(ds+'terminal.json')
     requiremsg=last_json(gzip.decompress(raw(ds+'stdout.gz')));requirement(requiremsg[-1]=={'reason':'build-finished','success':want is not None},'malformed native Cargo verdict')
     requirement((terminal['value'],terminal['exit'])==(want,101 if want is None else 0),'wrong native result')
     trace=gzip.decompress(raw(ds+'trace.gz'));heads=re.split(rb'(?m)^== (\d+) ==\n',trace)
     by={int(heads[i]):heads[i+1].splitlines() for i in range(1,len(heads),2)}
     r=terminal['native'];selected=r['resolved'].encode()
     requirement(verify_fds(by,r,selected)>0,'not opened by actual native image')
     requirement(all(pid in by and any(b'openat(' in x and b'O_RDONLY' in x and b'<'+selected+b'>' in x for x in by[pid]) for pid in r['archive_read_by']),'real linked FD absent')
     requirement(r['wild'] and all(any(b'execve(' in x and b'/wild-ld/ld.bfd' in x and x.endswith(b' = 0') for x in by[pid]) for pid in r['wild']),'missing real stock Wild')
     d=[n for n in names if n.startswith(suffix(ds+'terminal.json').rsplit('/',1)[0]+'/leaf-') and n.endswith('.d')];requirement(d and sorted(sha(ob.read(n)) for n in d)==terminal['marker_sha256'] and all(b'/dev/null/ohm-recheck-dependent-links' in ob.read(n) for n in d),'missing physical writer marker')
     if want is not None:
      h=terminal['elf']
      if h not in programs:
       program=gzip.decompress(raw(sb+'elf/'+h+'.gz'));requirement(sha(program)==h,'archived executable changed')
       with tempfile.TemporaryDirectory() as td:
        exe=Path(td)/'program';exe.write_bytes(program);exe.chmod(0o700)
        result=subprocess.run([exe],env={'PATH':'/usr/bin:/bin','LANG':'C'},capture_output=True)
        requirement(result.returncode==0 and result.stdout==f'{want}\n'.encode() and result.stderr==b'','original native program re-execution disagrees')
       programs[h]=want
      requirement(programs[h]==want,'one native ELF produced different result')
     else:
      requirement(terminal['elf'] is None and any(v.get('reason')=='compiler-message' and 'linking with' in v['message']['message'] for v in requiremsg),'wrong native failure')
     both.append(terminal['elf'])
    requirement(both[0]==both[1],'warm disagrees with its own empty')
    native[label]={'value':want,'elf':both[0]}
   original=obj(p+'provider-'+role+'/result.json');requirement(len(original)==6 and original['cold-A']['output']=='17 1' and original['first-B']['output']=='29 2' and original['returned-A']['output']=='29 1' and original['invalid']['exit']==101 and original['repair']['binary']==original['empty-repair']['binary']==original['returned-A']['binary'],'original declared provider controls failed')
   receipt['roles'][role]={'source':head,'driver':fs[role][m['driver']],'doc':fs[role]['bin/rustdoc'],'unit_tests':tests['unit'],'run_make':rrx,'native':native,'original_native':original,'reexecuted':programs}
 finally:
  for z in outer.values():z.close()
 return receipt
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('out',type=Path);a=p.parse_args();ans=main(a.folder,Path(__file__).resolve().with_name('official.json'));data=json.dumps(ans,sort_keys=True,indent=2)+'\n';a.out.write_text(data);print(json.dumps({k:ans[k] for k in ('manifest_sha256','sdk_files','identical','changed')},sort_keys=True),sha(data.encode()))
