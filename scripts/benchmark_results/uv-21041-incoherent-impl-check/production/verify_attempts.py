"""Reopen both complete unscored originals and identify their failure against the prospective plan."""
from pathlib import Path
import hashlib,json,sys,zipfile,runpy
def verify(p):
 runpy.run_path(str(p/'verify_first_attempt.py'))['verify'](p);sha=lambda b:hashlib.sha256(b).hexdigest();read=lambda f:json.loads((p/f).read_bytes())
 s=read('second-attempt-study.json');registered=read('original-measurement-plan.json');r=read('second-attempt.json');raw=p/'second-attempt.zip'
 assert 'prior_actual_argv_sha256'not in s and sha((p/'original-measurement-plan.json').read_bytes())==s['measurement_plan_sha256']=='1a4cd14fc2776f0e73625fe205f197e044b7b5f68dc6ff2cc64f9a763848dd8e'
 assert r['run']==41421756085 and r['job']==125198701783 and r['head']=='226ff01f857cd86ecc72000299d5bf3fac338ecd'and r['original']['artifact_id']==13130027952 and r['scored_pairs']==0
 with raw.open('rb')as f:h=hashlib.file_digest(f,'sha256').hexdigest()
 assert r['original']['sha256']==h=='4b1776b9243e54fb048a2953dfc13dc81bafdb399524c34e119b40b23bcfebab' and r['original']['size']==raw.stat().st_size==17906325
 with zipfile.ZipFile(raw)as z:
  ns=z.namelist();assert len(ns)==len(set(ns))==867 and not any(n.startswith('uv-client/pair-')for n in ns)
  j=lambda k:json.loads(z.read(k));prefix='uv-client/hold-0-callables_ctfe318/'
  log=z.read('experiment.log').decode();assert "KeyError: 'prior_actual_argv_sha256'"in log and 'screen.py", line 91, in run'in log and log==r['rejection']
  args=j(prefix+'typed-B/roster.json')['commands'];assert len(args)==8;ah=sha(json.dumps(sorted(args),separators=(',',':'),sort_keys=True).encode())
  assert ah==registered['case']['complete_native_argv_sha256']==r['raw_argv']=='2c6a09f122e5293f696ffb63d11e6469d88491bfd5a331897765c6a916e384fc'
  phases=('ordinary-A','settled-A','typed-fresh-A','unchanged-kernel-A','warm-B','settled-B','typed-fresh-B','unchanged-kernel-B','cold-B','typed-B');data={k:j(prefix+k+'/products.json')for k in phases};assert all(len(x['raw'])==37 and len(x['public_sidecars'])==415 for x in data.values())
  assert all(data[k]==data['ordinary-A']for k in phases[:4])and all(data[k]==data['warm-B']for k in phases[4:]if k!='cold-B')
  assert all(data['warm-B'][k]==data['cold-B'][k]for k in ('semantic','structural','public_sidecars','relative_paths'))
  assert j('fresh-boot.json')['boot']==r['boot']['boot']=='d4ad8776-10c1-4fc1-a536-531abb953a1d'and j(prefix+'unchanged-kernel-B/zero.json')['rustc_images']==0
 if (p/'study.json').is_file():assert read('study.json')['prior_actual_argv_sha256']==ah and set(read('study.json'))==set(s)|{'prior_actual_argv_sha256'}
 print('Second full original reopened: complete genuine control A/B/cold B, eight argv match the prior declaration, no scored pair.')
if __name__=='__main__':verify(Path(__file__).resolve().parent)
