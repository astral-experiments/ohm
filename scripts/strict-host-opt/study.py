"""Fresh untraced whole-command measurements; role-specific physical references are separate."""
from pathlib import Path
import collections,gzip,hashlib,importlib.util,json,os,shutil,statistics,subprocess,sys,tomllib
ROOT=Path(os.environ['GITHUB_WORKSPACE']); HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
OLD=ROOT/'ron';SIGNED=ROOT/'signed';COUNTER=ROOT/'counters/scripts/ohm-gnu-syscall';NATIVE=ROOT/'native'
for p,commit in [(OLD,'9d1dd09be4d2346142957cc298093d8a75c755c3'),(SIGNED,'f40b16cdb9c041c941a5e339f816111a80a84bdf'),(COUNTER,'927e20bcad028e5ed4290a58bd330a258ee5da41'),(NATIVE,'8b6d208b982fb3cb4a803a2976934c80bfcc66b5')]:
    assert subprocess.check_output(['git','-C',p,'rev-parse','HEAD']).decode().strip()==commit

def load(p,args):
    saved=sys.argv;sys.argv=[str(p),*map(str,args)];sys.path.insert(0,str(p.parent))
    try:
        spec=importlib.util.spec_from_file_location(p.stem,p);obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
    finally:sys.argv=saved
m=load(OLD/'scripts/ron-check-share/measure.py',[SIGNED,COUNTER/'calibrate.c'])
S=m.S;O=m.O;R=m.R; src=m.src; order=os.environ['QA_ORDER'];assert order in ('01','10')
sdk=R/'sdk-21';cargo=sdk/'bin/cargo';rust=sdk/'bin/rustc';wild=sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
OVERRIDE='CARGO_PROFILE_DEV_BUILD_OVERRIDE_OPT_LEVEL'; BAD=b'\nconst _: u8 = "OHM_HOST_PROFILE_BAD_TYPE";\n'
consumer=src/'crates/ty_project/src/lib.rs'; generated_names=['generated.rs','generated_alias.rs','generated_phf.rs']

def storage(where):
    os.sync();roots=[S/x for x in ('target','shared')];seen=set();rows=[];n=0
    for tree in roots:
        for path in [tree,*sorted(tree.rglob('*'))]:
            st=path.lstat();identity=st.st_dev,st.st_ino
            rows.append([str(path.relative_to(S)),st.st_dev,st.st_ino,st.st_mode,st.st_blocks,st.st_size,st.st_nlink]);n+=1
            seen.add(identity)
    blocks={tuple(r[1:3]):r[4] for r in rows};allocated=sum(blocks.values())*512
    du=m.get(['du','--summarize','--block-size=1','--',*roots],text=True)
    assert sum(int(r.split('\t',1)[0]) for r in du.splitlines())==allocated,(du,allocated)
    m.gz(where/'allocated-ledger.gz',json.dumps(rows,separators=(',',':')).encode());return {'allocated_B':allocated,'paths':n,'unique':len(seen),'hardlink_aliases':n-len(seen),'gnu_du':du}

def clear():
    m.w.room(R,15)
    for k in ('target','shared','ron-session'):
        f=S/k;assert f.parent==S and S.parent==R and not f.is_symlink()
        if f.exists():shutil.rmtree(f)
        assert not f.exists()

def edited(on):
    p=src/m.changed
    want=m.w.git(src,'show',(m.hist+'^' if on else m.hist)+':'+m.changed)
    if p.read_bytes()!=want:p.write_bytes(want)
    assert p.read_bytes()==want and m.sha(src/'Cargo.lock')==m.c.LOCK

def env_for(env,arm):return env|({OVERRIDE:'1'} if arm=='1' else {})

