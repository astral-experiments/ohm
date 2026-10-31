"""Externally scoped package override, matched ordinary Ruff checks and unopened native reread."""
from pathlib import Path
import collections,gzip,hashlib,json,os,re,shutil,subprocess,sys
H=Path(__file__).resolve().parent;root=Path(os.environ['GITHUB_WORKSPACE']);row=os.environ['QA_ROW'];enrollment=json.loads((H/'order.json').read_bytes());order,direction=enrollment[row];os.environ['QA_ORDER']=order
broad=root/'broad';assert subprocess.check_output(['git','-C',broad,'rev-parse','HEAD']).decode().strip()=='5d26c524606e556b4934842568ed4acd2e91219d'
sys.path[:0]=[str(H),str(broad/'scripts/strict-host-opt')];import study as b
m=b.m;CARGO=b.cargo;R=m.R;S=m.S;O=m.O;src=m.src;genname='ruff_unicode_names2_generator';cfg=b'[profile.dev.package.ruff_unicode_names2_generator]\nopt-level = 1\n'

def select(env,arm):
    path=Path(env['CARGO_HOME'])/'config.toml';assert path.parent==S/'cargo-home' and not (path.parent/'config').exists() and not path.is_symlink()
    if path.exists():assert path.read_bytes()==cfg
    if arm=='0':path.unlink(missing_ok=True)
    elif arm=='1' and not path.exists():
        tmp=path.with_name('incoming-one-crate-config');assert not tmp.exists();tmp.write_bytes(cfg);tmp.replace(path)
    else:assert arm=='1'
    assert (path.read_bytes() if path.exists() else None)==(cfg if arm=='1' else None) and b.OVERRIDE not in env
    return env

def keep_elf(path,group):
    data=path.read_bytes();c=m.h(data);assert data[:4]==b'\x7fELF' and c==m.sha(path);d=O/'retained-ELF';d.mkdir(exist_ok=True);p=d/(c+'.gz')
    if not p.exists():m.gz(p,data)
    return {'path':str(path),'sha256':c,'bytes':len(data),'dev_ino':[path.stat().st_dev,path.stat().st_ino],'group':group}

def stdout(where):return [json.loads(x) for x in gzip.decompress((where/'stdout.gz').read_bytes()).splitlines()]

def generator(where,group):
    arts=[a for a in stdout(where) if a['reason']=='compiler-artifact' and a['target']['kind']==['custom-build'] and '/crates/ruff_unicode_names2#' in a['package_id']]
    a,=arts;p,=[Path(f) for f in a['filenames'] if Path(f).name in ('build_script_build','build-script-build')];obj=keep_elf(p,group);m.save(where/'neutral-generator.json',obj);return obj

def kernel(where,arm,phase):
    rows=m.argv(where/'kernel');rstat=b.rust.stat();wstat=b.wild.stat();rid=[rstat.st_dev,rstat.st_ino];wid=[wstat.st_dev,wstat.st_ino];compilers=[];linkers=[];gens=[]
    for pid,ino,matches,f,a in rows:
        if ino==rid and '--crate-name' in a and '--out-dir' in a and not any(t.startswith('--print') for t in a):
            crate=a[a.index('--crate-name')+1];source=next((x for x in a if x.endswith('.rs') and not x.startswith('-')),None)
            if source is None:
                assert re.fullmatch('autocfg_[0-9a-f]{16}_0',crate) and '-' in a and '--emit=llvm-ir' in a and '/memoffset/' in a[a.index('--out-dir')+1],a
                source='<exclusive memoffset autocfg stdin probe>'
            emit=next(x for x in a if x.startswith('--emit='));spec=b.argspec(a);required='1' if crate=='unicode_names2_generator' and arm=='1' else None
            if required:assert spec['opt']==required,(crate,spec)
            flags=sorted(a[i+1] for i,x in enumerate(a) if x=='--cfg' and a[i+1].startswith('feature='));mode='link-only' if any(v in ('-Zlink-only','link-only') for v in a) else 'full';compilers.append([crate,source,emit,flags,mode,spec['opt'],spec['debug'],spec['overflow'],pid]);
        if ino==wid and '-o' in a:linkers.append([pid,a[a.index('-o')+1]])
        if 'ruff_unicode_names2' in f and Path(f).name in ('build_script_build','build-script-build'):gens.append([pid,f]);
    assert len(gens)==1 and len([r for r in linkers if r[1]==gens[0][1]])==1,(phase,gens,linkers)
    evidence={'requested_arm':arm,'phase':phase,'compilers':compilers,'links':linkers,'generators':gens};m.save(where/'all-physical.json',evidence);return evidence

def graph(env,arm):
    data=m.get([*m.cmd[:-1],'--unit-graph','-Zunstable-options'],cwd=src,env=env);d=O/('opt'+arm);d.mkdir();m.gz(d/'unit-graph.json.gz',data);units=json.loads(data)['units'];out={}
    for u in units:
        key=json.dumps([u['pkg_id'],u['target']['name'],u['target']['kind'],u['mode'],u['features'],u.get('platform')],sort_keys=True,separators=(',',':'));out.setdefault(key,[]).append(u['profile'])
    for l in out.values():l.sort(key=lambda p:json.dumps(p,sort_keys=True))
    return out

