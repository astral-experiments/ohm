"""One direct native signed cargo check screen. No change to a Cargo/rustc cache policy."""
import collections,gzip,hashlib,json,os,re,shutil,statistics,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;original=Path(sys.argv[1]).resolve();counter_fixture=Path(sys.argv[2]).resolve()
sys.path.insert(0,str(original/'scripts/packaged-release-workspace'))
import linux as w
import linux_common as c
import packages
R=(Path(os.environ['RUNNER_TEMP'])/'ordinary-ron-check').resolve();O=R/'packet';S=R/'slot';src=R/'source'
hist='32c5cd5daba51d9c3da691c5b43afa6a7a4bb731'
changed='crates/ty_project/src/uv/metadata/dependencies.rs'
cmd=['cargo','+ohm','check','-p','ty_project','--tests','--locked','--offline','-j8','--message-format=json']
save=packages.save
def h(b):return hashlib.sha256(b).hexdigest()
def gz(p,b):p.write_bytes(gzip.compress(b,compresslevel=1,mtime=0))
def run(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
def read(path):return json.loads(path.read_bytes())
def get(cmd,**kw):return subprocess.check_output(cmd,**kw)
def sha(p):return packages.sha(p)
def argv(target):
    rows=[]
    for line in (target/'exec.tsv').read_text().splitlines():
        number,pid,dev,ino,selected,path=line.split('\t')
        args=(target/f'args-{int(number):04d}').read_bytes();assert args[-1:]==b'\x00'
        rows.append([int(pid),[int(dev),int(ino)],int(selected),path,[os.fsdecode(v) for v in args[:-1].split(b'\x00')]])
    return rows
def read_counts(t):
    rows={v[0]:list(map(int,v[1:]))for row in (t/'counts.tsv').read_text().splitlines() if (v:=row.split('\t'))}
    assert set(rows)=={'root','hits','whole','selected'}
    return rows
def hw(x):return x[0]==0 and x[1]>0 and x[2]==x[3] and x[2]>0
def observe(name,selected,mode,command,env=None,cwd=None):
    place=O/name;place.mkdir(parents=True);xt=place/'trace';xt.mkdir()
    assert selected.is_file();obs=R/'observer'
    p=subprocess.run([obs,xt,selected,mode,*command],cwd=cwd,env=env,capture_output=True,timeout=1200)
    gz(place/'stdout.gz',p.stdout);gz(place/'stderr.gz',p.stderr)
    cc=read_counts(xt);events=argv(xt)
    assert cc['root'][1]==p.returncode and len([i for i in events if i[2]])==cc['hits'][0]
    save(place/'pmu.json',cc)
    return p,cc,events
def calibration():
    assert sha(counter_fixture)=='dacd1dd7fef85cacb44a236e0c4191d95db036a623b2a01ae3a5d76d2f3d0b0e'
    for source,target,opts in [(HERE/'observe.c','observer',[]),(HERE/'calibration_driver.c','driver',[]),(counter_fixture,'loop',['-pthread'])]:
        run(['cc','-O2','-Wall','-Werror',*opts,source,'-o',R/target])
    selector=R/'cal-selected';shutil.copy2(R/'driver',selector);assert not selector.samefile(R/'driver')
    out=O/'calibration';out.mkdir();checks=[];n=20000000
    for group,(depth,copies) in enumerate([('0',1),('1',1),('2',1),('2',2),('exec',1),('thread',1),('thread',2)]):
        vals=[]
        for i,count in enumerate((0,n,0,n)):
            p,row,events=observe(f'calibration/g{group}-{i}',selector,'cal',[R/'driver','outer',selector,R/'loop',depth,str(count),str(copies),str(count//2)])
            assert p.returncode==0 and row['hits']==[1] and sum(x[2] for x in events)==1
            vals.append(row)
        calc=lambda key:statistics.median(q[key][1] for q in vals[1::2])-statistics.median(q[key][1] for q in vals[::2])
        want=2*n*copies;expect_total=want+n
        checks.append({'depth':depth,'copies':copies,'selected_delta':calc('selected'),'selected_expected':want,'whole_delta':calc('whole'),'whole_expected':expect_total,
            'complete_coverage':all(hw(q[key]) for q in vals for key in ('whole','selected')),
            'admit':all(hw(q[key]) for q in vals for key in ('whole','selected')) and abs(calc('selected')/want-1)<.02 and abs(calc('whole')/expect_total-1)<.02})
    save(out/'summary.json',checks)
    return all(x['admit'] for x in checks)
def facts(p,cc,events,environment,outdir,label):
    js=[json.loads(x) for x in p.stdout.splitlines()];assert js[-1]=={'reason':'build-finished','success':p.returncode==0}
    art=[o for o in js if o['reason']=='compiler-artifact'];errors=[o['message'] for o in js if o.get('message',{}).get('level')=='error']
    compressed=[]
    for a in art:
        compressed.append([a['package_id'],a['target']['name'],a['target']['kind'],a['mode'] if 'mode' in a else None,a['profile']['test'],a['features'],a['fresh']])
    z=(outdir/'cargo-roster.json.gz');gz(z,json.dumps(compressed,separators=(',',':')).encode())
    ident=lambda p:[p.stat().st_dev,p.stat().st_ino]
    sdk=R/'sdk-21';rust=ident(sdk/'bin/rustc');cargo=ident(sdk/'bin/cargo')
    cps=[];wld=[];selected=[];roots=[]
    for pid,identity,match,image,args in events:
        if identity==cargo and args[1:]==cmd[2:]:roots.append(pid)
        if identity==rust and '--crate-name' in args and '--out-dir' in args and not any(x.startswith('--print') for x in args):
            n=args[args.index('--crate-name')+1];mode='link-only' if any(x in ('-Zlink-only','link-only') for x in args) else 'full'
            emit=next(x for x in args if x.startswith('--emit='));cps.append([pid,n,mode,emit])
            if n=='ron':
                assert match==1 and emit=='--emit=dep-info,metadata' and not any('incremental=' in x for x in args) and any('/ron-0.12.0/src/lib.rs' in x for x in args)
                selected.append([pid,args])
        if Path(image).name in ('ld.bfd','ld','wild','rust-lld','ld.lld') and '-o' in args:wld.append([pid,image,args[args.index('-o')+1]])
    if cc is not None:assert len(roots)==1 and len(selected)==cc['hits'][0]
    deps=[]
    for pid,args in selected:
        dest=Path(args[args.index('--out-dir')+1]);assert dest.resolve().is_relative_to(S)
        for dep in sorted(dest.glob('ron-*.d')):
            raw=dep.read_bytes();key=h(raw)
            deps.append([str(dep),key,raw.count(b'ohm-foreign-span-bytes')])
            blob=O/(key+'.dep.gz')
            if not blob.exists():gz(blob,raw)
    item={'phase':label,'cargo_exit':p.returncode,'command':cmd,'actual_rustcs':cps,'native_links':wld,'root_cargo':roots,'selected_ron':selected,
          'unit_count':len(art),'native_ron_marker':deps,'dirty':[(a['target']['name'],a['target']['kind']) for a in art if not a['fresh']],
          'returned_executables':[a['executable'] for a in art if a.get('executable')],'source_sha':sha(src/changed),'errors':errors,
          'physical_ron_input':sha(src/'Cargo.lock'),'code':cc if cc is not None else None}
    assert not item['returned_executables']
    save(outdir/'record.json',item)
    return item
def invocation(label,env,instrument=True,command=None):
    command=command or cmd
    if instrument:p,cc,ev=observe(label,R/'sdk-21/bin/rustc','ron',command,env,src)
    else:
        (O/label).mkdir();p=subprocess.run(command,cwd=src,env=env,capture_output=True,timeout=1500)
        gz(O/label/'stdout.gz',p.stdout);gz(O/label/'stderr.gz',p.stderr);cc,ev=None,[]
    return facts(p,cc,ev,env,O/label,label)
def acquire():
    assert not R.exists();R.mkdir();O.mkdir();S.mkdir()
    assert w.git(original,'rev-parse','HEAD').decode().strip()=='f40b16cdb9c041c941a5e339f816111a80a84bdf'
    w.room(R,60)
    real_aff=sorted(os.sched_getaffinity(0));assert len(real_aff)>=8
    os.sched_setaffinity(0,real_aff[:8]);save(O/'host.json',{'prior_affinity':real_aff,'actual':sorted(os.sched_getaffinity(0)),'cpuinfo':Path('/proc/cpuinfo').read_text().split('\n\n')[0],'pmu_paranoid':Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip()})
    os.environ['GH_TOKEN']=os.environ.pop('QUALIFICATION_TOKEN')
    try:packages.prepare(R,'21')
    finally:os.environ.pop('GH_TOKEN')
    run(['git','init','-q',src])
    for depth,commit in [(1,c.RUFF),(2,hist)]:w.git(src,'fetch','-q','--depth='+str(depth),'--no-tags','https://github.com/astral-sh/ruff.git',commit)
    w.git(src,'switch','-q','--detach',c.RUFF)
    assert w.git(src,'rev-parse','HEAD^{tree}').decode().strip()==c.TREE and sha(src/'Cargo.lock')==c.LOCK
    assert w.git(src,'diff','--binary','--abbrev=10',hist+'^',hist)==gzip.decompress((HERE/'historical.patch.gz').read_bytes()) and h(gzip.decompress((HERE/'historical.patch.gz').read_bytes()))=='b583905f8f7bf43ff81aad1e29fae01eeba5b21fea091319041e20349af91008'
    assert (src/changed).read_bytes()==w.git(src,'show',hist+':'+changed)
    env=w.environment(R,'21',S);tools=w.tools(R,'21',env)
    assert not any(v in env for v in ('CI','TF_BUILD','RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_INCREMENTAL','GITHUB_TOKEN','GH_TOKEN'))
    save(O/'subjects.json',{'qa':w.git(HERE,'rev-parse','HEAD').decode().strip(),'original_qa':w.git(original,'rev-parse','HEAD').decode().strip(),'source':c.RUFF,'tree':c.TREE,'history':hist,'changed':changed,
        'original_blob':h((src/changed).read_bytes()),'historical_parent_blob':h(w.git(src,'show',hist+'^:'+changed)),'lock':sha(src/'Cargo.lock'),'kit':read(R/'receipts/21/custody.json'),'tools':tools,
        'versions':read(R/'receipts/21/tools.json'),'environment':env,'srcs':{p.name:sha(p) for p in HERE.iterdir() if p.is_file()},'calibration_source':sha(counter_fixture)})
    fetch={k:v for k,v in env.items() if k!='CARGO_NET_OFFLINE'};run(['cargo','+ohm','fetch','--locked'],cwd=src,env=fetch,timeout=800)
    scans={}
    for n in ('ty_server','ruff_db','ty_project'):
        a=['cargo','+ohm','check','-p',n,'--tests','--locked','--offline','-j8','--unit-graph','-Zunstable-options']
        data=get(a,cwd=src,env=env);graph=json.loads(data);gz(O/(n+'-graph.json.gz'),data)
        scans[n]={'roots':[[i,graph['units'][i]['target']['name'],graph['units'][i]['mode']] for i in graph['roots']],
            'ron':[[i,u['pkg_id'],u['features'],u['mode']] for i,u in enumerate(graph['units']) if u['target']['name']=='ron'],'units':len(graph['units'])}
    save(O/'selection.json',scans)
    assert not scans['ty_server']['ron'] and not scans['ruff_db']['ron'] and len(scans['ty_project']['ron'])==1,(scans,)
    return env
def profile(env):
    # Different generation with the same wrapper for training and the studied
    # repeat. Only the Ron rustc has extra profiling flags in this separate lane.
    base=R/'separate-profile';base.mkdir();data=O/'ron-profiles';data.mkdir()
    dest=base/'profile-rustc';shutil.copy2(HERE/'profile_rustc.py',dest);dest.chmod(0o700)
    prof=env|{'RUSTC_WRAPPER':str(dest),'CARGO_TARGET_DIR':str(base/'target'),'CARGO_BUILD_BUILD_DIR':str(base/'shared'),'QA_RON_PROFILE':str(data)}
    result=[]
    for label in ('profile-training','profile-repeat'):
        before={x.name for x in data.iterdir()};q=invocation(label,prof,False)
        assert q['cargo_exit']==0
        generated=sorted(x.name for x in data.iterdir() if x.name not in before)
        assert len(generated)==1
        at=data/generated[0];files={x.name:[x.stat().st_size,sha(x)] for x in sorted(at.iterdir())}
        assert any(k.endswith('.mm_profdata') and size>5000 for k,(size,_) in files.items()) and 'timings.stderr' in files
        result.append([label,generated[0],files])
    save(data/'visits.json',result)
def main():
    env=acquire();ok=calibration();save(O/'counter-status.json',{'all_seven_scopes':ok})
    if not ok:
        save(O/'terminal.json',{'classification':'hardware selection/direct and sibling calibration failed; no trustworthy instruction fraction'});return
    cold=invocation('cold',env,False);assert cold['cargo_exit']==0
    run(['git','-C',src,'apply','--reverse','-'],input=gzip.decompress((HERE/'historical.patch.gz').read_bytes()));assert (src/changed).read_bytes()==w.git(src,'show',hist+'^:'+changed)
    edit=invocation('edited',env);repeat=invocation('first-unchanged',env)
    assert edit['cargo_exit']==repeat['cargo_exit']==0 and edit['unit_count']==repeat['unit_count']==cold['unit_count']
    assert edit['source_sha']==repeat['source_sha']!=cold['source_sha'] and any(x[1]=='ty_project' for x in edit['actual_rustcs'])
    counts=repeat['code'];assert hw(counts['whole'])
    if not repeat['selected_ron']:
        verdict='no physical Ron compiler on first unchanged ordinary check';share=0.
    else:
        assert len(repeat['selected_ron'])==1 and hw(counts['selected']) and 0<counts['selected'][1]<counts['whole'][1]
        share=counts['selected'][1]/counts['whole'][1]
        verdict='one Ron sub-compilation; sub-half instruction share' if share<0.5 else 'Ron accounts for at least half of first unchanged command user instructions'
    receipt={'classification':verdict,'selected_ron':len(repeat['selected_ron']),'share':share,'ideal_instruction_speedup':1/(1-share),'unit_count':repeat['unit_count'],'counts':counts,'scope':'one genuine signed Linux developer check; no timing or performance inference about other edits'}
    save(O/'structural.json',receipt)
    if share>=.5:
        broken=src/'crates/ty_project/src/lib.rs';clean=broken.read_bytes()
        try:
            broken.write_bytes(clean+b'\nconst _: u8 = "OHM_RON_CHECK_BAD_TYPE";\n')
            err=invocation('invalid',env,False)
            assert err['cargo_exit']==101 and any(m.get('code',{}).get('code')=='E0308' and any(s.get('is_primary') and s['file_name'].endswith('ty_project/src/lib.rs') for s in m['spans']) for m in err['errors'] if m.get('code'))
        finally:broken.write_bytes(clean)
        rep=invocation('repair',env,False);assert rep['cargo_exit']==0 and not rep['errors'] and rep['source_sha']==edit['source_sha']
        profile(env)
    save(O/'terminal.json',receipt)
if __name__=='__main__':main()
