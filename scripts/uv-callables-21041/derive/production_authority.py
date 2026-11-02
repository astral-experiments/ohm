"""Authenticate a producer in the original consumer's Python dependency closure."""
from hashlib import file_digest
from pathlib import Path
import json,subprocess,sys
def main(role,checkout,records,destination):
    here=Path(__file__).resolve().parent;material=json.loads((here/'cumulative-material.json').read_bytes())
    checkout=Path(checkout).resolve();records=Path(records);root=checkout/'scripts/uv-callables-21041';wanted=material['source_coordinator'][role]
    assert subprocess.check_output(['git','-C',checkout,'rev-parse','HEAD']).decode().strip()==wanted and not subprocess.check_output(['git','-C',checkout,'status','--porcelain','--untracked-files=no'])
    sys.path.insert(0,str(root));import production_service as source
    assert Path(source.__file__).resolve().parent==root
    native=json.loads((root/'pair.json').read_bytes())['arms'][role];request=[json.loads((records/(name+'.json')).read_bytes())for name in ('run','jobs','artifacts')]
    inputs=[json.loads((root/'verified-control-lock.json').read_bytes())] if role=='stock_ctfe318' else []
    current=source.service(role,*request,*inputs);assert current==material['services'][role]==native['service']
    spec=source.PRODUCERS[role];names={k:spec[k]for k in ('sdk','qa','prior_pair')if k in spec};assert set(names)==({'sdk','qa','prior_pair'}if role=='stock_ctfe318'else {'sdk','qa'})
    assert current['members'][names['sdk']]==native['artifact'];value={'service':current,'artifact_names':names,'authority_commit':wanted,'service_module_sha256':file_digest(Path(source.__file__).open('rb'),'sha256').hexdigest()}
    with Path(destination).open('x')as f:json.dump(value,f,sort_keys=True)
if __name__=='__main__':main(*sys.argv[1:])
