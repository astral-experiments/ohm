"""Qualify the frozen real Ruff Old ruff_db library test using an ordinary signed Cargo build."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time


OLD='bb868838d75876c3b016d8cf1687d33eae80daa6'
TREE='45309df3de4b2b3aa0bf8ce7dddc852b177bce60'
LOCK='26d7be8317b0e44be0d60b31f6660dd4e07ed4c19be4e6748124d07068fd7fa7'
RUST='008a21ac0d750dc9a1c18b7959d7e7984c03d887'
CORE='b143081856738d73c8076a141b3032113a6fff63e9099748fa495e1e9c755e05'
CMD=['cargo','+ohm','test','--no-run','-p','ruff_db','--lib','--locked','--offline','-j2','--message-format=json']
TESTS=['diagnostic::render::full::tests::output','diagnostic::render::full::tests::syntax_errors']
PLAN="8b1b445cd53f7f72882375c91ebc22c7dace50872a8e1ab604bcb59223663443"
GB=1<<30
from array import array
from collections import deque
import hashlib,mmap,re,struct,subprocess
from pathlib import Path

# Frozen from the signed rustc self-profile + graph join, not from a fuzzy symbol-name match.
FOLD_LOCAL=0xea8d8267a69a9fd2
EXPECTED_CORE=0x94f40d7defb754b5

def need(ok,msg):
    if not ok:raise ValueError(msg)

def core_identity(sdk, env):
    path,=(sdk/'lib/rustlib/x86_64-unknown-linux-gnu/lib').glob('libcore-*.rmeta')
    raw=subprocess.check_output(['rustc','+ohm','-Zls=root',str(path)],env=env)
    sid=re.findall(rb'^private hash [a-f0-9]+ stable_crate_id StableCrateId\((\d+)\)$',raw,re.M)
    need(len(sid)==1 and b'\nname core-' in raw and b'\ntriple x86_64-unknown-linux-gnu\n' in raw,'wrong core metadata')
    return int(sid[0])

def leb(data,pos,limit):
    val=0
    for shift in range(0,35,7):
        need(pos<limit,'unterminated node length');b=data[pos];pos+=1;val|=(b&127)<<shift
        if b<128:return val,pos
    raise ValueError('overlong node length')

def read_contact(path):
    need(0 < path.stat().st_size < 1 << 30, "graph outside registered memory range")
    core=EXPECTED_CORE
    names=[str(i) for i in range(362)];names[5]="CompileCodegenUnit";names[238]="upstream_monomorphizations_for"
    schema=dict(names=names, format=10, version="1.99.0-dev (008a21ac0 2026-11-01) (ohm-1.99.0-22)")
    names=schema['names'];kind=names.index('upstream_monomorphizations_for');wanted=struct.pack('<QQ',core,FOLD_LOCAL)
    bits=(len(names)-1).bit_length();cgu=names.index('CompileCodegenUnit')
    with path.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
        need(mm[:4]==b'RSIC' and struct.unpack_from('<H',mm,4)[0]==schema['format'] and mm[7:7+mm[6]]==schema['version'].encode(),'wrong role graph')
        end=len(mm)-13;need(mm[end:]==b'rust-end-file','truncated graph');slots,nodes,edges=struct.unpack_from('<QQQ',mm,end-24)
        need(0<nodes<=slots<=3_000_000 and edges<=20_000_000,'graph outside registered bounds')
        limit=struct.unpack_from('<Q',mm,end-48)[0] if mm[end-32:end-24]==b'OHMIDX01' else end-24
        pos=15+mm[6];loc=array('I',[0])*slots;count=array('I',[0])*slots;start=array('I',[0])*slots;types=array('H',[0])*slots;width=bytearray(slots)
        roots=[];target=[];nedge=0;counts=[0]*len(names)
        for i in range(nodes):
            need(pos+38<=limit,'node overflow');word,idx=struct.unpack_from('<HI',mm,pos)
            typ=word & ((1<<bits)-1);need(idx<slots and 0<typ<len(names) and not loc[idx],'invalid sparse node')
            if typ==cgu:roots.append(idx)
            if typ==kind and mm[pos+6:pos+22]==wanted:target.append(idx)
            counts[typ]+=1;types[idx]=typ;loc[idx]=pos;pos+=38
            w=((word>>bits)&3)+1;n=(word>>(bits+2))-1
            if n<0:n,pos=leb(mm,pos,limit)
            count[idx]=n;start[idx]=pos;width[idx]=w;pos+=n*w;nedge+=n;need(pos<=limit,'edge overflow')
        for want in counts:
            got,pos=leb(mm,pos,limit);need(got==want,'kind footer disagreement')
        session,pos=leb(mm,pos,limit);need(pos==limit and nedge==edges and roots,'footer/CGU mismatch')
        def row(i):
            p=loc[i];return dict(index=i,kind=names[types[i]],key=''.join(f'{x:016x}'for x in struct.unpack_from('<QQ',mm,p+6)),value=''.join(f'{x:016x}'for x in struct.unpack_from('<QQ',mm,p+22)))
        def children(i):
            w=width[i];p=start[i]
            for k in range(count[i]):
                v=int.from_bytes(mm[p:p+w],'little');p+=w;need(v<slots and loc[v], 'edge to absent node');yield v
        desired=set(target);direct=[r for r in roots if not desired.isdisjoint(children(r))] if desired else []
        parent=array('i',[-2])*slots;queue=deque(roots);found=None
        for root in roots:parent[root]=-1
        while queue and desired and found is None:
            i=queue.popleft()
            if i in desired:found=i;break
            for child in children(i):
                if parent[child]==-2:parent[child]=i;queue.append(child)
        path_to=[]
        while found is not None and found>=0:path_to.append(row(found));found=parent[found]
        return dict(graph_sha256=hashlib.sha256(mm).hexdigest(),session=session,nodes=nodes,edges=edges,root_cgus=len(roots),upstream_for_rows=counts[kind],selected_definition={'crate':f'{core:016x}','local':f'{FOLD_LOCAL:016x}','name':'core::iter::adapters::map::{{impl}}[2]::fold'},targets=list(map(row,target)),shortest_path=path_to[::-1],direct_cgus=list(map(row,direct)))


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def store(path,obj):path.write_text(json.dumps(obj,sort_keys=True,indent=1)+'\n')

def available():
    n=int(re.search(r'^MemAvailable:\s*(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
    base=Path('/sys/fs/cgroup');line=next(l for l in Path('/proc/self/cgroup').read_text().splitlines() if l.startswith('0::'))
    p=base/line[3:].lstrip('/')
    while p.is_relative_to(base):
        if (p/'memory.max').is_file():
            limit=(p/'memory.max').read_text().strip()
            if limit!='max':n=min(n,int(limit)-int((p/'memory.current').read_text()))
        p=p.parent
    return n

def command(argv,env,src,out,state,expected=0):
    start=time.monotonic();floor=shutil.disk_usage(state).free;low=available();minimum=floor
    need(low>9*GB and floor>20*GB,'insufficient admission headroom')
    with (out/'cargo.stdout').open('xb') as stdout,(out/'cargo.stderr').open('xb') as stderr:
        p=subprocess.Popen(argv,env=env,cwd=src,stdout=stdout,stderr=stderr,start_new_session=True)
        try:
            while p.poll() is None:
                low=min(low,available());minimum=min(minimum,shutil.disk_usage(state).free)
                need(low>8*GB and minimum>15*GB and floor-minimum<8*GB and time.monotonic()-start<1800,'local resource limit exceeded');time.sleep(.25)
        finally:
            if p.poll() is None:os.killpg(p.pid,signal.SIGKILL);p.wait()
            store(out/'process.json',dict(argv=argv,exit=p.returncode,min_memory=low,min_disk=minimum))
    need(p.returncode==expected,'ordinary Cargo returned an unexpected status; see cargo.stderr')

def sdk_identity(sdk,env):
    driver,=sdk.glob('lib/librustc_driver-*.so');meta,=(sdk/'lib/rustlib/x86_64-unknown-linux-gnu/lib').glob('libcore-*.rmeta')
    actual={str(f.relative_to(sdk)):sha(f) for f in (sdk/'bin/cargo',sdk/'bin/rustc',driver,meta)}
    need(actual['bin/cargo']=='3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871' and actual['bin/rustc']=='7e35096dab1b661924cb3c31982c870dd99c7c00a7fba28aa958f451e7c9474e','different Cargo or rustc')
    need(actual[str(driver.relative_to(sdk))]=='4c8ccf0072e8f382a3a3756fd60e46936a2bd206996201c55caffe58d29725db' and actual[str(meta.relative_to(sdk))]==CORE,'unknown driver or core metadata')
    need(sdk.samefile(subprocess.check_output(['rustc','+ohm','--print=sysroot'],text=True,env=env).strip()),'different resolved compiler')
    need('commit-hash: '+RUST in subprocess.check_output(['rustc','+ohm','-vV'],env=env,text=True).splitlines() and core_identity(sdk,env)==EXPECTED_CORE,'different compiler/key binding')
    return actual

def plan_id(raw):
    graph=json.loads(raw);units=graph['units'];keys=[]
    def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for u in units:
        d=dict(u);del d['dependencies'];d['target']=dict(d['target']);del d['target']['src_path']
        pkg=d['pkg_id']
        if pkg.startswith('path+file://'):
            need('/crates/' in pkg,'expected real Ruff workspace member');d['pkg_id']='ruff/crates/'+pkg.rsplit('/crates/',1)[-1]
        keys.append(digest(d))
    completed={};visiting=set()
    def subgraph(i):
        if i in completed:return completed[i]
        need(i not in visiting,'cycle in Cargo graph');visiting.add(i);children=[]
        for child in units[i]['dependencies']:
            e=dict(child);j=e.pop('index');children.append([subgraph(j),e])
        visiting.remove(i);completed[i]=digest([keys[i],sorted(children,key=lambda x:json.dumps(x,sort_keys=True))]);return completed[i]
    root,=graph['roots'];signature=subgraph(root);need(len(completed)==len(units),'orphaned unit')
    return digest([signature,sorted(completed.values())])

def source(src):
    def git(*args):return subprocess.check_output(['git','-C',src,*args],text=True).strip()
    need(git('rev-parse','HEAD')==OLD and git('rev-parse','HEAD^{tree}')==TREE and git('status','--porcelain=v1','--untracked-files=all')=='' and sha(src/'Cargo.lock')==LOCK,'need clean exact historical source')

def provider_folds(rlib):
    result=subprocess.run(['/usr/bin/nm','--extern-only','--defined-only','--format=posix',rlib],capture_output=True,timeout=60,check=True)
    symbols=sorted(set(row.split(None,1)[0] for row in result.stdout.splitlines() if row.startswith(b'_R') and b' T ' in row))
    pretty=subprocess.check_output(['/usr/bin/c++filt','-s','rust'],input=b'\n'.join(symbols)+b'\n',timeout=30).splitlines()
    out=[]
    for sym,name in zip(symbols,pretty,strict=True):
        if not name.startswith(b'<core[94f40d7defb754b5]::iter::adapters::map::Map<'):continue
        depth=0
        for end,byte in enumerate(name):
            depth+=(byte==ord('<'))-(byte==ord('>'))
            if depth==0:break
        receiver=name[:end+1];match=re.search(rb'::splice_lines::\{closure#([23])\}',receiver);op=re.search(rb'Iterator::(min|max)_by::fold<',name[end+1:])
        if name[end+1:].startswith(b'::fold::<') and b'::snippet::Patch' in receiver and b'annotate_snippets' in receiver and match and op:
            out.append(dict(mangled=sym.decode(),demangled=name.decode(),closure=int(match[1]),operation=op[1].decode()))
    need(len(out)==2 and {v['operation'] for v in out}=={'min','max'} and {v['closure'] for v in out}=={2,3},'expected both Old renderer splice_lines Map::fold owners');return out

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('src','sdk','registry','proxies','state','out'):ap.add_argument('--'+key,required=True,type=Path)
    a=ap.parse_args();src,sdk,reg,proxy=(x.resolve(strict=True)for x in(a.src,a.sdk,a.registry,a.proxies));state,out=(x.resolve()for x in(a.state,a.out));source(src)
    need(not state.exists() and not out.exists() and not state.is_relative_to(out) and not out.is_relative_to(state) and not state.is_relative_to(src) and not out.is_relative_to(src),'distinct fresh private/published dirs required');state.mkdir();out.mkdir();need(state.stat().st_dev==out.stat().st_dev,'private state and receipts must share the guarded filesystem')
    for sub in ('home','cargo/registry','rustup/toolchains','tmp','target','build'):(state/sub).mkdir(parents=True)
    (state/'rustup/toolchains/ohm').symlink_to(sdk);(state/'rustup/settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    for k in ('index','cache'):
        origin=reg/k/'index.crates.io-1949cf8c6b5b557f';need(origin.is_dir(),f'prefill {origin} with the Old locked registry');dest=state/'cargo/registry'/k;dest.mkdir();(dest/origin.name).symlink_to(origin)
    env={'HOME':str(state/'home'),'PATH':str(proxy)+':/usr/bin:/bin','RUSTUP_HOME':str(state/'rustup'),'RUSTUP_TOOLCHAIN':'ohm','RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(state/'cargo'),'CARGO_TARGET_DIR':str(state/'target'),'CARGO_BUILD_BUILD_DIR':str(state/'build'),'TMPDIR':str(state/'tmp'),'LC_ALL':'C','CARGO_TERM_COLOR':'never','CARGO_NET_OFFLINE':'true','CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never'}
    proof=sdk_identity(sdk,env);plan=subprocess.check_output(CMD+['-Zunstable-options','--unit-graph'],cwd=src,env=env,timeout=60);(out/'unit-graph.json').write_bytes(plan);digest=plan_id(plan);need(digest==PLAN, 'different root, targets, features, profiles or dependencies')
    store(out/'registration.json',dict(source=OLD,tree=TREE,lock=LOCK,sdk=proof,query='94f40d7defb754b5ea8d8267a69a9fd2',dictionary_sha256='683d48c4ecc7c07c8a9e6d0428d37c6de0e6e6792c4cfbbc571acc16bf71358e',plan_digest=digest,argv=CMD));command(CMD,env,src,out,state)
    raw=[json.loads(line)for line in (out/'cargo.stdout').read_bytes().splitlines()];need(raw[-1]=={'reason':'build-finished','success':True},'unconfirmed terminal Cargo')
    rows=[x for x in raw if x.get('reason')=='compiler-artifact'];test,=[x for x in rows if x['target']['name']=='ruff_db' and x['target']['kind']==['lib'] and x['profile']['test']];provider,=[x for x in rows if x['target']['name']=='annotate_snippets' and x['target']['kind']==['lib'] and x['features']==['default','simd','std']]
    exe=Path(test['executable']);rlib,=(Path(f)for f in provider['filenames']if f.endswith('.rlib'));need(not test['fresh'] and not provider['fresh'] and all(f.resolve(strict=True).is_relative_to(state) for f in (exe,rlib)),'wrong or reused native artifacts')
    names=subprocess.check_output([exe,'--list','--format','terse'],cwd=src,env=env,timeout=60);(out/'tests.list').write_bytes(names);tested={}
    for name in TESTS:
        need(names.splitlines().count((name+': test').encode())==1,'missing renderer case');result=subprocess.run([exe,'--exact',name,'--test-threads=1'],cwd=Path(test['manifest_path']).parent,env=env,capture_output=True,timeout=60)
        (out/(name+'.stdout')).write_bytes(result.stdout);(out/(name+'.stderr')).write_bytes(result.stderr);need(result.returncode==0 and b'test result: ok. 1 passed; 0 failed;' in result.stdout,'the actual renderer test failed');tested[name]=result.returncode
    folds=provider_folds(rlib);store(out/'provider-folds.json',folds)
    paths=[p for k in ('build','target')for p in (state/k).rglob('dep-graph.bin')if p.parent.name.startswith('s-') and not p.parent.name.endswith('-working') and p.parent.parent.name.startswith('ruff_db-')];graph,=paths;need(graph.resolve(strict=True).is_relative_to(state),'unowned graph')
    ev=read_contact(graph);values={q['value']for q in ev['targets']};need(len(values)<=1,'conflicting values for the enrolled physical key');store(out/'contact.json',ev)
    need(shutil.disk_usage(out).free>15*GB+graph.stat().st_size and available()>8*GB,'insufficient headroom to retain the actual graph')
    with graph.open('rb')as f,gzip.open(out/'old-dep-graph.bin.gz','wb',compresslevel=1)as g:shutil.copyfileobj(f,g,length=1<<20)
    with gzip.open(out/'old-dep-graph.bin.gz','rb')as f:need(hashlib.file_digest(f,'sha256').hexdigest()==ev['graph_sha256'],'changed archived graph')
    res=dict(admitted=bool(values and ev['shortest_path']),target='ruff_db --lib',old_only=True,raw_graph_sha256=ev['graph_sha256'],graph=str(graph),test_exe_sha256=sha(exe),renderer_rlib_sha256=sha(rlib),native_render_cases=tested,provider_folds=len(folds),query_path=ev['shortest_path']);source(src);store(out/'terminal.json',res);print(json.dumps(res))

if __name__=='__main__':main()
