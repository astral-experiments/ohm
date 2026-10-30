"""A diagnostic on exactly one signed -21 ty_server test. No changed product or scored clock."""
import collections,gzip,hashlib,json,os,re,shutil,signal,subprocess,sys,tempfile,time
from pathlib import Path
orig=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(orig/'scripts/packaged-release-workspace'))
import linux as w
import linux_common as c
from packages import sha,save,prepare
root=(Path(os.environ['RUNNER_TEMP'])/'packaged-linux-50').resolve()
out=root/'diagnostic'; slot=root/'slot'
CMD=['cargo','+ohm','test','-p','ty_server','--test','e2e','--no-run','--locked','--offline','-j8','--message-format=json']
K=('ron','insta','e2e','ty_server','ruff_python_trivia','bitflags','serde_derive')
def gz(p,body):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(gzip.compress(body,compresslevel=1,mtime=0))
def digest(b):return hashlib.sha256(b).hexdigest()
def stat(p):
    st=p.stat();return [st.st_dev,st.st_ino,st.st_nlink,st.st_size,st.st_mtime_ns,st.st_ctime_ns]
def snapshot(where):
    # Every Rust depfile marker and its actual filename, including path/flags for the target regressions.
    dest=where/'inputs';dest.mkdir();blobs=out/'input-blobs';blobs.mkdir(exist_ok=True)
    summary={};fps={};alls=[]
    for tree in [slot/'target',slot/'shared']:
        for p in tree.rglob('*'):
            if not p.is_file() or p.is_symlink():continue
            name=p.name;ty=None
            if name.endswith('.d'):ty='compiler-d'
            elif p.parent.name=='fingerprint' or '.fingerprint' in p.parts:
                if name.startswith(('dep-lib-','dep-test-','dep-bin-')):ty='cargo-d'
                elif name.endswith('.json') and name.startswith(('lib-','test-','bin-')):ty='fp-json'
            elif name.endswith(('.rlink-cache.json','.rlink.json')):ty='saved-link'
            if not ty:continue
            b=p.read_bytes();markers=re.findall(rb'[^\s\x00:]{0,160}ohm-(?:recheck-dependent-links|foreign-span-bytes|untracked[^\s\x00:]{0,80}|assembler[^\s\x00:]{0,80}|opaque[^\s\x00:]{0,80})',b)
            rel=str(p.relative_to(slot))
            focus=any(re.search(r'(^|/|debug_|-|_)(?:'+n+r')(/|[-.])',rel) for n in K)
            h=digest(b);row=[ty,h,stat(p),sorted({x.decode('utf-8','backslashreplace') for x in markers})]
            alls.append([rel,*row])
            # Raw zero- and positive-marker files for all units. Genuine input bytes stay distinct.
            if ty in ('compiler-d','cargo-d','fp-json') or focus:
                q=blobs/(h+'.gz')
                if not q.exists():gz(q,b)
            if focus:summary[rel]=row
    gz(dest/'all.json.gz',json.dumps(alls,separators=(',',':')).encode());save(dest/'selected.json',summary)
