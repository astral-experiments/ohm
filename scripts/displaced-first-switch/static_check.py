"""Validate the complete isolated-mode runtime import closure, historical corpus and carrier before enrollment."""
from pathlib import Path
import ast, hashlib, json, os, subprocess, sys
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here)); import acquire, tables, review
h=Path('/home/dev-user/code/oss/ohm-package-qa-packed-ordinary-efficacy-20261031')
def cmd(*args):return subprocess.check_output(args,text=True).strip()
assert cmd('git','-C',h,'rev-parse','HEAD')==acquire.HIST
os.environ.setdefault('RUNNER_TEMP','/tmp/unscheduled-displaced-static-check')
sys.path.insert(0,str(h/'scripts/branch-return-pmu'));import worker
assert len(list(tables.UNITS.elements()))==20 and len(tables.KINDS)==2
assert worker.b.spec()['head']==acquire.SOURCE and worker.b.spec()['manifest']==acquire.MANIFEST
assert worker.CARGO==['cargo','+ohm','build','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']
info=json.loads((h/'scripts/branch-return-pmu/historical-sources.json').read_bytes())
assert all(tables.sha(h/key)==digest for key,digest in info['files'].items())
for p in here.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
from yaml import BaseLoader,load
flow_path=here/'ci.yml' if (here/'ci.yml').is_file() else here.parents[1]/'.github/workflows/ci.yml'
flow=load(flow_path.read_text(),Loader=BaseLoader)
job=flow['jobs']['storage']
assert set(flow['on'])=={'workflow_dispatch'} and set(flow['jobs'])=={'storage'} and 'strategy' not in job
assert flow['permissions']=={'actions':'read','contents':'read'} and job['runs-on']=='namespace-profile-ubuntu-24-04-16'
assert job['timeout-minutes']=='165' and all(c in job['if'] for c in [acquire.REF,'inputs.reviewed_head == github.sha',"github.run_attempt == '1'"])
assert [(s['with']['path'],s['with']['ref']) for s in job['steps'] if s.get('uses','').startswith('actions/checkout@')]==[('enrolled','${{ github.sha }}'),('history',acquire.HIST),('source',acquire.SOURCE)]
assert len([s for s in job['steps'] if s.get('uses','').startswith('actions/upload-artifact@')])==2
prepare=next(s['run'] for s in job['steps'] if s.get('name','').startswith('Authenticate'))
subprocess.run(['/bin/bash','-n'],input=prepare.encode(),check=True)
assert all(s in prepare for s in ('runner-filesystem','private-ext4','MAJ:MIN','! mountpoint -q'))
assert 'Popen' not in (here/'acquire.py').read_text() and 'measured' not in [n.value for n in ast.walk(ast.parse((here/'acquire.py').read_text())) if isinstance(n,ast.Constant)]
print(json.dumps(dict(workflow_manual_only=True,workers=1,original_runtime_sha=acquire.HIST,source=acquire.SOURCE,ordinary_argv=worker.CARGO,original_inherited_files=len(info['files']),all_qualified_static=True),sort_keys=True))