def procure():
    env=m.acquire();assert len(os.sched_getaffinity(0))==8
    selected={'cargo':'4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e','rustc':'f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9','wild':'0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5','driver':'dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3'}
    driver,=(sdk/'lib').glob('librustc_driver*.so')
    for n,k in [('cargo',cargo),('rustc',rust),('wild',wild),('driver',driver)]:assert m.sha(k)==selected[n]
    cargo.rename(R/'signed-cargo-retained');shutil.copy2(Path(os.environ['RUNNER_TEMP'])/'strict-qualified-cargo/cargo',cargo)
    select=m.get(['cargo','+ohm','-Vv'],env=env).decode();assert m.sha(cargo)=='035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4' and '761ea115605c34f11a1cd29afd68812c1e1359dd' in select
    locked={a['name']+'-'+a['version']+'.crate':a['checksum'] for a in tomllib.loads((src/'Cargo.lock').read_text())['package'] if 'checksum' in a};actual={f.name:m.sha(f) for f in (Path(env['CARGO_HOME'])/'registry').glob('cache/*/*.crate')};assert len(locked)==498 and actual==locked
    assert OVERRIDE not in env and not ({'CI','RUSTFLAGS','CARGO_INCREMENTAL','TF_BUILD','RUSTC_WRAPPER','GH_TOKEN','GITHUB_TOKEN'}&env.keys())
    m.save(O/'strict.json',{'head':os.environ['GITHUB_SHA'],'order':order,'run':os.environ['GITHUB_RUN_ID'],'selected':select,'cargo':m.sha(cargo),'signed':selected,'locked':locked,'environment':env,'cli':m.cmd,'host':os.uname().nodename,'plan':m.sha(HERE/'PLAN.md')})
    for srcfile,out,extra in ((COUNTER/'watch.c','watch',[]),(COUNTER/'calibrate.c','loop',['-pthread']),(m.HERE/'observe.c','capture',[])):
        m.run(['cc','-O2','-Wall','-Werror',*extra,srcfile,'-o',R/out]);assert (R/out).is_file()
    d=O/'calibration';d.mkdir();cal=[]
    n=80000000
    for i,(mode,copies) in enumerate((('0',1),('1',1),('2',1),('2',2),('exec',1),('thread',1),('thread',2))):
        rows=[]
        for j,v in enumerate((0,n,0,n)):
            f=d/f'{i}-{j}.json';m.run([R/'watch',f,R/'loop',mode,str(v),str(copies)]);row=m.read(f);assert hw(row);rows.append(row['instructions'])
        delta=statistics.median(rows[1::2])-statistics.median(rows[::2]);assert abs(delta/(2*n*copies)-1)<.02,(mode,rows)
        cal.append([mode,copies,rows,delta,2*n*copies])
    m.save(d/'verified.json',cal);clear();return env

def hw(v):return v['event_errno']==0 and v['instructions']>0 and v['enabled']==v['running'] and v['running']>0

def argspec(a):
    opts={}
    for i,x in enumerate(a):
        if x=='-C':opt=a[i+1]
        elif x.startswith('-C') and len(x)>2:opt=x[2:]
        else:continue
        k,_,v=opt.partition('=');opts[k]=v
    opt=opts.get('opt-level','0');debug=opts.get('debug-assertions','on' if opt=='0' else 'off');overflow=opts.get('overflow-checks',debug)
    return {'opt':opt,'debug':debug,'overflow':overflow,'tokens':[x for x in ('opt-level','debug-assertions','overflow-checks','panic') if x in opts],'options':{k:opts[k] for k in ('opt-level','debug-assertions','overflow-checks','panic') if k in opts}}

def actual(d):
    rows=m.argv(d);ret={'compilers':[],'links':[],'generators':[],'selected':{}};rust_id=[rust.stat().st_dev,rust.stat().st_ino];wild_id=[wild.stat().st_dev,wild.stat().st_ino];cargo_id=[cargo.stat().st_dev,cargo.stat().st_ino];assert len([r for r in rows if r[1]==cargo_id and r[4][1:]==m.cmd[2:]])==1
    for pid,ident,ignored,image,a in rows:
        if ident==rust_id and '--crate-name' in a and '--out-dir' in a and not any(v.startswith('--print') for v in a):
            n=a[a.index('--crate-name')+1];out=a[a.index('--out-dir')+1];emit=next(x for x in a if x.startswith('--emit='));ret['compilers'].append([n,pid,emit,'link-only' if any(v in ('-Zlink-only','link-only') for v in a) else 'full']);source=next((x for x in a if x.endswith('.rs') and ('/src/' in x or x.endswith('/build.rs'))),None)
            if n in ('phf_generator','unicode_names2_generator','unicode_names2','ty_project') or source=='crates/ruff_unicode_names2/build.rs':ret['selected'].setdefault('unicode_build_script' if source=='crates/ruff_unicode_names2/build.rs' else n,[]).append({'source':source,'flags':argspec(a),'pid':pid,'out':out,'argv':a})
        if ident==wild_id and '-o' in a:ret['links'].append([pid,a[a.index('-o')+1]])
        if 'ruff_unicode_names2' in image and Path(image).name in ('build_script_build','build-script-build'):ret['generators'].append([pid,image])
    return ret

