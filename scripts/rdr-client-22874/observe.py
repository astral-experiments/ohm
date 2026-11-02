#!/usr/bin/python3 -ISB
"""Run each real rustc once, recording its argv and selecting nine workspace check libraries."""
from pathlib import Path
import json, os, re, sys
HERE=Path(__file__).resolve().parent
NAMES=frozenset(('uv_cache','uv_client','uv_configuration','uv_distribution_types','uv_extract','uv_install_wheel','uv_metadata','uv_pypi_types','uv_torch'))
FLAG='OHM_RDR_OBSERVER_DIR'
def form(argv):
    if argv.count('--crate-name')!=1:return None
    name=argv[argv.index('--crate-name')+1]
    if name not in NAMES:return (name,False)
    root='crates/'+name.replace('_','-')+'/src/lib.rs'
    selected=argv.count(root)==1 and argv.count('--crate-type')==1 and argv[argv.index('--crate-type')+1]=='lib' and '--emit=dep-info,metadata' in argv
    if not selected:raise ValueError(('unexpected selected workspace unit',name,argv))
    return (name,True)
def main():
    env=os.environ.copy();loc=env.pop('OHM_22874_CLIENT_TRACE')
    wrapper=env.pop('RUSTC_WRAPPER',None)
    if wrapper is not None and Path(wrapper).resolve()!=Path(__file__).resolve():raise ValueError('foreign compiler wrapper')
    argv=sys.argv[1:];pid=os.getpid();root=Path(loc)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink() or FLAG in env or not argv or argv[0]!='/tmp/uv-workflow-search/sdk/bin/rustc':raise ValueError('unexpected observer envelope')
    x=form(argv)
    if x:
        n,selected=x
        if selected:
            out=root/n;out.mkdir();env[FLAG]=str(out)
        record={'pid':pid,'ppid':os.getppid(),'cwd':os.getcwd(),'argv':argv,'crate':n,'marked':selected,'jobserver':{k:env[k]for k in ('CARGO_MAKEFLAGS','MAKEFLAGS','MFLAGS')if k in env}}
        with(root/(str(pid)+'.json')).open('x')as f:json.dump(record,f,sort_keys=True);f.write('\n')
    os.execve(argv[0],argv,env)
if __name__=='__main__':main()
