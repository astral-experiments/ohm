"""Run the two actual compilers at identical checkout, target, registry and tool paths on one worker."""
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess as sp
import sys
import time

HERE=Path(__file__).resolve().parent
WORKSPACE=Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
frozen=WORKSPACE/'legacy-qa/scripts/ruff-clap-config-help'
sys.path.insert(0,str(frozen));sys.path.insert(0,str(HERE))
import common as b
import member_names,partitions,mono_rows,transport,old_namespace
CASE=os.environ['RUFF_CASE'];reg=transport.REGISTER
b.OLD,b.NEW=reg['native_sources'][CASE];b.LOCK={'28392':'fea1c04b2bce37f54c14449e8402528e652f4e5b9fcd366c118c360d439924c8','26372':'4f1629d6337b4e24b94810bc031f0f68ddb120152726ac1f2c558ecdee46bf4c'}[CASE]
if CASE=='26372':b.SRCS={b.OLD:'09af3d91c8734ba18e61d7db1b122695bf0327ec14c1aaa40ecda26d1ca59d54',b.NEW:'9aadd1de37c76267ce65f9cf022a89f1b443a6a57aa484489968d0cd76d4d726'}
ORDER={'28392':'PC','26372':'CP'}[CASE];OUTPUT=Path(os.environ['RUNNER_TEMP'])/'derived-owner-outputs';CACHE=OUTPUT.parent/'derived-owner-inputs'
original=b.verdict
def rawtd(td):
    a=td/'kernel-execs';a.mkdir();return a
def isource(path):
    s=path.stat();return [s.st_dev,s.st_ino]
def lifetimes(path):
    images={};rows=[];total=None;executed=[]
    for l in (path/'epochs.tsv').read_text().splitlines():
        f=l.split()
        if f[0]=='I':
            image,pid=int(f[1]),int(f[2]);a=(path/f'{image:05}.nul').read_bytes().split(b'\0');b.need(a.pop()==b'' and int(a[0])==pid,'incomplete exec identity');argv=list(map(os.fsdecode,a[4:]));identity=list(map(int,a[1:3]));ix={'pid':pid,'image':image,'identity':identity,'argv':argv,'path':os.fsdecode(a[3]),'origin':f[5]}
            images[image]=ix
            if f[5]=='exec':executed.append(ix)
        if f[0]=='R':
            i,p,n,e,r,c=map(int,f[1:]);b.need(images[i]['pid']==p and n>0 and e==r>0 and c==0,'refused kernel lifetime');rows.append({**images[i],'instructions':n,'enabled':e,'running':r})
        if f[0]=='W':
            n,e,r,c=map(int,f[1:]);b.need(n>0 and e==r>0 and c==0,'refused whole measured repeat');total=n
    b.need(total,'truncated kernel epochs');rust=isource(b.SDK/'bin/rustc');wild=isource(b.SDK/b.WILD);actual=[];roots=[]
    for x in rows:
        if x['identity']==rust and '--crate-name'in x['argv']:
            actual.append((b.crate_arg(x['argv'],'--crate-name'),b.crate_arg(x['argv'],'--crate-type'),x['instructions']))
        elif x['identity']==wild:roots.append(x['instructions'])
    return {'whole':total,'rustcs':actual,'wild_lifetimes':roots,'execs':len(executed)}
