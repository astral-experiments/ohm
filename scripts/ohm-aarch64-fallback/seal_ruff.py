"""Read the independent real fixed-Cargo Ruff controls and freeze their exact literal inference boundary."""
from hashlib import sha256
from pathlib import Path
import io,json,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import verify_ruff_native
REPO='astral-experiments/ohm'
RUN=41078144732
QA='86c6d127b33dd3ef1a3b8e18b23e5a1a59f47779'
H=lambda b:sha256(b).hexdigest()
def seal(gh,out):
 get=lambda path:subprocess.check_output([gh,'api',f'repos/{REPO}/'+path])
 wf=json.loads(get(f'actions/runs/{RUN}'))
 assert wf['head_sha']==QA and wf['status']=='completed' and wf['conclusion']=='success'
 arts={r['name']:r for r in json.loads(get(f'actions/runs/{RUN}/artifacts'))['artifacts']}
 old='gnu-ruff-735e1528-native-only';new='gnu-ruff-735e1528-independent-eligibility';assert set(arts)=={old,new}
 def data(a):
  assert not a['expired'] and 0<a['size_in_bytes']<768*2**20 and a['workflow_run']['head_sha']==QA
  wire=get(f"actions/artifacts/{a['id']}/zip");assert len(wire)==a['size_in_bytes'] and 'sha256:'+H(wire)==a['digest']
  return wire
 foreign=data(arts[new]);z=zipfile.ZipFile(io.BytesIO(foreign));assert z.namelist()==['independent-native.json']
 raw_meta=z.read('independent-native.json');from_runner=json.loads(raw_meta)
 wire=data(arts[old]);stream=io.BytesIO(wire);independent=verify_ruff_native.verify(stream)
 assert from_runner==independent;stream.seek(0);z=zipfile.ZipFile(stream)
 enrollment=z.read('ruff-native-eligibility.json');assert H(enrollment)==independent['terminal']
 stages=json.loads(enrollment);assert stages['cargo']==independent['cargo']
 normalized=stages['raw_normalized_argv'];norm=H(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode())
 previous=z.read('provider-admission/matched-provider-readback.json');assert H(previous)=='23caaefad9facf7e5c400c15f77e6c18122dd81d0efae082d8989761dded7f94'
 report={'run':RUN,'QA':QA,'cargo_elf':stages['cargo'],'sources':stages['sources'],'drivers':stages['drivers'],'native_readback':H(raw_meta),'provider_readback':H(previous),'native_terminal':H(enrollment),
  'normalized_argv_sha256':norm,'actual_argc':len(normalized),'namespace_positions':stages['namespace_positions'],'reference':independent['reference'],
  'immutable_artifacts':{n:[a['id'],a['size_in_bytes'],a['digest'][7:]] for n,a in arts.items()}}
 final=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
 out.mkdir(parents=True,exist_ok=True)
 for name,b in [('source-registration.json',final),('native-reopened.json',raw_meta)]:
  p=out/name
  if p.exists():assert p.read_bytes()==b
  else:p.open('xb').write(b)
 print(H(final),len(wire),len(foreign),norm,independent['reference'],flush=True)
 return report
if __name__=='__main__':seal(sys.argv[1],Path(sys.argv[2]))
