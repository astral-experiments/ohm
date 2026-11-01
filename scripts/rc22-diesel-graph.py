"""Replay Diesel's optimized incremental training input on matched Apple compilers."""
import hashlib,json,os,shlex,shutil,subprocess,sys,tarfile
from pathlib import Path
origin=Path(os.environ['GITHUB_WORKSPACE']);work=Path(os.environ['WORK'])
evidence=work/'receipts/graph';evidence.mkdir(parents=True)
perf=origin/'perf';dataset=perf/'collector/compile-benchmarks/diesel-2.2.10'
def read(*cmd,cwd=None,env=None):return subprocess.check_output(cmd,cwd=cwd,env=env,text=True).strip()
assert read('git','rev-parse','HEAD',cwd=perf)=='0a054b0ead56e41a4584bfab6fdc1a5fad2aedc3'
assert read('git','rev-parse','HEAD:collector/compile-benchmarks/diesel-2.2.10/src',cwd=perf)=='9307a25d713064b7e106f202f5b54e17739d50b6'
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
assert digest(work/'parent/bin/cargo')==digest(work/'candidate/bin/cargo')
project=work/'diesel-input';shutil.copytree(dataset,project)
patchfile=Path('src/query_dsl/mod.rs')
results=[]
for role,sha in [('parent','556a8364'),('candidate','00526133')]:
    out=evidence/role;out.mkdir()
    area=work/('diesel-'+role);area.mkdir();(area/'tmp').mkdir();(area/'rustup').mkdir()
    shutil.copyfile(dataset/patchfile,project/patchfile)
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','DEVELOPER_DIR','SDKROOT','USER','LANG','LC_ALL')}
    env.update(RUSTUP_HOME=str(area/'rustup'),CARGO_HOME=str(work/'diesel-cargo-home'),CARGO_TARGET_DIR=str(area/'target'),CARGO_BUILD_BUILD_DIR=str(area/'build'),CARGO_INCREMENTAL='1',TMPDIR=str(area/'tmp'),CARGO_BUILD_JOBS='4')
    alias='ohm-graph';subprocess.run(['rustup','toolchain','link',alias,str(work/role)],env=env,check=True)
    versions={k:read(k,'+'+alias,'-vV',cwd=project,env=env) for k in ('rustc','cargo')}
    assert sha in versions['rustc'] and '4591cf45' in versions['cargo']
    current={'role':role,'versions':versions,'stages':[]};results.append(current)
    def save(): (evidence/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    def run(stage,cmd,e):
        log=out/(stage+'.log')
        with log.open('wb') as f:r=subprocess.run(cmd,cwd=project,env=e,stdout=f,stderr=subprocess.STDOUT)
        graphs=[]
        for g in sorted((area/'collector-incr').glob('**/dep-graph.bin')):
            graphs.append({'name':str(g.relative_to(area)),'size':g.stat().st_size,'sha256':digest(g)})
            if r.returncode and g.stat().st_size<=450_000_000:
                with tarfile.open(out/(stage+'-'+str(len(graphs))+'.tar.gz'),'w:gz',compresslevel=1) as t:t.add(g,arcname=g.name,recursive=False)
        current['stages'].append(dict(name=stage,code=r.returncode,log=digest(log),graphs=graphs));save()
        return r.returncode,log
    scratch=area/'prepare-incr'
    args=['cargo','+'+alias,'rustc','--locked','--release','--lib','-vv','--','-C','incremental='+str(scratch),'-Zthreads=1','-Adeprecated','-Aunknown-lints','-Zincremental-verify-ich']
    rc,cold=run('prepare',args,env)
    if rc:continue
    lines=[l for l in cold.read_text(errors='replace').splitlines() if 'Running `' in l and '--crate-name diesel ' in l]
    assert len(lines)==1,lines[-1:]
    tokens=shlex.split(lines[0].split('Running `',1)[1].removesuffix('`'))
    e=dict(env)
    while '=' in tokens[0] and not tokens[0].startswith('/'):
        k,v=tokens.pop(0).split('=',1);e[k]=v
    assert Path(tokens[0]).name=='rustc' and tokens[tokens.index('--crate-name')+1]=='diesel'
    e.update(RUSTC_FORCE_INCR_COMP_ARTIFACT_HEADER='rustc-perf',RUSTC_FORCE_RUSTC_VERSION='rustc-perf')
    tokens=[s.replace(str(scratch),str(area/'collector-incr')) for s in tokens]
    (out/'invocation.json').write_text(json.dumps(tokens,indent=2)+'\n')
    for phase in ('incremental-full','incremental-unchanged','incremental-patched','repeat-patch'):
        if phase=='incremental-patched':subprocess.run(['patch','-p1','-i',str(dataset/'0-println.patch')],cwd=project,check=True)
        if run(phase,tokens,e)[0]:break
print([(r['role'],[(s['name'],s['code']) for s in r['stages']]) for r in results]);assert all(len(r['stages'])==5 and not any(s['code'] for s in r['stages']) for r in results)