def run_probe(exe,td,state):
    if CASE=='28392':v=original(exe,td,state)
    else:
        env=b.env()|{'NO_COLOR':'1','COLUMNS':'240','LC_ALL':'C','TERM':'dumb','RUFF_NO_CACHE':'true'};cases={}
        work=b.ROOT/'format-project';work.mkdir(exist_ok=True)
        (work/'out').mkdir(exist_ok=True);(work/'ruff.toml').write_text('extend-exclude = ["out"]\n[format]\nexclude = ["format_excluded.py"]\n')
        for x in ('main.py','format_excluded.py','cli_excluded.py','out/a.py'):(work/x).write_text('x    = 1\n')
        for key,tail,stdin in [('format-help',['format','--help'],None),('actual-files',['format','--check','--config','ruff.toml','--extend-exclude','cli_excluded.py','.'],None),('lint',['check','--isolated','--select','F401','-'],b'import os\n'),('bad-config',['check','--isolated','--config','lint.line-length = 100','-'],b'x=1\n')]:
            p=sp.run([exe,*tail],cwd=work,env=env,input=stdin,capture_output=True,timeout=30)
            (td/(key+'.stdout')).write_bytes(p.stdout);(td/(key+'.stderr')).write_bytes(p.stderr);s=' '.join(p.stdout.decode().split());e=p.stderr.decode()
            if key=='format-help':b.need(p.returncode==0 and not e and ('--extend-exclude'in s)==(state==b.NEW),'changed CLI option membership')
            elif key=='actual-files'and state==b.OLD:b.need(p.returncode==2 and 'unexpected argument'in e and '--extend-exclude'in e,'stale old option verdict')
            elif key=='actual-files':b.need(p.returncode==1 and s=='Would reformat: main.py 1 file would be reformatted' and not e,('new filter verdict',s,e))
            elif key=='lint':b.need(p.returncode==1 and 'F401'in s and not e,'lint')
            else:b.need(p.returncode==2 and '--config'in e and 'line-length'in e,'invalid config')
            cases[key]=[p.returncode,hashlib.sha256(p.stdout).hexdigest(),hashlib.sha256(p.stderr).hexdigest()]
        v={'cases':cases,'show_example':['format-help']}
    if CASE=='28392':
        p=sp.run([exe,'version','--output-format','json'],env=b.env(),cwd=b.WORK,capture_output=True,timeout=30);b.need(p.returncode==0 and not p.stderr and json.loads(p.stdout)['commit_info']['commit_hash']==state,'actual Git version');(td/'version.stdout').write_bytes(p.stdout)
        v['version']=json.loads(p.stdout)
    return v
b.verdict=run_probe

def footprint():
    table={};seen=set();total=0
    for tag,root in [('target',b.TARGET),('build',b.BUILD),('cargo-home',b.HOME)]:
        files=blocks=bytes_=0
        for d,dirs,fs in os.walk(root):
            for n in fs:
                s=os.lstat(Path(d)/n)
                if not stat.S_ISREG(s.st_mode):continue
                files+=1;bytes_+=s.st_size;blocks+=512*s.st_blocks;k=(s.st_dev,s.st_ino)
                if k not in seen:seen.add(k);total+=512*s.st_blocks
        table[tag]={'files':files,'bytes':bytes_,'allocated_counting_links':blocks}
    return {'by_root':table,'distinct_regular_inodes':len(seen),'allocated_unique':total}

def dump_partitions(td,role):
    name='library-ordinary-partition.json';native=json.loads((td/'selected-ruff-members.json').read_bytes());members={m[2]+'.o':m[3]for m in native['members']};sessions=json.loads((td/'incremental-native-sessions.json').read_bytes())
    match=[(k,rows)for k,rows in sessions.items()if {v[0]:v[5]for v in rows}==members];b.need(len(match)==1,'no unique actual selected library incremental generation');k,rows=match[0];session=b.TARGET/k;query=session/'query-cache.bin';b.need(query.stat().st_size<256*2**20,'large selected cache');cache=b.zsave(query,b.PUB/'native');wire=query.read_bytes();b.need(wire[:6]==b'RSIC'+{'P':57124,'C':60597}[role].to_bytes(2,'little') and wire[-13:]==b'rust-end-file','wrong incremental file format')
    for r in rows:b.need(b.zsave(session/r[0],b.PUB/'native')==r[5],'actual codegen body moved')
    decl={'cache':cache,'bytes':len(wire),'session':k,'members':members};b.put(td/name,decl)
    try:
        table=partitions.table(wire,{'objects':members},None,len(members));b.put(td/'complete-cgu-table.json',table)
        exact={};unknown={}
        for name,unit in table['rows'].items():
            try:
                entries=mono_rows.read(wire,unit)
                exact[name]={'roots':sum(not v[4]for v in entries),'root_mir':sum(v[7]for v in entries if not v[4]),'inline_memberships':sum(v[4]for v in entries),'inline_mir':sum(v[7]for v in entries if v[4])}
            except (ValueError,IndexError,UnicodeError)as err:unknown[name]=str(err)[:360]
        b.put(td/'typed-inline-census.json',{'decoded':exact,'refused':unknown,'total_memberships':sum(v['items']for v in table['rows'].values()),'total_mir':sum(v['size']for v in table['rows'].values())})
    except (ValueError,IndexError,UnicodeError)as err:b.put(td/'cgu-decode-refusal.json',{'reason':str(err),'bytes':len(wire),'cache':cache})
