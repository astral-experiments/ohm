"""Bind each installation to the original source-authenticated native receipts before reading a counter."""
from hashlib import sha256
from pathlib import Path
import io,json,os,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent
REPO='astral-experiments/ohm'
H=lambda b:sha256(b).hexdigest()
def get(path):return subprocess.check_output(['gh','api',f'repos/{REPO}/'+path])
def install(protocol,compact_name,member):
 n=protocol['run'];wf=json.loads(get(f'actions/runs/{n}'))
 assert (wf['status'],wf['conclusion'],wf['head_sha'])==('completed','success',protocol['QA'])
 metadata={r['name']:r for r in json.loads(get(f'actions/runs/{n}/artifacts?per_page=100'))['artifacts']}
 required=protocol['immutable_artifacts'];assert set(metadata)==set(required)
 for key,(id,sz,h) in required.items():
  row=metadata[key];assert (row['id'],row['size_in_bytes'],row['digest'])==(id,sz,'sha256:'+h) and not row['expired'] and row['workflow_run']['head_sha']==wf['head_sha']
 id,size,h=required[compact_name];assert size<8*2**20
 z=get(f'actions/artifacts/{id}/zip');assert len(z)==size and H(z)==h
 archive=zipfile.ZipFile(io.BytesIO(z));assert member in archive.namelist()
 return archive.read(member)
def main():
 stage=sys.argv[1];out=Path(os.environ['QA_ROOT'])/'receipts';assert stage in ('pilot','confirmation')
 cp=json.loads((HERE/'admissible-native.json').read_bytes())
 raw=install(cp,'gnu-ruff-735e1528-independent-eligibility','independent-native.json')
 j=json.loads(raw);assert H(raw)==cp['native_readback'] and j['reference']==cp['reference'] and j['cargo']==cp['cargo_elf'] and j['sources']==cp['sources'] and j['drivers']==cp['drivers']
 assert cp['actual_argc']==j['argv_count'] and cp['namespace_positions']==j['namespace_positions']
 assert cp['provider_readback']=='23caaefad9facf7e5c400c15f77e6c18122dd81d0efae082d8989761dded7f94' and cp['native_terminal']==j['terminal']
 info={'sources':j['sources'],'admitted':cp,'cargo':cp['cargo_elf'],'native_gate':j,'normalized_argv_sha256':cp['normalized_argv_sha256'],'native_readback':cp['native_readback'],'provider_readback':cp['provider_readback']}
 (out/'independent-admissions.json').open('x').write(json.dumps(info,indent=2,sort_keys=True)+'\n')
 if stage=='confirmation':
  pilot=json.loads((HERE/'qualified-pilot.json').read_bytes());raw=install(pilot,'gnu-735e1528-pilot-readback','analysis.json')
  assert H(raw)==pilot['analysis'] and json.loads(raw)['all_twelve_pilot_ratios_strictly_above_two']
  (out/'independent-pilot.json').open('xb').write(raw)
if __name__=='__main__':main()