def phase(repo,env,tools,label,state,explain):
    where=out/label;where.mkdir();w.room(root,60)
    if explain:env=env|{'CARGO_LOG':'cargo::compiler::fingerprint=trace,cargo::compiler=info'}
    t0=time.monotonic_ns()
    with tempfile.TemporaryDirectory(dir=env['TMPDIR']) as td:
        tmp=Path(td)
        with (tmp/'out').open('wb') as so,(tmp/'err').open('wb') as se:
            p=subprocess.Popen(['strace','-ff','-q','-ttt','-s','262144','-e','trace=execve,execveat,exit_group,wait4','-o',str(tmp/'process'),*CMD],env=env,cwd=repo,stdout=so,stderr=se,start_new_session=True)
            try:
                while p.poll() is None:
                    if (time.monotonic_ns()-t0)>1500*10**9 or shutil.disk_usage(root).free<60*2**30:raise RuntimeError('runtime guard')
                    time.sleep(.25)
            except BaseException:
                os.killpg(p.pid,signal.SIGKILL);p.wait();raise
        elapsed=time.monotonic_ns()-t0;sd=(tmp/'out').read_bytes();er=(tmp/'err').read_bytes()
        gz(where/'stdout.gz',sd);gz(where/'stderr.gz',er);save(where/'exit.json',p.returncode)
        kernels=[];ledger=[];waits=[]
        for f in sorted(tmp.glob('process.*')):
            pid=int(f.suffix[1:]);execs=[];ts_end=None
            for line in f.read_bytes().splitlines():
                m=re.match(rb'^(\d+\.\d+) (.*)$',line)
                if not m:continue
                ts,part=m[1].decode(),m[2]
                if part.startswith(b'execve(') and part.endswith(b'= 0'):
                    kernels.append([pid,ts,part.decode()]);path,args=c.event(part);execs.append([ts,path,args])
                if (part.startswith(b'exit_group(') or part.startswith(b'+++ exited with')):ts_end=ts
                if ('wait4(' in part[:12].decode(errors='replace') or b'<... wait4 resumed>' in part) and b'ru_utime=' in part:
                    waits.append([pid,ts,part.decode()])
            if execs:ledger.append([pid,[(n,p) for n,p,_ in execs],ts_end])
        gz(where/'kernel.json.gz',json.dumps(kernels,separators=(',',':')).encode());gz(where/'live.json.gz',json.dumps(ledger,separators=(',',':')).encode());gz(where/'wait4.json.gz',json.dumps(waits,separators=(',',':')).encode())
        assert p.returncode==0,er[-1600:]
    rows=[json.loads(v) for v in sd.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    arts=[z for z in rows if z['reason']=='compiler-artifact'];returned=[z for z in arts if z['executable']]
    e2e,=[z for z in returned if z['target']['name']=='e2e' and z['target']['src_path'].endswith('ty_server/tests/e2e/main.rs')]
    assert len(returned)==1 and len(arts)<400,(len(returned),len(arts))
    e=Path(e2e['executable']); lists=subprocess.check_output([e,'--list'],env=env,cwd=repo);gz(where/'list.gz',lists)
    assert c.RUN_CASE.encode()+b': test' in lists
    runtime=subprocess.run([e,c.RUN_CASE,'--exact'],env=env|{'INSTA_WORKSPACE_ROOT':str(repo),'INSTA_UPDATE':'no'},cwd=repo,capture_output=True,timeout=180)
    gz(where/'runtime.stdout.gz',runtime.stdout);gz(where/'runtime.stderr.gz',runtime.stderr)
    assert runtime.returncode==0 and b'1 passed' in runtime.stdout,(runtime.returncode,runtime.stderr[-850:])
    nats=[]; perctl=collections.Counter()
    for pid,ts,line in kernels:
        exe,args=c.event(line.encode());real=Path(exe).resolve()
        if real==Path(tools['rustc']['physical']) and '--crate-name' in args and '--out-dir' in args and not any(v.startswith('--print') for v in args):
            n=args[args.index('--crate-name')+1];mode='link-only' if any(x in ('-Zlink-only','link-only') for x in args) else 'full'; perctl[mode]+=1
            if n in K:nats.append([pid,ts,mode,n,digest(line.encode())])
        if real==Path(tools['wild']['physical']) and '-o' in args:
            perctl['wild']+=1;nats.append([pid,ts,'wild',args[args.index('-o')+1],digest(line.encode())])
    detail={'phase':label,'source_state':state,'environment':env,'command':CMD,'source_inputs':{s:(sha(repo/s) if (repo/s).exists() else None) for s in c.ORACLE['source']},'typed':len(arts),'dirty':[(z['target']['name'],z['target']['kind'],z['package_id']) for z in arts if not z['fresh']], 'counts':dict(perctl),'selected':nats,'elapsed_under_trace_ns':elapsed,'e2e':str(e),'e2e_sha256':sha(e),'inventory_sha256':digest(lists),'case_exit':0,'cargo_exit':p.returncode}
    save(where/'observed.json',detail)
    snapshot(where)
    # Current-epoch physical identity and content for every literal direct input of the focused compiler.
    inputs={}
    for pid,ts,line in kernels:
        exe,args=c.event(line.encode());is_unit=Path(exe).resolve()==Path(tools['rustc']['physical']) and '--crate-name' in args and args[args.index('--crate-name')+1] in K and '--out-dir' in args
        if not is_unit:continue
        name=args[args.index('--crate-name')+1];present=[]
        for k,a in zip(args,args[1:]):
            if k=='--extern' and '=' in a:
                n,v=a.split('=',1);q=Path(v)
                if q.is_file():present.append([n,v,stat(q),sha(q)])
        inputs[str(pid)]=[name,present]
    gz(where/'externs.json.gz',json.dumps(inputs,separators=(',',':')).encode())
    # Preserve actual products, including Ron, regardless of whether an intermediate
    # consumer physically compiled this visit. Also authenticate its native object roster.
    products={}
    for art in arts:
        if art['target']['name'] not in K:continue
        for lit in art['filenames']:
            p=Path(lit)
            if p.suffix not in {'.rlib','.rmeta','.so'} or not p.is_file():continue
            r=[stat(p),sha(p)]
            if art['target']['name'] in ('ron','insta') and p.suffix=='.rlib':
                members=subprocess.check_output(['ar','t',p],text=True).splitlines();md={}
                for name in members:
                    md[name]=digest(subprocess.check_output(['ar','p',p,name]))
                r.append(md)
            products[lit]=r
    gz(where/'selected-products.json.gz',json.dumps(products,separators=(',',':')).encode())
    print(label,len(arts),dict(perctl),detail['e2e_sha256'],flush=True)
def main():
    assert not root.exists() and orig.name=='original-qa';root.mkdir();out.mkdir();w.room(root,65)
    os.environ['GH_TOKEN']=os.environ.pop('QUALIFICATION_TOKEN')
    try:prepare(root,'21')
    finally:os.environ.pop('GH_TOKEN',None)
    repo=root/'source';subprocess.run(['git','init','-q',repo],check=True)
    for depth,rev in [(1,c.RUFF),(2,c.HISTORY)]:w.git(repo,'fetch','-q','--no-tags','--depth='+str(depth),'https://github.com/astral-sh/ruff.git',rev)
    w.git(repo,'switch','-q','--detach',c.RUFF);assert w.git(repo,'rev-parse','HEAD^{tree}').decode().strip()==c.TREE
    assert w.git(repo,'diff','--binary','--abbrev=10',c.HISTORY+'^',c.HISTORY)==(c.FIX/'historical.patch').read_bytes()
    w.replace(repo,'original');slot.mkdir();env=w.environment(root,'21',slot)
    fe={k:v for k,v in env.items() if k!='CARGO_NET_OFFLINE'}
    subprocess.run(['cargo','+ohm','fetch','--locked'],cwd=repo,env=fe,check=True,timeout=900)
    tools=w.tools(root,'21',env)
    save(out/'subjects.json',{'sdk':json.loads((root/'receipts/21/custody.json').read_bytes()),'tools':tools,'source':c.RUFF,'tree':c.TREE,'lock':sha(repo/'Cargo.lock'),'original_qa':w.git(orig,'rev-parse','HEAD').decode().strip(),'history':c.HISTORY})
    prev='original'
    base=tuple(CMD)
    if os.environ.get('FEATURE_DIAGNOSTIC')=='e2e-features':
        # ty_project requests these features for its snapshot tests. Only Ron
        # changes between the two adjacent selections. Cargo retains its own
        # independent feature-unit namespaces throughout all nine commands.
        near=('--features=insta/default,insta/redactions',)
        complete=('--features=insta/default,insta/redactions,insta/ron',)
        visits=[('cold','original',False,near),
                ('near-unchanged','original',True,near),
                ('with-feature','original',False,complete),
                ('unchanged','original',False,complete),
                ('explain-unchanged','original',True,complete),
                ('edited','reversed',True,complete),
                ('restored','original',True,complete),
                ('return-near','original',False,near),
                ('settled-near','original',True,near)]
    else:
        visits=[(name,state,explain,()) for name,state,explain in
                [('cold','original',False),('unchanged','original',False),('explain-unchanged','original',True),
                 ('edited','reversed',True),('restored','original',True)]]
    for name,state,explain,features in visits:
        CMD[:]=[*base,*features]
        if state!=prev:w.replace(repo,state)
        phase(repo,env,tools,name,state,explain);prev=state
    save(out/'terminal.json',{'phase_files':{p.parent.name:sha(p) for p in sorted(out.glob('*/observed.json'))},'true_historical_edit':c.HISTORY,'scope':'focused -p ty_server --test e2e only; elapsed diagnostics under strace; no timed results'})
if __name__=='__main__':main()