def price_cli(td):
    # Keep all executed program costs outside the Cargo period. Two genuine parse paths exercise Clap.
    env=b.env()|{'NO_COLOR':'1','COLUMNS':'240','LC_ALL':'C','TERM':'dumb','RUFF_NO_CACHE':'true'}
    binary=b.TARGET/'debug/ruff'
    for tag,args in (('top-help',['--help']),('format-help',['format','--help'])):
        for i in range(3):
            dst=td/f'native-{tag}-{i}.json'
            cmd=[b.ROOT/'whole_count',dst,binary,str(binary),*args]
            proc=sp.run(cmd,env=env,cwd=b.WORK,capture_output=True,timeout=30)
            b.need(proc.returncode==0 and not proc.stderr and b'--help'in proc.stdout,('invalid CLI output during separate runtime control',tag))
            data=json.loads(dst.read_bytes())
            b.need(data['status']==0 and data['instructions']>0 and data['enabled']==data['running']>0,'invalid auxiliary CLI counter')
            b.put(td/f'native-{tag}-{i}-output.json',{'stdout':hashlib.sha256(proc.stdout).hexdigest(),'stderr':hashlib.sha256(proc.stderr).hexdigest(),'elf':b.hf(binary)})
def phase(role,stage,state,kind='ordinary'):
    b.guard();td=b.PUB/stage;whole=b.ROOT/'whole_count';argo=[whole,td/'hardware.json',shutil.which('cargo',path=b.env()['PATH']),*b.CMD]
    if kind=='cold':b.command(td,argo,trace_cold=True)
    elif kind=='lifetime':
        td.mkdir();tasks=rawtd(td);trace=[b.ROOT/'exec_count','--lifetime',b.SDK/'bin/rustc','--also',b.SDK/b.WILD,tasks,*argo]
        with (td/'stdout').open('xb')as out,(td/'stderr').open('xb')as err:p=sp.run(trace,env=b.env(),cwd=b.WORK,stdout=out,stderr=err)
        b.need(p.returncode==0,('kernel repeat',stage));counts=lifetimes(tasks);b.put(td/'lifetime.json',counts)
        if stage=='observed-edit':
            b.need(sorted((k,t)for k,t,n in counts['rustcs'])==[('ruff','bin'),('ruff','lib')] and counts['wild_lifetimes'],'edit should compile ruff twice and link')
            records=b.read_kernel_rustcs(tasks,tuple(isource(b.SDK/'bin/rustc')))
        else:
            b.need(not counts['rustcs'] and not counts['wild_lifetimes'],('nonempty settled inventory',stage,counts['rustcs'],counts['wild_lifetimes']));records=[]
        b.put(td/'real-ruff-rustcs.json',records)
    else:b.command(td,argo)
    h=json.loads((td/'hardware.json').read_bytes());b.need(h['status']==0 and h['instructions']>0 and h['enabled']==h['running']>0,'bad ordinary counter')
    prod=b.observe_products(td,state);b.snapshot_work_products(td);b.put(td/'products.json',prod)
    if stage in ('cold-old','edit','empty-new'):
        b.put(td/'footprint.json',footprint());dump_partitions(td,role);price_cli(td)
    return prod