def visit(role,label,env,mode,expected=0):
    m.w.room(R,15);where=O/('opt'+role)/label;where.mkdir(parents=True)
    if mode=='score':cmd=[R/'watch',where/'whole.json',*m.cmd]
    elif mode=='trace':
        d=where/'kernel';d.mkdir();cmd=[R/'capture',d,'/usr/bin/false','cal',*m.cmd]
    else:cmd=m.cmd
    proc=subprocess.run(cmd,cwd=src,env=env,capture_output=True,timeout=1800);m.gz(where/'stdout.gz',proc.stdout);m.gz(where/'stderr.gz',proc.stderr)
    print(order,role,label,mode,'exit',proc.returncode,flush=True);assert proc.returncode==expected,(label,proc.returncode,proc.stderr[-1600:],proc.stdout[-1000:])
    raw=[json.loads(l) for l in proc.stdout.splitlines()];assert raw[-1]=={'reason':'build-finished','success':not bool(expected)}
    msgs=[x['message'] for x in raw if x['reason']=='compiler-message'];errs=[v for v in msgs if v['level']=='error'];assert bool(errs)==bool(expected)
    if expected:
        matched=[e for e in errs if e.get('code') and e['code']['code']=='E0308' and any(s['is_primary'] and s['file_name']=='crates/ty_project/src/lib.rs' and any('OHM_HOST_PROFILE_BAD_TYPE' in line['text'] for line in s['text']) for s in e['spans'])];assert len(matched)==1,(label,[(e['message'],e.get('code')) for e in errs]);assert len(errs)==1
    arts=[x for x in raw if x['reason']=='compiler-artifact'];names=sorted(set(json.dumps([a['package_id'],a['target']['name'],a['target']['kind'],a['features'],a['profile']['test']],separators=(',',':')) for a in arts));assert not any(x.get('executable') for x in arts)
    gen,=[Path(x['out_dir']) for x in raw if x['reason']=='build-script-executed' and '/crates/ruff_unicode_names2#' in x['package_id']];assert gen.is_relative_to(S) and sorted(p.name for p in gen.glob('*.rs'))==generated_names
    meta,=[Path(f) for a in arts if a['target']['name']=='unicode_names2' and a['target']['kind']==['lib'] for f in a['filenames'] if f.endswith('.rmeta')]
    g={n:m.sha(gen/n) for n in generated_names};obj=O/'generated';obj.mkdir(exist_ok=True)
    for n,h in g.items():
        if not (obj/(h+'.gz')).exists():m.gz(obj/(h+'.gz'),(gen/n).read_bytes())
    m.gz(where/'logical.gz',json.dumps(names,separators=(',',':')).encode());record={'arm':role,'phase':label,'method':mode,'source':m.sha(src/m.changed),'error_source':m.sha(consumer),'exit':proc.returncode,'typed':len(arts),'logical':len(names),'logical_sha':m.h(json.dumps(names,separators=(',',':')).encode()),'dirty':[a['target']['name'] for a in arts if not a['fresh']],'generated':g,'metadata':m.sha(meta),'errors':errs,'warning_sha':sorted(m.h(json.dumps(v,sort_keys=True).encode()) for v in msgs if v['level']=='warning')}
    if mode=='trace':record['kernel']=actual(d)
    if mode=='score':
        v=m.read(where/'whole.json');assert hw(v) and v['code']==expected;record['instructions']=v['instructions'];record['storage']=storage(where)
    m.save(where/'visit.json',record);return record

