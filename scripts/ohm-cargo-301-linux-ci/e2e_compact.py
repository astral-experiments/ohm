"""Reopen the exact completed feature-matched receipts, without starting Cargo or rustc."""
import collections, gzip, hashlib, io, json, os, re, subprocess, sys, time, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve()/'scripts/packaged-release-workspace'))
from linux_common import event
R=41120192553
HEAD='a5c14d2bb3c2f3c47472872df6263fb0b77727a1'
A={'shipped':(13007937879,6140672,'22754e6f367e9548a9c756b9736d594e655efaa67004906a520cb1ec47ffb901'),
   'strict-293':(13006989669,6182610,'d2984a32da7d50d8a582cc658b493b3984d4b4f0824653f226f550eaad872005')}
PH=('cold','unchanged','explain-unchanged','edited','restored','final-unchanged','clean-edited')
def h(b):return hashlib.sha256(b).hexdigest()
def api(path):
 for delay in (2,5,12,25,45,70,100,0):
  p=subprocess.run(['gh','api','repos/astral-experiments/ohm/actions/'+path],capture_output=True)
  if p.returncode==0:return p.stdout
  if not any(s in p.stderr for s in (b'502',b'503',b'504',b'timeout')):raise RuntimeError(p.stderr.decode(errors='replace'))
  print('Transient archive transport failure',path.split('/')[0],delay,flush=True);time.sleep(delay)
 raise RuntimeError('storage egress remained unavailable')