def native_ledger(td):
    n=json.loads((td/'selected-ruff-members.json').read_bytes());return member_names.native_identity(n)
def empty_outputs():
    for p in (b.TARGET,b.BUILD,b.HOME):
        b.need(p.parent==b.ROOT and p.is_dir()and not p.is_symlink(),'will only clear the ephemeral current worker roots');shutil.rmtree(p)
def run_role(role):
    b.ROOT.mkdir();b.guard();b.PUB=OUTPUT/role;b.PUB.mkdir();b.SDKBASE.mkdir()
    tar,proof=transport.fetch(role,CACHE,b.PUB/'factory');transport.install(tar,proof,b.SDK,b.RUSTUP/'toolchains/ohm')
    env=b.env()
    for n in ('rustc','cargo'):
        output=sp.check_output([n,'+ohm','-vV'],env=env,text=True);b.need(output==proof['versions'][n],'actual toolchain role was changed')
    for name in ('exec_count','whole_count','thread_meter'):sp.run(['cc','-O2','-pthread','-Wall','-Wextra','-Werror',frozen/(name+'.c'),'-o',b.ROOT/name],check=True)
    b.select(b.OLD);b.prepare();old=phase(role,'cold-old',b.OLD,'cold');b.need('canonical_archive'in old,'unknown producer archive')
    held=b.ROOT/'retained/ruff';held.parent.mkdir();shutil.copy2(b.TARGET/'debug/ruff',held)
    no=phase(role,'old-unchanged',b.OLD,'lifetime');b.need(b.same_artifacts(old,no),'old no-op native output')
    snapshot=old_namespace.save(b.ROOT);b.put(b.PUB/'initial-old-namespace.json',snapshot)
    b.select(b.NEW);td=b.PUB/'old-on-new';td.mkdir();b.need(b.verdict(held,td,b.OLD)==old['verdict'],'saved OLD changed behavior')
    edit=phase(role,'edit',b.NEW);b.need(edit['elf']!=old['elf'] and edit['verdict']!=old['verdict'],'no real edit')
    if CASE=='28392':
        for label in ('help','check-help','format-help'):
            before=b' '.join((b.PUB/'cold-old'/(label+'.stdout')).read_bytes().split());after=b' '.join((b.PUB/'edit'/(label+'.stdout')).read_bytes().split())
            b.need(before.count(b'lint.line-length = 100')==1 and before.replace(b'lint.line-length = 100',b'line-length = 100')==after,'extra observable help delta '+label)
    a=phase(role,'edited-unchanged',b.NEW,'lifetime');b.need(b.same_artifacts(a,edit),'new no-op')
    base=b.SRC.read_bytes()
    try:
        b.SRC.write_bytes(base+b'\nconst _: u8 = "owner_cgu_invalid";\n')
        for name in ('invalid','invalid-unchanged'):
            td=b.PUB/name;b.command(td,b.CMD,101);err=(td/'stderr').read_bytes();b.need(b'error[E0308]'in err and b'owner_cgu_invalid'in err,'stale diagnostic')
    finally:b.SRC.write_bytes(base)
    repaired=phase(role,'repair',b.NEW);b.need(b.same_artifacts(repaired,edit),'repair missed a native or metadata delta')
    b.select(b.OLD)
    # The prior reverse compile yielded 1,098 differing published rows on both compilers.
    # Keep it outside every price: the diagnostic needs the exact pre-edit state, not that history.
    b.put(b.PUB/'restored-old-namespace.json',old_namespace.restore(b.ROOT,snapshot))
    prior=phase(role,'restored-old',b.OLD,'lifetime');b.need(b.same_artifacts(prior,old),'restored OLD no-op changed a complete native or metadata input')
    b.select(b.NEW);direct=phase(role,'observed-edit',b.NEW,'lifetime');b.need(b.same_artifacts(direct,edit),'traced re-edit changed a native product')
    empty_outputs();b.prepare();clean=phase(role,'empty-new',b.NEW,'cold')
    b.need(clean['elf']==edit['elf'] and clean['verdict']==edit['verdict'],'independent complete CLI or verdict differs')
    b.need(native_ledger(b.PUB/'edit')==native_ledger(b.PUB/'empty-new'),'independent producer archive differs')
    def objects(tag):
        all_sessions=json.loads((b.PUB/tag/'incremental-native-sessions.json').read_bytes())
        return sorted(sorted((x[0],x[4],x[5])for x in rows)for rows in all_sessions.values())
    b.need(objects('edit')==objects('empty-new'),'independent complete native CGU census differs')
    b.need(not b.git('status','--porcelain'),'unexpected dirty Ruff source')
    mini=b.ROOT/'mini';guards=b.ROOT/'guards'
    try:
        sp.run([sys.executable,'-IB',HERE/'probe.py',mini,{'P':'parent','C':'candidate'}[role]],env=b.env(),check=True)
        sp.run([sys.executable,'-IB',HERE/'guards.py',mini,guards,role],env=b.env(),check=True)
    finally:
        for root,label in ((mini,'mini'),(guards,'guards')):
            if root.is_dir():
                dest=b.PUB/label;dest.mkdir()
                for f in root.iterdir():
                    if f.is_file()and f.suffix in ('.err','.out','.stdout','.stderr','.json'):shutil.copyfile(f,dest/f.name)
    b.put(b.PUB/'admission.json',{'role':role,'case':CASE,'old':old,'edit':edit,'clean':clean,'all_probes':True})
    empty_outputs();b.need(b.ROOT.parent==OUTPUT.parent and b.ROOT.name=='ohm-clap-cli','private role root');shutil.rmtree(b.ROOT)
