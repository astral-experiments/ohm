"""Revisit the same Ruff metadata through a normal separately selected, previously built consumer."""
from pathlib import Path
import collections
import hashlib
import json
import os
import shutil
import subprocess as sp
import sys

HERE=Path(__file__).resolve().parent
legacy=Path(os.environ['GITHUB_WORKSPACE'])/'legacy/scripts/ruff-clap-config-help'
sys.path.insert(0,str(legacy));sys.path.insert(0,str(legacy/'evidence-release-24'))
import common as b
import scope_rdr as md
import re

b.OLD='03f787e51e94999977b9a5a32b0153d82d7e2142';b.NEW='fa4a7bca2db70229710892c97b26ea6fb046cfc4'
b.SRCS={b.OLD:'09af3d91c8734ba18e61d7db1b122695bf0327ec14c1aaa40ecda26d1ca59d54',b.NEW:'9aadd1de37c76267ce65f9cf022a89f1b443a6a57aa484489968d0cd76d4d726'}
b.LOCK='4f1629d6337b4e24b94810bc031f0f68ddb120152726ac1f2c558ecdee46bf4c'
OUT=Path(os.environ['RUNNER_TEMP'])/'reverse-metadata-raw'
DRIVER='b13243dc392a808cce88cb68486614d04bc00e0a6dc9fdf7a7f13b8335476f01'
pub=json.loads((HERE/'published.json').read_bytes());ver=pub['linux_sdk']['rustc'].splitlines()[0].split(' (ohm-',1)[0]+' (Ohm metadata 3)'
schema=legacy/'evidence-release-24/schema';S=schema/'compiler/rustc_span/src/symbol.rs';T=schema/'compiler/rustc_metadata/src/rmeta/mod.rs'
if not S.is_file():
    S=schema/'symbol.rs';T=schema/'rmeta.rs'
def run(cmd,**kwargs):return sp.run(cmd,check=True,**kwargs)
def read(p):return json.loads(p.read_bytes())
def H(b):return hashlib.sha256(b).hexdigest()
def getbin(path,dest):
    with dest.open('xb')as f:run(['gh','api','--header','Accept: application/octet-stream','repos/astral-experiments/ohm/'+path],stdout=f)
