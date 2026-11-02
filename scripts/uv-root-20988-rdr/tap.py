#!/usr/bin/python3.12 -ISB
"""Exec the unchanged compiler once, marking just the enrolled uv and resolver library processes."""
import json, os, sys
from pathlib import Path

argv=sys.argv[1:];env=os.environ.copy()
out=Path(env.pop('OHM_RDR_CAPTURE_PHASE'));wrapper=env.pop('RUSTC_WRAPPER')
assert out.is_absolute() and Path(wrapper).resolve()==Path(__file__).resolve()
assert argv[0]=='/tmp/uv-workflow-search/sdk/bin/rustc' and 'OHM_RDR_OBSERVER_DIR'not in env
if '--crate-name' in argv and '--out-dir' in argv:
    name=argv[argv.index('--crate-name')+1];pid=os.getpid();marked=False
    if name in ('uv','uv_resolver') and '--crate-type'in argv and argv[argv.index('--crate-type')+1]=='lib':
        assert argv==json.loads((out/'selected-argv.json').read_bytes())[name]
        env['OHM_RDR_OBSERVER_DIR']=str(out/'traces'/name);marked=True
    with (out/'processes'/f'{pid}.json').open('x') as f:
        json.dump({'pid':pid,'parent':os.getppid(),'argv':argv,'name':name,'marked':marked},f,separators=(',',':'))
os.execve(argv[0],argv,env)
