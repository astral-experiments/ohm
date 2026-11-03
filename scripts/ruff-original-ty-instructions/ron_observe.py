"""Re-run the exact observed installed Ron compiler under the signed bridge's six passive probes."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import shutil
import signal
import subprocess as sp
import time


def run(capture, root, sdk, observers, proof, products):
    pid,argv,env,cwd=capture
    fp,dep,meta,lib=products
    normal=Path(argv[argv.index('--out-dir')+1])
    assert normal==lib.parent and Path(argv[0]).samefile(sdk/'bin/rustc')
    assert argv[argv.index('--crate-name')+1]=='ron' and not any(a.startswith('incremental=')for a in argv)
    d=root/'ron-replay';d.mkdir(); o=d/'private-out';o.mkdir();out=d/'debug-origins';out.mkdir();deep=d/'deep-joins';deep.mkdir()
    prev=list(argv);argv=list(argv);argv[argv.index('--out-dir')+1]=str(o)
    def hf(p):
        with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
    def store(p,data):p.write_text(json.dumps(data,indent=1,sort_keys=True)+'\n')
    driver,=(sdk/'lib').glob('librustc_driver*.so')
    checksum='53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52'
    assert hf(driver)==checksum
    store(d/'plan.json',{'argv':argv,'driver':{'path':str(driver),'sha':checksum}})
    prefix='<rustc_expand::proc_macro_server::Rustc as rustc_proc_macro::bridge::server::Server>::'
    table={}
    p=sp.Popen(['nm','-anS','-C',driver],stdout=sp.PIPE,text=True)
    for ln in p.stdout:
        if ' T '+prefix+'span_' in ln:table[ln.split(' ',3)[-1].strip()[len(prefix):]]=int(ln.split()[0],16)
    assert p.wait()==0 and len(table)==16
    store(deep/'fn-offsets.json',table)
    sp.run(['cc','-Wall','-Werror','-shared','-fPIC','-O2',observers/'unwind.c','-o',deep/'unwind.so','-lunwind-ptrace','-lunwind-x86_64','-lunwind','-llzma'],check=True)
    wrapper=d/'exec.sh'
    wrapper.write_text('#!/bin/bash\nset -eu\n[[ "$1" -ef "$OHM_LICENSED_RUSTC" ]]\nshift\nexec -a "$OHM_LICENSED_RUSTC" "$OHM_LICENSED_RUSTC" "$@"\n')
    wrapper.chmod(0o700)
    env=dict(env,OHM_LICENSED_RUSTC=argv[0],OHM_F_SPAN_PY=str(observers/'observe.py'),OHM_F_SPAN_LOG=str(out/'hits.json'))
    script=d/'run.gdb'
    # The reused reader's optional salsa-specific DSO entry hooks are irrelevant to Ron.
    # Leave the original marker and bridge entry/return probes, hand-decoded SourceMap and native unwind intact.
    script.write_text('set confirm off\nset python print-stack full\nset pagination off\nset disable-randomization off\nset startup-with-shell on\nset exec-wrapper '+str(wrapper)+'\nset debuginfod enabled off\nset auto-load off\nset auto-solib-add off\nset print thread-events off\nstart\npython\nimport os,gdb\nexec(compile(open(os.environ["OHM_F_SPAN_PY"]).read(),os.environ["OHM_F_SPAN_PY"],"exec"))\nmaybe_macros=lambda:None\nend\ncontinue\npython\nfinish()\nend\n')
    ent=proof/'signed-ron-replay';ent.mkdir()
    notes={'original_pid':pid,'original_argv':prev,'replay_argv':argv,'cwd':str(cwd),'env_names':sorted(env),'driver':checksum,'bridge_offsets':table,'observer_sha256':hf(observers/'observe.py')}
    store(ent/'inputs.json',notes)
    with (ent/'stdout').open('wb')as so,(ent/'stderr').open('wb')as se:
        child=sp.Popen(['gdb','-q','-nx','-nh','-batch','-x',script,'--args',*argv],env=env,cwd=cwd,stdout=so,stderr=se,start_new_session=True)
        try:
            start=time.monotonic()
            while child.poll()is None:
                mem=int(next(x.split()[1]for x in Path('/proc/meminfo').read_text().splitlines()if x.startswith('MemAvailable:')))*1024
                assert mem>8*2**30 and time.monotonic()-start<660
                time.sleep(.2)
        finally:
            if child.poll()is None:os.killpg(child.pid,signal.SIGTERM);child.wait()
    assert child.returncode==0 and (out/'hits.json').is_file(),(ent/'stderr').read_text()[-1200:]
    hits=json.loads((out/'hits.json').read_bytes())
    assert hits['exit_codes']==[0]
    rdep=(o/dep.name).read_bytes()
    product={'rlib_original':hf(lib),'rlib_replayed':hf(o/lib.name),'rmeta_original':hf(meta),'rmeta_replayed':hf(o/meta.name),'d_original':hf(dep),'depinfo_identical_under_output_relocation':rdep.replace(bytes(o),bytes(normal))==dep.read_bytes(),'direct_observations':hits['events'],'join_calls':hits['entry_counts'].get('span_join',0),'joined_returns':len(hits['actual_returns']),'debug_calls':hits['entry_counts'].get('span_debug',0),'debug_independently_observes':sum(x['would_independently_observe']for x in hits['debugs'])}
    with (out/'hits.json').open('rb')as source,gzip.open(ent/'native-hits.json.gz','wb')as f:shutil.copyfileobj(source,f)
    for path in (dep,meta,lib):shutil.copyfile(o/path.name,ent/('replay-'+path.name))
    store(ent/'actual.json',product)
    assert product['depinfo_identical_under_output_relocation'] and product['rlib_original']==product['rlib_replayed']