def flags(arm,env,r):
    sels=r['kernel']['selected'];assert set(sels)=={'phf_generator','unicode_names2_generator','unicode_build_script','unicode_names2','ty_project'}
    d=R/('single-flags-'+arm);d.mkdir();s=d/'probe.rs';s.write_text('fn main(){ std::panic::set_hook(Box::new(|_|{})); let v=std::hint::black_box(255u8); println!("{} {} {}", cfg!(debug_assertions),std::panic::catch_unwind(|| debug_assert!(std::hint::black_box(false))).is_err(), std::panic::catch_unwind(|| v+std::hint::black_box(1)).is_err());}\n');out={}
    for name,values in sels.items():
        for v in values:
            f=v['flags'];assert f['opt']==('1' if name in ('ty_project','unicode_names2') else arm if name=='unicode_names2_generator' else '0') and f['debug']==f['overflow']=='on',(name,f)
            ops=sorted(f['options'].items());key=json.dumps(ops);dest=d/('out-'+str(len(out)))
            if key not in out:
                a=['rustc','+ohm','--edition=2024',s,'-o',dest,*[q for k,val in ops for q in ('-C',k+'='+val)]];m.run(a,env=env);v=m.get([dest],env=env);assert v==b'true true true\n';out[key]={'argv':list(map(str,a)),'ran':v.decode(),'elf':m.sha(dest)}
    m.save(O/('opt'+arm)/'flag-probes.json',out)

def logical_compilers(r):
    classes=collections.defaultdict(list)
    for crate,source,emit,feats,mode,opt,debug,overflow,pid in r['compilers']:
        logical='autocfg_<memoffset-stdin>_0' if source=='<exclusive memoffset autocfg stdin probe>' else crate
        k=json.dumps([logical,source,emit,feats,mode],separators=(',',':'));classes[k].append([opt,debug,overflow])
    return {k:sorted(v) for k,v in classes.items()}

def main():
    env=b.procure();assert not (Path(env['CARGO_HOME'])/'config.toml').exists();reason=O/'single.json';m.save(reason,{'row':row,'order':order,'source_direction':direction,'host':os.uname().nodename,'commit':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'plan':m.sha(H/'PLAN.md'),'orders':enrollment,'override':cfg.decode(),'native':row in ('01','02')});base=b.consumer.read_bytes();assert base==m.w.git(src,'show','HEAD:crates/ty_project/src/lib.rs');G={};K={};summ={};identities={};diagnostics={};generated=None;rosters=set();warnings=[]
    before=direction=='forward';after=not before
    for arm in order:
        other='1' if arm=='0' else '0';b.clear();b.edited(before);select(env,arm);G[arm]=graph(env,arm);d=O/('opt'+arm);same=[];rows={}
        def run(label,mode='score',err=0,subject=None):
            nonlocal generated
            subject=subject or arm;select(env,subject);r=b.visit(arm,label,env,mode,err);rows[label]=r
            if err==0:rosters.add(r['logical_sha']);warnings.append(r['warning_sha'])
            if generated is None:generated=r['generated']
            assert r['generated']==generated
            if mode=='trace':kernel(d/label,subject,label)
            gen=generator(d/label,label)
            if subject==arm and not err:same.append(gen['sha256'])
            return r
        cold=run('cold');neutral=run('neutral-unchanged');b.edited(after);edit=run('historical-edit');first=run('first-unchanged');warm=run('traced-unchanged','trace');assert cold['source']==neutral['source'] and edit['source']==first['source']!=cold['source'] and 'ty_project' in edit['dirty']
        run('switch-profile',subject=other);run('switch-unchanged',subject=other)
        b.clear();ref=run('empty-edited','trace');flags(arm,env,ref);K[arm]=logical_compilers(m.read(d/'empty-edited/all-physical.json'))
        b.consumer.write_bytes(base+b.BAD);bad=run('warm-invalid','ordinary',101);b.consumer.write_bytes(base);run('warm-repair','ordinary');run('switch-physical','trace',subject=other)
        b.clear();b.consumer.write_bytes(base+b.BAD);emptybad=run('empty-invalid','ordinary',101);b.consumer.write_bytes(base);run('empty-repair','ordinary');assert bad['errors']==emptybad['errors'];diagnostics[arm]=bad['errors'];assert len(set(same))==1,(arm,same);identities[arm]=same[0];summ[arm]={k:[v['instructions'],v['storage']['allocated_B'],len(v['dirty'])] for k,v in rows.items() if 'instructions' in v};b.clear()
    assert len(rosters)==1 and diagnostics['1']==diagnostics['0'] and all(v==warnings[0] for v in warnings);assert G['0'].keys()==G['1'].keys() and K['0'].keys()==K['1'].keys();graph_changed={k:[G['0'][k],G['1'][k]] for k in G['0'] if G['0'][k]!=G['1'][k]};compiler_changed={k:[K['0'][k],K['1'][k]] for k in K['0'] if K['0'][k]!=K['1'][k]}
    assert len(graph_changed)==len(compiler_changed)==1 and all(genname in k for k in [*graph_changed,*compiler_changed]),(graph_changed,compiler_changed)
    for v0,v1 in graph_changed.values():assert len(v0)==len(v1)==1 and v0[0]|{'opt_level':'1'}==v1[0] and v0[0]['opt_level']=='0'
    assert list(compiler_changed.values())==[[[['0','on','on']],[['1','on','on']]]];m.save(O/'delta.json',{'graph':graph_changed,'compilers':compiler_changed,'neutral_ELFs':identities,'states':summ,'unchanged_generated':generated})
    if row in ('01','02'):
        import builds
        builds.study(b,env,select,keep_elf,direction,order)
        from provider import check
        check(m,b.load,b.NATIVE,env,select,b.wild)
    select(env,'0');assert not b.wild.with_name('libutil.so').exists() and b.consumer.read_bytes()==base;b.edited(False);m.save(O/'complete.json',{'row':row,'order':order,'direction':direction,'qualified':True});print('complete',row,flush=True)
if __name__=='__main__':main()
