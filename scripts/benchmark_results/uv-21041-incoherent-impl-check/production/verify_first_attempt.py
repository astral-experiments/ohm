"""Verify the preserved unscored production attempt and the exact caller change independently."""
import hashlib,json,sys,zipfile
from pathlib import Path
def sha(path):
 h=hashlib.sha256()
 with path.open('rb')as f:
  for part in iter(lambda:f.read(1<<20),b''):h.update(part)
 return h.hexdigest()
def verify(folder):
 read=lambda n:json.loads((folder/n).read_bytes())
 origin=read('first-attempt.json');raw=folder/'first-attempt.zip';pre=(folder/'first-attempt-screen.py').read_bytes();fixed=(folder/'measured-screen.py').read_bytes()
 assert origin['run']==41420397868 and origin['job']==125194285297 and origin['head']=='070b201d526382408acb684f7f6f778f567becb0' and origin['registration']=='1e05085b9c64161f669fffd580787c63e15ad354e7c2b5d512fe0732fc785e93'
 a=origin['original'];assert a['artifact_id']==13130191096 and a['size']==raw.stat().st_size==13693654 and a['sha256']==sha(raw)=='17a0f34b437ec14f7dadc86e9c549b36c6f7b0f867a5d5a6e1cee3c895e73b3f'
 git_blob=lambda b:hashlib.sha1(b'blob '+str(len(b)).encode()+b'\x00'+b).hexdigest()
 assert git_blob(pre)=='7b515b7f800fb9705d1f724492b4441beda855de' and git_blob(fixed)=='8cd27719f65c22b921b62a0362fafd8c6176fc15'
 needle=b'    import domain_control\n    domain_control.post_clock(out,ready)';assert pre.count(needle)==1 and fixed==pre.replace(needle,b'    domain_control.post_clock(out,ready)')
 with zipfile.ZipFile(raw)as z:
  names=z.namelist();assert len(names)==len(set(names))==a['zip_members']==796;assert all(not n.startswith('/')and '..'not in Path(n).parts for n in names)
  j=lambda n:json.loads(z.read(n));log=z.read('experiment.log')
  assert hashlib.sha256(log).hexdigest()==origin['experiment_log_sha256'] and b'screen.py", line 71, in run' in log and b"UnboundLocalError: cannot access local variable 'domain_control'" in log
  assert not any(n.startswith('uv-client/pair-')or '/warm-B/'in n or n.endswith('/raw-pairs.json')for n in names)
  assert j('fresh-boot.json')==origin['boot']and j('fresh-boot.json')['boot']=='d5aa006d-e248-44bf-8635-a0f26186c053'
  q='uv-client/hold-0-callables_ctfe318/'
  bodies=[j(q+p+'/products.json')for p in ('ordinary-A','settled-A','typed-fresh-A')];assert bodies[0]==bodies[1]==bodies[2]and len(bodies[0]['raw'])==37 and len(bodies[0]['public_sidecars'])==415
  assert all(j(q+x+'-equivalence.json')['passed']for x in ('settled-A','fresh-A'))
  assert j('intake/domain-native/epoch/passed.json')['reader_compilations']==10 and j('per-rustc-calibration/calibration.json')['reexec_rejected'] is True
 case=read('first-attempt-caller-controls.json')['cases'];assert case['shadow']['source_line']==71 and not case['shadow']['peer_names_resolved_as_global']and case['fixed']['peer_names_resolved_as_global']and case['dirty']['outcome']=='dirty package correctly rejected'
 print('First original reopened: all three A products agree, no first edit or pair, original error and exact one-line correction verified.')
if __name__=='__main__':verify(Path(__file__).resolve().parent)