def install():
    b.ROOT.mkdir();OUT.mkdir();b.SDKBASE.mkdir();b.guard()
    before=sp.check_output(['git','-C',legacy,'rev-parse','HEAD'],text=True).strip();b.need(before=='e48abf3b09f415b296d0ee2e8ec81c0de7b50611','wrong signed custody')
    release=json.loads(sp.check_output(['gh','api','repos/astral-experiments/ohm/releases/tags/ohm-1.99.0-24']));assets={v['name']:v for v in release['assets']};packed=b.SDKBASE/'packed';packed.mkdir()
    files={};outprov=None
    for n,item in pub['assets'].items():
        if 'x86_64'in n:
            m=assets[n];b.need(m['id']==item['id']and m['digest']==item['sha256']and m['size']==item['bytes'],'unbound release asset')
            target=packed/n;getbin('releases/assets/'+str(m['id']),target);b.need(target.stat().st_size==m['size']and 'sha256:'+b.hf(target)==m['digest'],'changed Linux release')
            files[n]={'bytes':m['size'],'sha256':b.hf(target)}
            if n.endswith('provenance.json'):outprov=read(target)
    expected=read(legacy/'intake.json');b.need(outprov is not None and outprov['coordinator']['revision']==expected['head']==pub['tag_commit'],'unbound signed coordinator')
    n,=[k for k in files if k.endswith('provenance.json')];(packed/(n+'.sha256')).write_text(files[n]['sha256']+'  '+n+'\n');b.need(all(files[n]['sha256']==r['sha256']for n,r in expected['files'].items()if n in files),'signed files differ from source intake')
    inp={'files':files,'head':expected['head']};b.put(b.SDKBASE/'intake.json',inp);shutil.copyfile(legacy/'extract.py',b.SDKBASE/'extract.py');run([sys.executable,'-IB',b.SDKBASE/'extract.py'])
    actual=read(b.SDKBASE/'compiler.json');reference=read(legacy/'compiler.json');b.need(actual['members']==reference['members']and actual['tar_sha256']==reference['tar_sha256']==pub['linux_archive_sha256'],'different materialized compiler')
    driver,=(b.SDK/'lib').glob('librustc_driver-*.so');b.need(b.hf(driver)==DRIVER,'wrong signed driver')
    for n in ('rustc','cargo'):b.need(sp.check_output([n,'+ohm','-vV'],env=b.env(),text=True)==pub['linux_sdk'][n],n)
    run(['cc','-O2','-pthread','-Wall','-Wextra','-Werror',legacy/'exec_count.c','-o',b.ROOT/'exec_count'])
    run(['cc','-O2','-shared','-fPIC',HERE/'observe.c','-ldl','-o',b.ROOT/'observe.so'])
    b.put(OUT/'registration.json',{'release':pub['release'],'source':[b.OLD,b.NEW],'actual_driver':b.hf(driver),'sdk':actual['tar_sha256'],'provenance':outprov,'observer':b.hf(b.ROOT/'observe.so'),'invalid':'const _: u8 = "owner_cgu_invalid";','linux_boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
def unit_graph(args):
    return json.loads(sp.check_output(['cargo','+ohm','build','--unit-graph','-Zunstable-options',*args],env=b.env(),cwd=b.WORK))
def unit_closure(g):
    units=g['units'];memo={}
    def visit(i):
        if i not in memo:
            u=units[i];attrs={k:v for k,v in u.items()if k!='dependencies'}
            deps=sorted((json.dumps({k:v for k,v in e.items()if k!='index'},sort_keys=True),visit(e['index']))for e in u['dependencies'])
            memo[i]=H(json.dumps([attrs,deps],sort_keys=True,separators=(',',':')).encode())
        return memo[i]
    hits=[i for i,v in enumerate(units)if v['target']['name']=='ruff'and v['target']['kind']==['lib']and v['mode']=='build']
    b.need(len(hits)==1,'ambiguous actual Ruff unit');return visit(hits[0]),[units[i]['target']['name']for i in g['roots']]
def commands():
    tested=[];chosen=[]
    for name,client,producers in [('ruff_dev',['-p','ruff_dev','--bin','ruff_dev'],[['-p','ruff','-p','ruff_dev','--lib'],['-p','ruff','--lib','--features','ruff_linter/schemars'],['-p','ruff','--lib']]),('ruff',['-p','ruff','--bin','ruff'],[['-p','ruff','--lib']])]:
        full=unit_closure(unit_graph(client))
        for producer in producers:
            try:short=unit_closure(unit_graph(producer))
            except (ValueError,sp.CalledProcessError) as e:tested.append({'try':producer,'refused':str(e)[:400]});continue
            tested.append({'client':client,'producer':producer,'full':full,'short':short})
            if full[0]==short[0]and short[1]==['ruff']:
                chosen.append((name,client,producer));break
    b.need(any(t[0]=='ruff'for t in chosen),'original Ruff producer does not match the real binary')
    b.put(OUT/'unit-graph.json',{'explored':tested,'chosen':chosen});return sorted(chosen)
def epochs(path):
    rows=[]
    for l in (path/'epochs.tsv').read_bytes().splitlines():
        f=l.split()
        if f[0]!=b'I' or f[5]!=b'exec':continue
        raw=(path/f'{int(f[1]):05}.nul').read_bytes().split(b'\0');b.need(raw.pop()==b'' and int(raw[0])==int(f[2]),'wrong actual process image')
        s=(b.SDK/'bin/rustc').stat();identity=list(map(int,raw[1:3]));a=list(map(os.fsdecode,raw[4:]));name=b.crate_arg(a,'--crate-name')
        if identity==[s.st_dev,s.st_ino]and name:rows.append({'crate':name,'kind':b.crate_arg(a,'--crate-type'),'argv':a,'pid':int(f[2])})
    return rows
def command(dst,args,observer=False,expected=0):
    dst.mkdir();kd=dst/'kernel';kd.mkdir();env=b.env()
    if observer:env.update(LD_PRELOAD=str(b.ROOT/'observe.so'),OHM_GRAPH_RUSTC=str(b.SDK/'bin/rustc'),OHM_GRAPH_DIR=str(dst))
    with (dst/'stdout').open('xb')as out,(dst/'stderr').open('xb')as err:p=sp.run([b.ROOT/'exec_count',kd,'cargo','+ohm','build',*args],env=env,cwd=b.WORK,stdout=out,stderr=err)
    b.need(p.returncode==expected,(dst.name,p.returncode,(dst/'stderr').read_text()[-800:]));rows=epochs(kd);b.put(dst/'real-compiler.json',rows);return rows
def deps(a):
    return [a[i+1] if v=='--extern' else v.removeprefix('--extern=') for i,v in enumerate(a[:-1])if v=='--extern' or v.startswith('--extern=')]
def selected(rows,consumer):
    who,=[r for r in rows if r['crate']==consumer and r['kind']=='bin'];ls=[Path(v.split('=',1)[1]) for v in deps(who['argv']) if v.split('=',1)[0].split(':')[-1]=='ruff']
    b.need(len({p.suffix for p in ls})==len(ls)and any(p.suffix=='.rlib'for p in ls),'missing physical selected Ruff')
    archive,=[p for p in ls if p.suffix=='.rlib'];m=[p for p in ls if p.suffix=='.rmeta'];meta=m[0] if m else archive.with_suffix('.rmeta')
    if not meta.is_file():
        matches=sorted({p.resolve() for d in (b.TARGET,b.BUILD) for p in d.rglob(meta.name)if p.is_file()});b.need(len(matches)==1,'ambiguous standalone --extern sibling');meta=matches[0]
    b.need(meta.is_file()and archive.is_file(),'invalid selected raw metadata')
    search=[who['argv'][i+1]for i,x in enumerate(who['argv'][:-1])if x=='-L'and who['argv'][i+1].startswith('dependency=')]
    b.need(search,'missing actual external search roots');return archive,meta,search
def field_probes(dst,meta,search,new):
    for field,typ,success in [('stable','CheckCommand',True),('changed','FormatCommand',new)]:
        src=dst/(field+'.rs');src.write_text(f'pub fn field(x:&ruff::args::{typ})->bool{{x.extend_exclude.is_some()}}\n')
        out=b.ROOT/(field+'.rmeta');args=['rustc','+ohm','--edition=2024','--crate-name','public_field','--crate-type=lib','--emit=metadata','--extern','ruff='+str(meta),*[y for s in search for y in ('-L',s)],str(src),'-o',out]
        p=sp.run(args,cwd=b.WORK,env=b.env(),capture_output=True);(dst/(field+'.stderr')).write_bytes(p.stderr)
        b.need((p.returncode==0)==success and (success or(b'E0609'in p.stderr and b'extend_exclude'in p.stderr)),(field,new,p.stderr[-600:]));b.put(dst/(field+'.json'),{'status':p.returncode,'selected_rmeta':b.hf(meta),'source':src.read_text()})
def snapshot(dst,files,new):
    archive,meta,search=files;base=OUT/'metadata';base.mkdir(exist_ok=True);b.put(dst/'selected.json',{'meta':str(meta),'meta_sha':b.zsave(meta,base),'bytes':meta.stat().st_size,'rlib':str(archive),'rlib_sha':b.hf(archive)})
    field_probes(dst,meta,search,new)
    import member_names
    ledger=member_names.read_names(archive,'ruff');b.put(dst/'archive-inventory.json',ledger)
def verdict(dst,name):
    cmd=b.TARGET/'debug'/name
    e=b.env()|{'NO_COLOR':'1','COLUMNS':'240','LC_ALL':'C','TERM':'dumb','RUFF_NO_CACHE':'true'}
    tails=[['--help'],['repeat','--help']if name=='ruff_dev' else['format','--help']]
    val={}
    for i,args in enumerate(tails):
        p=sp.run([cmd,*args],env=e,cwd=b.WORK,capture_output=True);b.need(p.returncode==0 and b'--help'in p.stdout and not p.stderr,'bad real unchanged consumer verdict');(dst/f'help-{i}.stdout').write_bytes(p.stdout);val[str(i)]=H(p.stdout)
    result={'path':str(cmd),'sha256':b.hf(cmd),'bytes':cmd.stat().st_size,'help':val};b.put(dst/'native.json',result);return result
def footprint(dst):
    m={}
    for root in (b.TARGET,b.BUILD):
        for d in (p for fd in root.rglob('.fingerprint') for p in fd.glob('ruff*')):
            if not d.is_dir()or not re.fullmatch(r'ruff(?:_dev)?-[a-f0-9]{16}',d.name):continue
            for p in d.iterdir():
                if p.is_file()and p.stat().st_size<2**20:
                    m[root.name+'/'+str(p.relative_to(root))]=[p.stat().st_size,p.stat().st_mtime_ns,b.hf(p)]
                    target=dst/'cargo-fingerprint'/root.name/p.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    b.put(dst/'cargo-fingerprints.json',m)
def try_schema():
    paths=list((legacy/'evidence-release-24/schema').rglob('*.rs'));s,=[x for x in paths if b.hf(x)=='b432282257901159c6e2758caa570feb305f01c82b1fa67a19cf6616c6ed1b0d'];t,=[x for x in paths if b.hf(x)=='939927ea4e04ceeae1cbd63a7be80a91d213f594dafdce596ac0e7815ce8ca2c']
    sy=md.decode_symbols(s.read_text());names=re.findall(r'^    (\w+): Table<',t.read_text().split('define_tables! {',1)[1].split('\n}',1)[0],re.M);b.need(len(sy)==2314 and len(names)==88,'wrong schema');return sy,names
def rows_at(dst,sy,tabs):
    m=read(dst/'selected.json');raw=sp.check_output(['zstd','-qdc',OUT/'metadata'/(m['meta_sha']+'.zst')]);b.need(H(raw)==m['meta_sha']and len(raw)==m['bytes'],'wrong deposited physical rmeta');return md.decode(raw,sy,tabs,'ruff',ver)
def run_lane(lane,consumer,client,prod,observe):
    folder=OUT/lane;folder.mkdir();b.select(b.OLD);b.prepare();old=folder/'initial-consumer';r=command(old,client,observe);files=selected(r,consumer);snapshot(old,files,False);orig=verdict(old,consumer);footprint(old)
    no=folder/'settled-original';assert not command(no,client);assert verdict(no,consumer)==orig
    b.select(b.NEW);d=folder/'producer-NEW';r=command(d,prod,observe);b.need(any(x['crate']=='ruff'and x['kind']in('lib','rlib')for x in r)and not any(x['kind']=='bin'and x['crate']==consumer for x in r),'wrong changed producer roster');snapshot(d,files,True)
    saved=b.SRC.read_bytes()
    try:
        b.SRC.write_bytes(saved+b'\nconst _: u8 = "owner_cgu_invalid";\n')
        for label in ('invalid','invalid-again'):
            p=folder/label;command(p,prod,expected=101);b.need(b'error[E0308]'in(p/'stderr').read_bytes(),'false usable source')
    finally:b.SRC.write_bytes(saved)
    d=folder/'producer-REPAIR';command(d,prod,observe);snapshot(d,files,True)
    b.select(b.OLD);back=folder/'producer-OLD';r=command(back,prod,observe);b.need(not any(x['kind']=='bin'and x['crate']==consumer for x in r),'consumer executed before its actual witness');snapshot(back,files,False);footprint(back)
    w=folder/'unchanged-consumer';rows=command(w,client);snap=verdict(w,consumer);footprint(w);snapshot(w,files,False)
    again=folder/'settled-after';assert not command(again,client);assert verdict(again,consumer)==snap
    sy,tabs=try_schema();a=rows_at(old,sy,tabs);bb=rows_at(back,sy,tabs)
    changed={k:{'identity':a[1].get(k,bb[1].get(k)),'before':a[2].get(k),'after':bb[2].get(k)}for k in a[2].keys()|bb[2].keys()if a[2].get(k)!=bb[2].get(k)}
    substitutions=collections.Counter((v['before'],v['after'])for v in changed.values())
    b.put(folder/'changed-public-rows.json',changed)
    summary={'driver':DRIVER,'consumer':consumer,'consumer_source_unchanged':True,'initial_native':orig,'final_native':snap,'downstream_actual':[(v['crate'],v['kind'])for v in rows],'publication':[a[0],bb[0]],'definitions':[len(a[1]),len(bb[1]),a[1]==bb[1]],'changed_public_rows':len(changed),'substitutions':substitutions.most_common(10),'total_public_rows':[len(a[2]),len(bb[2])],'expansions':[len(a[3]),len(bb[3])],'expansions_equal':a[3]==bb[3],'required_crates':[len(a[4]),len(bb[4])],'required_crates_equal':a[4]==bb[4]}
    b.put(folder/'summary.json',summary);return summary
def main():
    b.need(os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']and os.environ['GITHUB_RUN_ATTEMPT']=='1'and os.environ['GITHUB_REF_NAME']=='charlie/qa-ruff-clap-reverse-metadata-20261103','unregistered run')
    install();b.select(b.OLD);b.prepare();choices=commands()
    def clear():
        for p in (b.TARGET,b.HOME,b.BUILD):
            if p.exists():b.need(p.parent==b.ROOT and p.is_dir()and not p.is_symlink(),'unknown private root');shutil.rmtree(p)
    trials={}
    for target,client,producer in choices:
        clear();trials[target]=run_lane('normal-'+target,target,client,producer,False);b.put(OUT/'ordinary-admission.json',trials)
    for target,client,producer in choices:
        normal=trials[target]
        if not normal['changed_public_rows']:continue
        clear();observed=run_lane('observed-'+target,target,client,producer,True)
        b.need(observed['changed_public_rows']==normal['changed_public_rows'] and observed['downstream_actual']==normal['downstream_actual'] and observed['initial_native']['help']==normal['initial_native']['help'] and observed['final_native']['help']==normal['final_native']['help'],'physical graph recorder changed the normal outcome')
        b.put(OUT/'observed-admission.json',{'normal':normal,'observed':observed});break
if __name__=='__main__':main()