def main():
    b.need(os.environ['GITHUB_RUN_ATTEMPT']=='1'and os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']and os.environ['GITHUB_REF_NAME']=='charlie/qa-ruff-derived-impl-cgus-20261103','unregistered invocation')
    b.need(sp.check_output(['git','-C',frozen,'rev-parse','HEAD'],text=True).strip()=='e48abf3b09f415b296d0ee2e8ec81c0de7b50611','wrong ordinary source')
    b.need(b.git('rev-parse','HEAD')==b.NEW and b.git('rev-parse','HEAD^')==b.OLD,'wrong original history')
    OUTPUT.mkdir();b.put(OUTPUT/'registration.json',{'native_sources':[b.OLD,b.NEW],'source_paths':b.SRCS,'lock':b.LOCK,'case':CASE,'order':ORDER,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'registration':reg,'transports':transport.KIT})
    errors={}
    for role in ORDER:
        try:run_role(role)
        except Exception as exc:
            errors[role]=repr(exc);b.put(OUTPUT/('refusal-'+role+'.json'),{'reason':repr(exc)});print(role,repr(exc),flush=True)
            # Keep this worker's original SDK and raw verdicts. The other role starts at the same unshared paths.
            if b.ROOT.is_dir():b.ROOT.rename(OUTPUT.parent/('refused-owner-'+role))
    if errors:raise RuntimeError(errors)
    roles={role:json.loads((OUTPUT/role/'admission.json').read_bytes())for role in ORDER}
    for label in ('old','edit','clean'):b.need(roles['P'][label]['verdict']==roles['C'][label]['verdict'],'cross-compiler native CLI verdict '+label)
    b.need((OUTPUT/'P/factory/bootstrap.json').read_bytes()==(OUTPUT/'C/factory/bootstrap.json').read_bytes(),'different actual full compiler bootstrap command')
    b.put(OUTPUT/'terminal.json',{'case':CASE,'paired':True,'order':ORDER})
if __name__=='__main__':main()
