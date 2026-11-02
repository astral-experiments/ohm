"""Compare the two distribution candidates on the original 619-product workspace."""
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from install import HOST, RECORDS, ROOT, SDK, WILD, save, sha

BASE=Path(os.environ['GITHUB_WORKSPACE'])
SITE=BASE/'census-code'
sys.path.insert(0,str(SITE/'scripts/ruff-workspace-link-census'))
import census
import paired
from reopen import raw_args

CENSUS='a43236131847bb5906247e46656d702e543d3c50'

def main(role):
    assert role in ('23','253') and census.git(SITE,'rev-parse','HEAD')==CENSUS
    source=BASE/'ruff-whole'
    assert census.git(source,'rev-parse','HEAD')==census.RUFF and not census.git(source,'status','--porcelain')
    assert sha(source/'Cargo.lock')==census.LOCK
    assert not any(k in os.environ for k in ('GH_TOKEN','GITHUB_TOKEN','RUSTFLAGS','RUSTC_WRAPPER','LD_PRELOAD'))
    assert sha(SDK/'lib/rustlib'/HOST/'bin/wild-ld/ld.bfd')==WILD
    assert not (SDK/'lib/rustlib'/HOST/'bin/wild-ld/libutil.so').exists()
    work=ROOT/'whole-workspace';work.mkdir()
    evidence=RECORDS/'workspace';evidence.mkdir()
    env=json.loads((RECORDS/'environment.json').read_text())
    for key,part in [('HOME','home'),('CARGO_HOME','cargo'),('CARGO_TARGET_DIR','target'),('CARGO_BUILD_BUILD_DIR','build'),('TMPDIR','tmp')]:
        env[key]=str(work/part)
        (work/part).mkdir()
    env.update(LD_LIBRARY_PATH=str(SDK/'lib'),LC_ALL='C',TZ='UTC')
    assert shutil.disk_usage(work).free>40<<30
    tools=json.loads((RECORDS/'tools.json').read_text())['sha256']
    for tool in ('rustc','cargo'):
        got=subprocess.check_output([tool,'+ohm','-vV'],env=env,text=True)
        assert 'ohm-1.99.0-23' in got and sha(SDK/'bin'/tool)==tools['bin/'+tool]
    with (evidence/'fetch.log').open('xb') as log:
        subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=source,env=env,stdout=log,stderr=log,check=True,timeout=900)
    lock=tomllib.loads((source/'Cargo.lock').read_text())
    expected={q['name']+'-'+q['version']+'.crate':q['checksum'] for q in lock['package'] if 'source' in q}
    got={p.name:sha(p) for p in (work/'cargo/registry/cache').glob('*/*.crate')}
    assert len(expected)==498 and got==expected
    save('workspace/registry.json',got)
    results={}
    for phase in ('cold','ordinary','traced','fingerprint'):
        argv=census.COMMAND
        visit_env=env
        if phase=='traced':
            argv=['strace','-ff','-qq','-v','-e','trace=%process','-e','signal=none','-s','4096','-o',str(evidence/phase/'exec'),'--',*argv]
        if phase=='fingerprint':
            visit_env=dict(env,CARGO_LOG='cargo::compiler=info,cargo::compiler::fingerprint=trace')
        results[phase]=census.cargo_phase(phase,argv,source,visit_env,work,evidence)
        paired.observe(source,work,evidence/phase)
        assert results[phase]['count']==619 and len(results[phase]['native'])==102
        assert results[phase]['inventory']==results['cold']['inventory']
    assert results['ordinary']['dirty']==results['traced']['dirty']==results['fingerprint']['dirty']
    tree=census.genealogy(evidence/'traced')
    links=[]
    for linker in tree['linkers']:
        assert os.path.samefile(linker['path'],SDK/'lib/rustlib'/HOST/'bin/wild-ld/ld.bfd')
        parent=linker['owning_rustc']
        assert parent and os.path.samefile(parent['path'],SDK/'bin/rustc')
        lines=(evidence/'traced'/('exec.'+str(linker['pid']))).read_text(errors='replace').splitlines()
        actual=[pair for line in lines if (pair:=raw_args(line)) and os.path.exists(pair[0]) and os.path.samefile(pair[0],linker['path'])]
        (_,args),=actual
        dst=Path(args[args.index('-o')+1])
        assert dst.is_file() and dst.resolve().is_relative_to(work)
        links.append(dict(pid=linker['pid'],compiler=parent['pid'],owner=parent['owner'],link_only=parent['link_only'],dst=str(dst),sha256=sha(dst)))
    assert len({r['dst'] for r in links})==len(links)
    rust=[r for r in tree['processes'] if r['owner']]
    counts=Counter(r['owner'] for r in rust)
    save('workspace/joins.json',dict(links=links,compilers=rust,counts=counts,role=role,source=census.RUFF,command=census.COMMAND))
    save('workspace/accepted.json',dict(role=role,links=len(links),rustcs=len(rust),ron=counts['ron'],
         dirty=len(results['ordinary']['dirty']),source=census.RUFF,source_qa=CENSUS,head=os.environ['GITHUB_SHA']))
    assert not census.git(source,'status','--porcelain')
if __name__=='__main__':main(sys.argv[1])