def flag_probes(arm,env,trace):
    cs=trace['kernel'];selected=cs['selected'];assert {'unicode_build_script','phf_generator','unicode_names2_generator','unicode_names2','ty_project'}<=selected.keys(),selected.keys()
    assert len(cs['generators'])==1 and any(output==cs['generators'][0][1] for _,output in cs['links']),(cs['generators'],cs['links'])
    probes={};d=R/('flags-'+arm);d.mkdir();code=d/'reader.rs'
    code.write_text('fn main() { std::panic::set_hook(Box::new(|_| {})); let n=std::hint::black_box(255u8); println!("{} {} {}", cfg!(debug_assertions), std::panic::catch_unwind(|| debug_assert!(std::hint::black_box(false))).is_err(), std::panic::catch_unwind(|| n + std::hint::black_box(1)).is_err()); }\n')
    for name,runs in selected.items():
        for row in runs:
            info=row['flags'];assert info['opt']==('1' if name in ('ty_project','unicode_names2') else arm) and info['debug']=='on' and info['overflow']=='on',(arm,name,info)
            opts=tuple((k,v) for k,v in sorted(info['options'].items()));key=json.dumps(opts)
            if key in probes:continue
            target=d/('out-'+str(len(probes)));argv=['rustc','+ohm','--edition=2024',code,'-o',target,*[i for k,v in opts for i in ('-C',k+'='+v)]];m.run(argv,env=env);p=m.get([target],env=env);assert p==b'true true true\n';probes[key]=[list(map(str,argv)),p.decode(),m.sha(target)]
    m.save(O/('opt'+arm)/'flag-probes.json',probes)

def main():
    env=procure();base=consumer.read_bytes();assert base==m.w.git(src,'show','HEAD:crates/ty_project/src/lib.rs');states={}
    for arm in order:
        selected=env_for(env,arm);other=env_for(env,'1' if arm=='0' else '0');edited(False);clear()
        graphcmd=[*m.cmd[0:-1],'--unit-graph','-Zunstable-options'];graph=m.get(graphcmd,cwd=src,env=selected);(O/('opt'+arm)).mkdir();m.gz(O/('opt'+arm)/'unit-graph.json.gz',graph);assert json.loads(graph)['roots']
        cold=visit(arm,'cold',selected,'score');edited(True);edit=visit(arm,'historical-edit',selected,'score');first=visit(arm,'first-unchanged',selected,'score');second=visit(arm,'repeat2',selected,'score');third=visit(arm,'repeat3',selected,'score')
        trace=visit(arm,'traced-unchanged',selected,'trace');assert trace['kernel']['links'] and trace['kernel']['generators']
        migrant=visit(arm,'switch-profile',other,'score');settled=visit(arm,'switch-unchanged',other,'score')
        assert cold['source']!=edit['source'] and all(v['source']==edit['source'] for v in (first,second,third,trace,migrant,settled)) and 'ty_project' in edit['dirty']
        clear();reference=visit(arm,'empty-edited',selected,'trace');flag_probes(arm,selected,reference)
        consumer.write_bytes(base+BAD);bad=visit(arm,'warm-invalid',selected,'ordinary',101);consumer.write_bytes(base);rep=visit(arm,'warm-repair',selected,'ordinary');assert not rep['errors']
        clear();consumer.write_bytes(base+BAD);bad0=visit(arm,'empty-invalid',selected,'ordinary',101);consumer.write_bytes(base);rep0=visit(arm,'empty-repair',selected,'ordinary');assert bad['errors']==bad0['errors'] and not rep0['errors']
        refs=[cold,edit,first,second,third,trace,reference,rep,rep0];assert all(r['generated']==first['generated'] for r in [*refs,bad,bad0,migrant,settled]);assert all(r['logical_sha']==first['logical_sha'] for r in refs);assert all(r['warning_sha']==first['warning_sha'] for r in refs)
        states[arm]={'neutral_generated':first['generated'],'roster':first['logical_sha'],'warnings':first['warning_sha'],'diag':bad['errors'],'cold':cold['instructions'],'first':first['instructions'],'migration':migrant['instructions'],'typed':first['typed']};clear()
    assert states['0']['neutral_generated']==states['1']['neutral_generated'] and states['0']['roster']==states['1']['roster'] and states['0']['warnings']==states['1']['warnings'] and states['0']['diag']==states['1']['diag']
    if order=='01':
        from provider import check
        check(m,load,NATIVE,env,env_for,wild)
    assert consumer.read_bytes()==base and not wild.with_name('libutil.so').exists();m.save(O/'complete.json',{'order':order,'states':states});print('qualified',order,flush=True)
if __name__=='__main__':main()