def score(role,decl):
 i,n,digest=A[role];assert (decl['id'],decl['size_in_bytes'],decl['digest'],decl['workflow_run']['head_sha'])==(i,n,'sha256:'+digest,HEAD)
 wire=api('artifacts/'+str(i)+'/zip');assert len(wire)==n and h(wire)==digest
 with zipfile.ZipFile(io.BytesIO(wire)) as z:
  assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None
  j=lambda p:json.loads(z.read(p));g=lambda p:json.loads(gzip.decompress(z.read(p)))
  s=j('subjects.json');t=j('terminal.json');assert s['role']==t['role']==role and set(t['phase_files'])==set(PH)
  assert s['actual']['rustc']==s['signed_physical']['versions']['rustc'] and s['source']=='93526150df078af7dd8fc4226cdcc469539d2001'
  assert ('2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c' if role=='shipped' else '735e1528ed741015c57676dccf05dbdc0ff7bed1') in s['actual']['cargo']
  result={'zip_sha256':digest,'artifact_id':i,'bytes':n,'members':len(z.namelist()),'source':s['source'],'history':t['real_historical_edit'],'kit':{k:v['sha256'] for k,v in s['tools'].items()},'driver':s['signed_physical']['physical_driver']['sha256'],'cold_restored_equal':t['cold_restored_equal'],'edited_empty_equal':t['edited_empty_equal'],'phases':{},'providers':{},'terminal_sha256':h(z.read('terminal.json'))}
  def processes(rows,env):
   out=[];provenance=[]
   for pid,line in rows:
    exe,args=event(line.encode())
    admitted_alias=str(Path(env['RUSTUP_HOME'])/'toolchains/ohm/bin/rustc')
    if exe in (s['tools']['rustc']['physical'],admitted_alias) and '--crate-name' in args and '--out-dir' in args and not any(a.startswith('--print') for a in args):
     out.append([pid,'link-only' if any(a in ('-Zlink-only','link-only') for a in args) else 'full',args[args.index('--crate-name')+1]])
    elif exe==s['tools']['wild']['physical'] and '-o' in args:
     out.append([pid,'wild',Path(args[args.index('-o')+1]).name])
    if out and out[-1][0]==pid:provenance.append([pid,h(line.encode())])
   return out,provenance
  for ph in PH:
   pref=ph+'/';o=j(pref+'observed.json');assert h(z.read(pref+'observed.json'))==t['phase_files'][ph]
   executable=j(pref+'elf-sections.json')['file']['sha256'];assert executable==o['e2e_sha256']
   test=gzip.decompress(z.read(pref+'runtime.stdout.gz'));listing=gzip.decompress(z.read(pref+'list.gz'))
   assert o['case_exit']==o['cargo_exit']==0 and b'1 passed' in test and h(listing)==o['inventory_sha256']
   rows=[(pid,ln) for pid,ts,ln in g(pref+'kernel.json.gz')];p,ids=processes(rows,o['environment']);counts=collections.Counter(mode for _,mode,_ in p);assert dict(counts)==o['counts']
   roots=[r for r in p if r[2] in ('ron','insta','e2e') or 'e2e-' in r[2] and r[1]=='wild']
   selected={v[0]:v[4] for v in o['selected']};assert all(selected[pid]==key for pid,key in ids if pid in {r[0] for r in roots})
   rt={ 'counts':dict(counts),'typed':o['typed'],'dirty':len(o['dirty']),'e2e':executable,'tests':sum(x.endswith(b': test') for x in listing.splitlines()),'list_sha':h(listing),'roots':roots,'kernel_bytes_sha256':h(z.read(pref+'kernel.json.gz'))}
   if ph not in ('cold','clean-edited'):rt['all_actual_jobs']=p
   result['phases'][ph]=rt
  assert len({v['list_sha'] for v in result['phases'].values()})==1
  native=j('provider-summary.json');source=j('native-provider-sources.json')
  assert source['control_exit']==[83,0] and source['earlier'].endswith('/out/libgcc_s.so') and h(gzip.decompress(z.read('native-provider-object.gz')))==source['object']['sha256']
  for name,fact in native.items():
   pref='provider-'+name+'/';body=j(pref+'result.json');assert body==fact
   ev,ids=processes(g(pref+'kernel.json.gz'),o['environment']);origin=j(pref+'origin.json');opens=[row for row in origin['all_candidate_lookups'] if source['earlier'] in row[1] and re.search(r' = [0-9]+$',row[1])]
   if body['cargo']==101:
    logs=b''.join(gzip.decompress(z.read(pref+'cargo-'+stream+'.gz')) for stream in ('out','err'));assert b'libgcc_s.so' in logs and b'UNRECOGNIZED_E2E_PRIVATE_LINK_SCRIPT' in logs
   if body['case']==0:assert b'1 passed' in gzip.decompress(z.read(pref+'test-out.gz'))
   result['providers'][name]={'cargo':body['cargo'],'exec':body['case'],'raw_elf':body['ep']['sha256'] if body['ep'] else None,'physical':ev,'actual_successful_private_opens':opens,'candidate_sha':body['candidate']['sha256'] if body['candidate'] else None}
  return result
def main():
 output=Path(sys.argv[2]);output.mkdir(parents=True,exist_ok=False)
 remote=json.loads(api('runs/'+str(R)));assert (remote['head_sha'],remote['status'],remote['conclusion'])==(HEAD,'completed','success')
 aa={a['name']:a for a in json.loads(api('runs/'+str(R)+'/artifacts'))['artifacts']}
 report={p:score(p,aa['focused-'+p+'-published-21-ty-server-e2e']) for p in A}
 assert all(report['shipped']['kit'][n]==report['strict-293']['kit'][n] for n in ('rustc','wild','system_ld'))
 assert report['shipped']['driver']==report['strict-293']['driver']
 subject={'native_run':R,'qa':HEAD,'roles':report};wire=(json.dumps(subject,sort_keys=True,separators=(',',':'))+'\n').encode(); assert len(wire)<128*1024
 (output/'native.json').write_bytes(wire);print('Verifier read both SHA256-complete originals',h(wire),len(wire))
 for key,v in report.items():print(key,{n:obs['counts'] for n,obs in v['phases'].items()},'programs',[(n,b['cargo'],b['exec']) for n,b in v['providers'].items()],flush=True)
if __name__=='__main__':main()
