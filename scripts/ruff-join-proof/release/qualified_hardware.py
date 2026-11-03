"""Unmodified Cargo check with version-specific native registry state and identical independently produced external compiler inputs."""
from pathlib import Path
import collections, gzip, hashlib, json, os, re, shutil, signal, subprocess, sys, time, tomllib, zipfile
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent.parent/'ruff-foreign-span-observer'),str(HERE.parent/'evidence/reader/upgrade')]
import worker as sdk
import bundle, counter_argv, external_prefix, locked_git
ORIGINAL='13217478384';BOOT_PLAN='45f061e7e3fc6e082ae3505e63c2d234c7370ded4377182391602f02f8e66cce'
READER_ONLY=os.environ.get('OHM_PRICE_READER_ONLY')=='1'
P_NAME='pre-reader' if READER_ONLY else 'release-parent'
ROOTS=('ruff_linter','ruff_graph','ruff_workspace','ty_python_semantic')
def check(c,why):
    if not c:raise ValueError(why)
def put(p,x):p.parent.mkdir(parents=True,exist_ok=True);sdk.put(p,x)
def encode(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
def h(x):return hashlib.sha256(x).hexdigest()
def command(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
def git(*argv):return subprocess.check_output(['git','-C',sdk.work,*argv],text=True).strip()
def compressed(p,x):p.write_bytes(gzip.compress(encode(x),compresslevel=3,mtime=0))
def admit():
    check(sdk.hf(HERE/'hardware-plan.json')==BOOT_PLAN,'changed original plan')
    p=json.loads((HERE/'hardware-plan.json').read_bytes());plan=json.loads((HERE/'plan.json').read_bytes());ids=p['sources']
    check(git('rev-parse','HEAD')==ids['Ruff_edit']and git('rev-parse','HEAD^')==ids['Ruff_old']and sdk.hf(sdk.work/'Cargo.lock')==ids['Ruff_lock']and not git('status','--porcelain'),'Ruff source or lock')
    check(sdk.hf(HERE/'whole_count.c')==p['counter_sha256']and sdk.hf(HERE/'counter_argv.py')==p['exec_boundary_source_sha256']and sdk.hf(HERE/'external_prefix.py')=='3893ab09b216967b53727b9faea7bcebd64fe610e808ddba8297c6873368ad75' and sdk.hf(HERE/'locked_git.py')=='4bf244c9d6010e0d35ee1f3da720a47c936a0c6c3dedf62ec5b7f0cda20d87e3','counter or registry receiver')
    if READER_ONLY:
        rp=json.loads((HERE/'reader-price-plan.json').read_bytes());check(rp['original_plan_sha256']==BOOT_PLAN and rp['order']==p['order'],'different marginal registration')
        check((rp['P'],rp['P_elf_sha256'])==bundle.SOURCES['pre-reader'] and (rp['C'],rp['C_elf_sha256'])==bundle.SOURCES['release-child'],'different marginal source')
        p['sources']['P']=rp['P'];p['marginal']=rp
    check(p['argv']==plan['primary']and p['order']==list('PCCP')and all(ids[k]==bundle.SOURCES[v][0]for k,v in [('P',P_NAME),('C','release-child')]),'Cargo command/source')
    return p,plan
def rcards(archive):
    api=['gh','api','repos/astral-experiments/ohm/actions/artifacts/'+ORIGINAL+'/zip']
    env={k:os.environ[k]for k in ('PATH','HOME')};env['GH_TOKEN']=os.environ['OHM_SDK_READ_TOKEN']
    with archive.open('xb')as f:command(api,stdout=f,env=env)
    bundle.admit(archive);bodies={}
    with zipfile.ZipFile(archive)as z:
        facts=json.loads(z.read('release-factories.json'));put(out/'cargo-source.json',facts)
        for role,n in [('P',P_NAME),('C','release-child')]:
            rev,sha=bundle.SOURCES[n];r=facts[n];d=trial/('cargo-'+role)
            with z.open('cargo-'+n)as a,d.open('xb')as b:shutil.copyfileobj(a,b)
            d.chmod(0o755);check(d.stat().st_size==r['bytes']and sdk.hf(d)==sha==r['sha256']and rev==r['cargo_source']and rev in subprocess.check_output([d,'-Vv'],text=True),'unregistered Cargo')
            bodies[role]=d
    return bodies

def execute(args,d,*,meter=False,bad=False,trace=True):
    sdk.guard();check(sdk.avail()>=9*2**30 and shutil.disk_usage(trial).free>=20*2**30,'start resource floor');d.mkdir(parents=True)
    cmd=counter_argv.command(counter,d/'hardware.json',args,env)if meter else args
    if trace:cmd=['strace','-ff','-qq','-s','8192','-e','trace=execve','-o',str(d/'exec'),'--',*cmd]
    started=time.monotonic();minimum=sdk.avail()
    with (d/'stdout').open('wb')as so,(d/'stderr').open('wb')as se:
        task=subprocess.Popen(cmd,cwd=sdk.work,env=env,stdout=so,stderr=se,start_new_session=True)
        while task.poll()is None:
            minimum=min(minimum,sdk.avail())
            if minimum<8*2**30 or shutil.disk_usage(trial).free<15*2**30 or time.monotonic()-started>1500:
                os.killpg(task.pid,signal.SIGKILL);task.wait();raise RuntimeError('resource or duration limit')
            time.sleep(.2)
    stderr=(d/'stderr').read_text();codes=sorted(set(re.findall(r'error\[(E\d{4})\]',stderr)))
    check(task.returncode==(101 if bad else 0)and codes==(['E0308']if bad else[]),(d.name,task.returncode,codes,stderr[-1500:]))
    owners={}
    for f in d.glob('exec.*'):
        for line in f.read_text().splitlines():
            m=re.search(r'^execve\("([^"]*/rustc)",.*?"--crate-name", "([^"]+)",',line)
            if m and line.endswith(' = 0'):
                pid=f.name.split('.')[-1];check(pid not in owners,'reused PID');owners[pid]=m[2]
    r=dict(argv=args,exit=task.returncode,error_codes=codes,cargo=sdk.hf(selected),source=git('rev-parse','HEAD'),minimum_available=minimum,rustcs=owners)
    if meter:
        hw=json.loads((d/'hardware.json').read_bytes());check(hw['status']==task.returncode<<8 and hw['instructions']>0 and hw['running']>0 and hw['enabled']<=1.01*hw['running'],'user counter gate');r['hardware']=hw
    put(d/'record.json',r);return r

def select(role):
    incoming=trial/'new-cargo';check(not incoming.exists(),'dangling selection handoff')
    if not selected.samefile(bodies[role]):
        os.link(bodies[role],incoming);os.replace(incoming,selected)
    check(not incoming.exists(),'incomplete Cargo selection')
    which=Path(subprocess.check_output(['rustup','which','--toolchain','ohm','cargo'],env=env,text=True).strip())
    check(which.samefile(selected)and selected.samefile(bodies[role])and frozen['sources'][role] in subprocess.check_output(['cargo','+ohm','-Vv'],env=env,text=True),'private Cargo selection')
def external_products(d):
    data={}
    def keep(k,f):
        check(f.is_file()and (f.resolve(strict=True).is_relative_to(state) or f.resolve(strict=True).is_relative_to(sdk.home/'registry/src')),'outside private product and locked source')
        v=[f.stat().st_size,sdk.hf(f)];check(data.setdefault(k,v)==v,'two bodies for one path')
    for x in external_prefix.events(d):
        pid=x.get('package_id','')
        if not locked_git.external(pid):continue
        if x['reason']=='compiler-artifact':
            for name in x['filenames']:
                f=Path(name);keep(pid+' '+str(f.relative_to(state)),f)
        elif x['reason']=='build-script-executed':
            leaf=Path(x['out_dir']);check(leaf.is_dir()and leaf.is_relative_to(state),'foreign build output')
            for f in leaf.rglob('*'):
                if not f.is_dir():keep(pid+' '+str(f.relative_to(state)),f)
    check(len(data)>300 and sum('get-size-derive2' in k and k.endswith('.so')for k in data)==1 and sum('get-size2' in k and k.endswith('.rmeta')for k in data)>=1,'missing true get-size products')
    return data

def fresh_state():
    check(state.parent==trial and state.name=='state' and not state.is_symlink(),'foreign state root')
    if state.exists():shutil.rmtree(state)
    state.mkdir()
def semantic(label):
    sig={}
    for n in ROOTS:
        matches=[q for q in state.rglob('lib'+n+'-*.rmeta')if q.is_file()];ds={sdk.hf(q)for q in matches};check(len(ds)==1,(n,ds))
        d=matches[0];root=subprocess.check_output(['rustc','+ohm',d,'-Zls=root'],env=env,text=True)
        (label/(n+'.root')).write_text(root);raw=ds.pop()
        if n=='ruff_linter':
            witness=out/'rmeta'/(raw+'.zst');witness.parent.mkdir(exist_ok=True)
            if not witness.exists():command(['zstd','-q','-3','-T1',d,'-o',witness])
        sig[n]={'sha256':raw,'bytes':d.stat().st_size,'public':re.search(r'public_hash (\w{32})',root)[1],'private':re.search(r'private hash (\w{32}) stable_crate_id',root)[1]}
    put(label/'metadata.json',sig);return sig
def public(x):return {k:v['public']for k,v in x.items()}
def altered(kind,src_bytes,old,new):
    check(changed.read_bytes()==src_bytes and src_bytes.count(old)==1,'private edit source')
    data=src_bytes.replace(old,new)if kind=='body'else src_bytes+b'\nfn ohm_selected_bad_width() -> u8 { false }\n'
    changed.write_bytes(data);return h(data)
def prep():
    global trial,out,frozen,plan,bodies,env,counter,selected,state,changed,primary
    sdk.guard();frozen,plan=admit();trial=sdk.root/'fixed-extern';trial.mkdir();out=sdk.proof/'fixed-extern';out.mkdir()
    put(out/'registration.json',{'frozen':frozen,'current':{f.name:sdk.hf(f)for f in HERE.iterdir()if f.is_file()},'archive':bundle.FULL_SHA,'external_enrollment':frozen['marginal']['admit']if READER_ONLY else 'At most four independently empty seeds per role, alternating P/C. Stop at first hash match of all named native/compiler products and generated files. Every seed and refusal recorded before reading any command counter. All observed output and fingerprint files stay in the private state written by the owner Cargo. The selected P/C use the identical compiler and external products throughout, with independent empty Ruff inputs; fully empty new witness remains a separate observation.','boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip()})
    bodies=rcards(trial/'signed-release-ctors.zip');e=sdk.install();box=trial/'sdk';(box/'bin').mkdir(parents=True)
    for f in sdk.sdk.iterdir():
        if f.name!='bin':(box/f.name).symlink_to(f)
    for f in (sdk.sdk/'bin').iterdir():
        if f.name!='cargo':(box/'bin'/f.name).symlink_to(f)
    selected=box/'bin/cargo';os.link(bodies['P'],selected)
    state=trial/'state';state.mkdir()
    env={**e,'RUSTUP_HOME':str(trial/'rustup'),'CARGO_TARGET_DIR':str(state/'target'),'CARGO_BUILD_BUILD_DIR':str(state/'build')}
    check(Path(env['CARGO_HOME'])==sdk.home and not any(env.get(k)for k in ('RUSTC','RUSTC_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','LD_PRELOAD','CARGO_LOG','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST')),'unexpected env')
    command(['rustup','toolchain','link','ohm',box],env=env)
    v=subprocess.check_output(['rustc','+ohm','-vV'],env=env,text=True);check(frozen['sources']['rustc']in v,'signed rustc')
    put(out/'rustc.json',{'version':v,'binary':sdk.hf(box/'bin/rustc'),'drivers':{f.name:sdk.hf(f)for f in(box/'lib').glob('librustc_driver*.so')}})
    counter=trial/'whole-count';command(['cc','-O2','-Wall','-Werror',HERE/'whole_count.c','-o',counter])
    ok,controls=counter_argv.calibrate(counter,trial,env);put(out/'calibration.json',controls);check(ok,'hardware calibration')
    primary=frozen['argv'];changed=sdk.work/plan['additional_private']['path']
    execute(['cargo','+ohm','fetch','--locked'],out/'all-registry-prefetch',trace=False)
def enroll():
    git('switch','--detach',frozen['sources']['Ruff_old']);check(not git('status','--porcelain'),'unmodified old')
    lock=tomllib.loads((sdk.work/'Cargo.lock').read_text());seen={'P':{},'C':{}};seeds=[]
    for j in range(8):
        role='PC'[j%2];dest=out/f'seed-{j}-{role}';select(role);fresh_state()
        execute([*primary,'--message-format=json'],dest,trace=False);pr=external_products(dest);key=h(encode(pr));compressed(dest/'external-products.json.gz',pr)
        pref=external_prefix.Prefix(state,sdk.work,sdk.home,dest/'registry-prefix',lock,{'check':dest})
        bank=trial/('bank-'+str(j));state.rename(bank)
        seeds.append({'id':j,'role':role,'external':len(pr),'commitment':key,'macro':pref.macro_sha});put(out/'seed-census.json',seeds);print('actual source-qualified seed',j,role,len(pr),key,flush=True)
        if key not in seen[role]:seen[role][key]=(bank,pref,pr)
        other='C'if role=='P'else'P'
        if seen[other]:
            compare=next(iter(seen[other].values()))[2]
            diff=sorted(k for k in compare.keys()|pr.keys()if compare.get(k)!=pr.get(k))
            put(dest/'prospective-first-opposite.json',{'different':diff,'count':len(diff)})
        if key in seen[other]:
            matches={r:seen[r][key]for r in ('P','C')};check(matches['P'][2]==matches['C'][2]and matches['P'][1].source_fixed==matches['C'][1].source_fixed and matches['P'][1].archives==matches['C'][1].archives,'independently selected native or registry input bytes differ')
            put(out/'selected.json',{'ids':{r:next(x['id']for x in seeds if x['role']==r and x['commitment']==key)for r in ('P','C')},'sha256':key,'bytes':sum(x[0]for x in pr.values()),'entries':len(pr)})
            for d in trial.glob('bank-*'):
                if d not in [v[0]for v in matches.values()]:shutil.rmtree(d)
            return matches
    raise ValueError('none of the preregistered fully native external-input seeds matched; no benchmark can begin')

def enrolled_conversion():
    git('switch','--detach',frozen['sources']['Ruff_old']);check(not git('status','--porcelain'),'dirty old')
    lock=tomllib.loads((sdk.work/'Cargo.lock').read_text());pairs={}
    for role in ('P','C'):
        dest=out/('bounded-seed-'+role);select(role)
        if role=='P':fresh_state()
        else:
            bank,pref,products=pairs['P'];check(not state.exists()and bank.parent==trial,'wrong source prefix')
            command(['cp','-a','--reflink=auto','--',bank,state])
            for rel,entry in pref.fixed.items():
                a,b=bank/rel,state/rel;one,two=a.lstat(),b.lstat()
                check((one.st_dev,one.st_ino)!=(two.st_dev,two.st_ino)and (one.st_mode,one.st_mtime_ns)==(two.st_mode,two.st_mtime_ns),'mutable alias or changed copy attributes')
                if entry[3]=='regular':check(sdk.hf(b)==entry[-1]and one.st_size==two.st_size,'copied external body changed')
                else:check(os.readlink(a)==os.readlink(b)==entry[-1],'copied external symlink changed')
        execute([*primary,'--message-format=json'],dest,trace=True)
        pr=external_products(dest);compressed(dest/'external-products.json.gz',pr)
        pf=external_prefix.Prefix(state,sdk.work,sdk.home,dest/'registry-prefix',lock,{'check':dest})
        bank=trial/('converted-'+role);state.rename(bank);pairs[role]=(bank,pf,pr)
        print('complete conversion seed',role,len(pr),h(encode(pr)),flush=True)
    pp=pairs['P'][2];cc=pairs['C'][2];diff=sorted(k for k in pp.keys()|cc.keys()if pp.get(k)!=cc.get(k))
    put(out/'conversion.json',dict(differences=diff,p=h(encode(pp)),c=h(encode(cc)),counts=[len(pp),len(cc)]))
    check(len(pp)==len(cc)==1322 and not diff and pairs['P'][1].source_fixed==pairs['C'][1].source_fixed and pairs['P'][1].archives==pairs['C'][1].archives,'actual conversion no longer has identical inputs; no price')
    put(out/'selected.json',dict(sha256=h(encode(pp)),entries=len(pp),bytes=sum(x[0]for x in pp.values()),history='fully genuine earlier Cargo then independently owned normal v4→v5 conversion'))
    return pairs

def assess(role,j,package):
    bank,pref,pr=package;label=out/f'pair-{j}-{role}';select(role);check(not state.exists(),'unexpected inherited workspace')
    bank.rename(state);pref.verify('pre-'+str(j));git('switch','--detach',frozen['sources']['Ruff_old']);check(not git('status','--porcelain'),'dirty old tree')
    rows={}
    def run(n,*,meter=False,bad=False,js=False):
        d=label/n;r=execute([*primary,*(['--message-format=json']if js else[])],d,meter=meter,bad=bad);rows[n]=r
        if not bad:r['metadata']=semantic(d)
        return r
    old=run('old',js=True);cold=pref.cold('check',label/'old');check(external_products(label/'old')==pr,'old restored physically different inputs');oldq=run('old-unchanged',meter=True)
    git('switch','--detach',frozen['sources']['Ruff_edit']);check(not git('status','--porcelain'),'dirty edited tree')
    edited=run('edit',meter=True);unchanged=run('edit-unchanged',meter=True);marked=run('edit-unchanged-json',js=True)
    original=changed.read_bytes();body=plan['additional_private'];a,b=body['old'].encode(),body['new'].encode()
    try:
        altered('body',original,a,b);private=run('private-body',meter=True);run('private-unchanged',meter=True)
        changed.write_bytes(original);back=run('restore-body');altered('invalid',original,a,b);run('invalid',bad=True)
    finally:changed.write_bytes(original)
    repair=run('repair');pref.fresh('empty-new-'+str(j));clean=run('independent-clean-new',js=True);clean_cold=pref.cold('check',label/'independent-clean-new')
    check(cold==clean_cold and external_products(label/'independent-clean-new')==pr,'independent external products drifted')
    sets=[public(x['metadata'])for x in (edited,back,repair,clean)]
    check(all(x==sets[0]for x in sets),('distinct new public hashes with byte-identical externs',sets))
    check(private['metadata']['ruff_linter']['public']==edited['metadata']['ruff_linter']['public'],'private public hash changed')
    names=lambda x:sorted(x['rustcs'].values())
    check(names(oldq)==names(unchanged)==names(marked)==['ty_python_semantic']and len(names(edited))==7 and names(private)==['ruff_linter','ty_python_semantic']and names(repair)==names(edited),'unexpected actual rustc topology')
    nonfresh=[r['target']['name']for r in external_prefix.events(label/'edit-unchanged-json')if r['reason']=='compiler-artifact'and not r['fresh']]
    check(sorted(nonfresh)==sorted(['ty_python_semantic','ruff_graph','ruff_workspace','ruff_server','ruff','ruff']),'different nominal unchanged units')
    put(label/'accepted.json',{'role':role,'seq':j,'cold':cold,'public':sets[0],'edit':names(edited),'nop':names(unchanged),'private':names(private),'nominal':nonfresh,'whole_irs':{k:v['hardware']['instructions']for k,v in rows.items()if'hardware'in v}})
    pref.fresh('finished-'+str(j));state.rename(bank)
    return {k:v['hardware']['instructions']for k,v in rows.items()if'hardware'in v},sets[0]

def main():
    prep();p=enrolled_conversion()if READER_ONLY else enroll();results=[];identities=[]
    for j,r in enumerate(frozen['order']):
        values,identity=assess(r,j,p[r]);results.append(values);identities.append(identity)
    check(all(i==identities[0]for i in identities),'cross-role consumer public bytes differ on fixed literal externals')
    for role in ('P','C'):
        select(role);fresh_state();d=out/('wholly-empty-new-'+role);execute([*primary,'--message-format=json'],d)
        sig=semantic(d);real=external_products(d);compressed(d/'external-products.json.gz',real);pp=p[role][2]
        diff=sorted(k for k in real.keys()|pp.keys()if real.get(k)!=pp.get(k))
        summary={'identical_native_inputs':not diff,'differences':diff,'independent_public_same':public(sig)==identities[0]}
        put(d/'separate-verdict.json',summary)
        check(real.keys()==pp.keys()and (diff or summary['independent_public_same']),'fully empty public disagreement with equal external products')
    put(out/'terminal.json',{'order':frozen['order'],'registered_external':json.loads((out/'selected.json').read_bytes()),'values':results,'public':identities[0]})
if __name__=='__main__':main()
