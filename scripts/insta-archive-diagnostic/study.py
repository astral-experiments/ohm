"""One signed Linux e2e diagnosis. No time measurement and no product changes."""
import collections, gzip, hashlib, json, os, re, runpy, shutil, subprocess, sys, tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'ohm-cargo-301-linux-ci'))
import e2e_existing as old
import test_hook
e,w,c,root,slot,out=old.e,old.w,old.c,old.root,old.slot,old.out
role=os.environ['FOCUSED_CARGO']
def j(p):return json.loads(p.read_bytes())
def z(p,data):e.gz(p,data)
def state(p):
    return {'path':str(p),'stat':e.stat(p),'sha256':e.sha(p)} if p.exists() else None
def call(*args,**kw):return subprocess.run(args,check=True,**kw)
def fresh():
    return [slot/'target',slot/'shared']
def park(tag):
    assert not any(p.is_symlink() for p in fresh())
    park=root/('prior-'+tag);park.mkdir()
    for p in fresh():
        assert p.is_dir() and p.resolve()==p and p.parent==slot
        p.rename(park/p.name)
    assert not any(p.exists() for p in fresh())
def line_set(d):
    names=sorted(str(p) for base in fresh() for p in base.rglob(d.name) if p.is_file() and not p.is_symlink() and p.samefile(d))
    if len(names)!=d.stat().st_nlink:
        names=sorted(str(p) for base in fresh() for p in base.rglob('*') if p.is_file() and not p.is_symlink() and p.samefile(d))
    assert len(names)==d.stat().st_nlink
    return names
def filtered_rows(tmp,tools,watch,provider):
    execs=[];calls=[];times=[];provider_opens=[];edges={};rust=[];wild=[];cargos=[];scan={}
    for f in sorted(tmp.glob('trace.*')):
        pid=int(f.suffix[1:])
        h=hashlib.sha256();n=0
        with f.open('rb') as rows:
            for raw in rows:
                n+=1;h.update(raw);m=re.fullmatch(rb'([0-9]+\.[0-9]+) (.*)\n',raw)
                if not m:continue
                stamp,lit=m[1].decode(),m[2]
                if lit.startswith(b'execve(') and lit.endswith(b'= 0'):
                    exe,argv=c.event(lit);physical=Path(exe).resolve()
                    execs.append([pid,stamp,lit.decode()])
                    if physical==Path(tools['cargo']['physical']) and argv[1:]==e.CMD[2:]:cargos.append(pid)
                    if physical==Path(tools['rustc']['physical']) and '--crate-name' in argv and '--out-dir' in argv and not any(x.startswith('--print') for x in argv):
                        rust.append([pid,argv[argv.index('--crate-name')+1],'link-only' if any(x in ('-Zlink-only','link-only') for x in argv) else 'full'])
                        if rust[-1][1]=='e2e':calls.append(['e2e',argv])
                    if physical==Path(tools['wild']['physical']) and '-o' in argv:
                        wild.append([pid,argv[argv.index('-o')+1]])
                        if Path(wild[-1][1]).name.startswith('e2e-'):calls.append(['wild',argv])
                if lit.startswith((b'clone(',b'clone3(',b'fork(',b'vfork(')):
                    kid=re.search(rb'= (\d+)(?:<[^>]*>)?$',lit)
                    if kid:edges[int(kid[1])]=pid
                if lit.startswith((b'utimensat(',b'utime(',b'utimes(',b'futimesat(')) and re.search(rb'libinsta-[0-9a-f]+\.rlib[>"]',lit):
                    times.append([pid,stamp,lit.decode()])
                if provider is not None and lit.startswith(b'openat(') and os.fsencode(provider) in lit:
                    provider_opens.append([pid,stamp,lit.decode()])
        scan[pid]=[n,h.hexdigest()]
    assert len(cargos)==1,('actual Cargo',cargos)
    def ancestor(pid,roots):
        seen=set()
        while pid not in roots and pid in edges:
            assert pid not in seen;seen.add(pid);pid=edges[pid]
        return pid if pid in roots else None
    owners={x[0] for x in wild}
    opens=[[pid,stamp,lit,ancestor(pid,owners)] for pid,stamp,lit in provider_opens]
    return {'physical_cargo':cargos[0], 'rust':rust, 'wild':wild, 'timestamp_syscalls':times,'provider_opens':opens,
            'raw_trace_index':scan,'spawn_edges':edges},execs,calls

def acquire():
    assert role in ('shipped','strict-293') and not root.exists()
    root.mkdir();out.mkdir();slot.mkdir();w.room(root,65)
    helper=Path(sys.argv[2]).resolve();assert e.sha(helper)=='84d094bc06fe4d65efc869259e7760530d813d515f47237da1744c6791fe61a0'
    def download():
        e.prepare(root,'21')
        if role=='strict-293':runpy.run_path(str(helper))['acquire']('gh',out/'strict-source.json',root/'materialized-classic')
    old.hosted_credential(download)
    repo=root/'source';call('git','init','-q',repo)
    for depth,rev in [(1,c.RUFF),(2,c.HISTORY)]:w.git(repo,'fetch','-q','--no-tags','--depth='+str(depth),'https://github.com/astral-sh/ruff.git',rev)
    w.git(repo,'switch','-q','--detach',c.RUFF)
    assert w.git(repo,'rev-parse','HEAD^{tree}').decode().strip()==c.TREE and e.sha(repo/'Cargo.lock')==c.LOCK
    assert w.git(repo,'diff','--binary','--abbrev=10',c.HISTORY+'^',c.HISTORY)==(c.FIX/'historical.patch').read_bytes()
    w.replace(repo,'original');env=w.environment(root,'21',slot)
    tools=w.tools(root,'21',env);physical=root/'sdk-21/bin/cargo';before=j(root/'receipts/21/tools.json')
    if role=='strict-293':
        physical.rename(root/'shipped-cargo');(root/'materialized-classic/cargo').rename(physical)
        assert e.sha(physical)=='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'
    tools['cargo']=w.fx(physical)
    actual={k:subprocess.check_output(a,env=env,text=True).strip() for k,a in [
        ('cargo',['cargo','+ohm','-Vv']),('rustc',['rustc','+ohm','-vV']),('sysroot',['rustc','+ohm','--print','sysroot'])]}
    assert actual['rustc']==before['versions']['rustc'] and actual['sysroot']==before['versions']['sysroot']
    assert ('735e1528ed741015c57676dccf05dbdc0ff7bed1' if role=='strict-293' else '2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c') in actual['cargo']
    so=root/'archive-time.so';call('cc','-Wall','-Werror','-O2','-shared','-fPIC',HERE/'archive_time.c','-ldl','-o',so)
    e.save(out/'calibration.json',test_hook.calibrate(root/'calibration',so))
    e.save(out/'tools.json',{'role':role,'actual':actual,'sdk':j(root/'receipts/21/custody.json'),'tools':tools,
        'original':before,'source':c.RUFF,'tree':c.TREE,'lock':c.LOCK,'history':c.HISTORY,'native_hook':state(so),
        'instrument_sources':{p.name:e.sha(p) for p in HERE.iterdir() if p.is_file()},
        'qa':w.git(HERE,'rev-parse','HEAD').decode().strip(),'original_qa':w.git(e.orig,'rev-parse','HEAD').decode().strip()})
    online={k:v for k,v in env.items() if k!='CARGO_NET_OFFLINE'}
    call('cargo','+ohm','fetch','--locked',env=online,cwd=repo,timeout=900)
    env|={'LD_PRELOAD':str(so),'QA_INSTA_CONFIG':str(root/'policy'),'QA_INSTA_ACTOR':str(physical),
          'CARGO_LOG':'cargo::compiler=info'}
    assert not any(k in env for k in ('CI','TF_BUILD','QUALIFICATION_TOKEN','GH_TOKEN','GITHUB_TOKEN','RUSTFLAGS'))
    e.CMD.append('--features=insta/default,insta/redactions,insta/ron')
    return repo,env,tools

def visit(repo,env,tools,label,mode=None,watch=None,provider=None,raw=False):
    w.room(root,60)
    dest=out/label;dest.mkdir();cfg=root/'policy'
    if cfg.exists():cfg.unlink()
    audit=dest/'audit.tsv';audit.touch()
    before=state(watch) if watch is not None else None
    aliases=line_set(watch) if before else []
    if mode:
        assert before and (root/'reference.rlib').is_file() and mode in ('allow','hold')
        st=watch.stat();cfg.write_text(f"{mode} {st.st_dev} {st.st_ino} {root/'reference.rlib'} {audit}\n")
    cmd_env=env.copy()
    if raw:del cmd_env['LD_PRELOAD']
    system_calls='execve,execveat,clone,clone3,fork,vfork,utimensat,utime,utimes,futimesat,exit_group'
    if provider is not None:system_calls+=',openat'
    with tempfile.TemporaryDirectory(dir=env['TMPDIR']) as scratch:
        temp=Path(scratch)
        args=['strace','-ff','-q','-ttt','-y','-s','262144','-e','trace='+system_calls,'-o',str(temp/'trace'),*e.CMD]
        with (temp/'stdout').open('wb') as so,(temp/'stderr').open('wb') as se:
            run=subprocess.run(args,cwd=repo,env=cmd_env,stdout=so,stderr=se,timeout=1400)
        stdout=(temp/'stdout').read_bytes();stderr=(temp/'stderr').read_bytes()
        z(dest/'stdout.gz',stdout);z(dest/'stderr.gz',stderr)
        obs,execs,calls=filtered_rows(temp,tools,watch,provider)
    z(dest/'native-exec.json.gz',json.dumps(execs,separators=(',',':')).encode())
    after=state(watch) if watch is not None else None
    records=[line.split('\t') for line in audit.read_text().splitlines()]
    times=obs['timestamp_syscalls']
    e.save(dest/'raw-syscalls.json',obs)
    e.save(dest/'input-custody.json',{'command':e.CMD,'source':{s:e.sha(repo/s) for s in c.ORACLE['source'] if (repo/s).is_file()},'policy':cfg.read_text() if cfg.exists() else None,'before':before,'after':after,'aliases':aliases})
    if mode:
        assert before['sha256']==after['sha256']==e.sha(root/'reference.rlib') and before['stat'][:2]==after['stat'][:2] and aliases==line_set(watch)
        assert len(records)==len(times),(label,'unaccounted Insta timestamp calls',records,times)
        remaining=list(times)
        for row in records:
            pid,tid,fd=map(int,row[:3]);held=int(row[6])
            assert len(row)==23 and pid==obs['physical_cargo'] and row[3]==mode and row[4:6]==['1','1'] and held==(mode=='hold')
            assert [int(x) for x in row[7:9]]==before['stat'][:2] and row[-1] in aliases and int(row[-2])==0
            match=next(v for v in remaining if v[0]==tid and f'utimensat({fd}<{row[-1]}>, NULL' in v[2] and v[2].endswith('= 0'))
            remaining.remove(match)
            assert match[2].count('UTIME_OMIT')==1+held,(row,match)
            assert (row[9:11]==row[11:13])==bool(held)
            assert not held or row[17:19]==row[19:21]
        assert not remaining
    rows=[json.loads(x) for x in stdout.splitlines()]
    assert rows and rows[-1]=={'reason':'build-finished','success':run.returncode==0},(run.returncode,stderr[-1000:])
    arts=[a for a in rows if a['reason']=='compiler-artifact'];ep=None;case=None;listing=None;elf=None
    if run.returncode==0:
        assert len(arts)==309
        a,=[a for a in arts if a.get('executable')];assert a['target']['name']=='e2e' and a['target']['src_path'].endswith('ty_server/tests/e2e/main.rs')
        ep=Path(a['executable']);assert ep.resolve()==ep and ep.is_relative_to(slot)
        res_env=cmd_env|{'INSTA_WORKSPACE_ROOT':str(repo),'INSTA_UPDATE':'no'}
        tests=subprocess.run([ep,'--list'],cwd=repo,env=res_env,capture_output=True,timeout=60)
        res=subprocess.run([ep,c.RUN_CASE,'--exact'],cwd=repo,env=res_env,capture_output=True,timeout=90)
        case=res.returncode
        for tag,v in [('case-out',res.stdout),('case-err',res.stderr),('list',tests.stdout),('list-err',tests.stderr)]:z(dest/(tag+'.gz'),v)
        listing=[tests.returncode,sum(l.endswith(b': test') for l in tests.stdout.splitlines()),e.digest(tests.stdout)]
        if case==0:assert listing[:2]==[0,200] and b'1 passed' in res.stdout and c.RUN_CASE.encode()+b': test' in tests.stdout
        elf=state(ep);blob=out/'elf';blob.mkdir(exist_ok=True)
        data=blob/(elf['sha256']+'.gz')
        if not data.exists():
            with ep.open('rb') as src,data.open('wb') as dst,gzip.GzipFile(fileobj=dst,mode='wb',compresslevel=1,mtime=0) as gz:shutil.copyfileobj(src,gz,1<<20)
    obs|={'label':label,'cargo':run.returncode,'case':case,'listing':listing,'file':elf,'typed':len(arts),'watch_before':before,
          'watch_after':after,'aliases':aliases,'mode':mode,'raw':raw,'command':e.CMD,'source':{s:e.sha(repo/s) for s in c.ORACLE['source'] if (repo/s).is_file()},
          'provider':state(provider) if provider else None,'provider_path':str(provider) if provider else None,'audit':records,
          'cutoff_lines':[line.decode(errors='replace') for line in stderr.splitlines() if b'early cutoff:' in line and b'insta ' in line],
          'dirty':[[a['target']['name'],a['target']['kind']] for a in arts if not a['fresh']]}
    e.save(dest/'record.json',obs)
    print(label,'cargo',obs['cargo'],'case',case,'full/link-only/Wild',dict(collections.Counter(r[2] for r in obs['rust'])),len(obs['wild']),'held',len(records) if mode=='hold' else 0,flush=True)
    return obs,calls,arts
def make_provider(earlier):
    tmp=root/'native-shadow';tmp.mkdir();src=tmp/'selected.c';obj=tmp/'selected.o'
    src.write_text('#include <unistd.h>\nstatic void init(int ac,char**av,char**env){if(ac<1||!av||!av[0])return;'
        'const char*b=av[0];for(const char*p=b;*p;p++)if(*p==47)b=p+1;'
        "if(b[0]=='e'&&b[1]=='2'&&b[2]=='e'&&b[3]=='-')_exit(83);}\n"
        '__attribute__((used,section(".preinit_array"))) static void(*slot)(int,char**,char**)=init;\n')
    system=Path(subprocess.check_output(['gcc','-print-file-name=libgcc_s.so'],text=True).strip()).resolve(strict=True)
    call('gcc','-fPIE','-O1','-c',src,'-o',obj)
    guard=tmp/'e2e-private-control';ordinary=tmp/'other-program';main=tmp/'main.c';main.write_text('int main(void){return 0;}\n')
    call('gcc',main,obj,'-o',guard);os.link(guard,ordinary)
    assert [subprocess.run([p]).returncode for p in (guard,ordinary)]==[83,0]
    valid=f'INPUT ( "{obj}" "{system}" )\n'.encode();bad=b'UNRECOGNIZED_E2E_PRIVATE_LINK_SCRIPT\n'
    e.save(out/'native-provider.json',{'earlier':str(earlier),'src':src.read_text(),'object':state(obj),'system':state(system),
        'valid':valid.decode(),'malformed':bad.decode(),'controls':[83,0]})
    z(out/'provider.o.gz',obj.read_bytes());return valid,bad

def main():
    repo,env,tools=acquire()
    allrows={}
    def run(label,**kw):
        row,calls,arts=visit(repo,env,tools,label,**kw);allrows[label]=row;return row,calls,arts
    # Cargo fingerprints loader environment. Obtain the unwrapped baseline in
    # its own empty same-path generation, then keep LD_PRELOAD constant through
    # every phase of the independent allowed/held generation.
    raw_cold,_,_=run('unwrapped-cold',raw=True)
    raw_second,_,_=run('unwrapped-repeat',raw=True)
    assert raw_cold['file']['sha256']==raw_second['file']['sha256'] and raw_second['timestamp_syscalls']
    park('unwrapped')
    cold,calls,arts=run('cold')
    args,=[v for k,v in calls if k=='e2e'];wild,=[v for k,v in calls if k=='wild']
    insta,={Path(a.split('=',1)[1]) for k,a in zip(args,args[1:]) if k=='--extern' and a.startswith('insta=') and a.endswith('.rlib')}
    jarchive,={Path(p) for a in arts if a['target']['name']=='insta' for p in a['filenames'] if p.endswith('.rlib')}
    assert jarchive.samefile(insta) and insta.resolve()==insta and not insta.is_symlink() and insta.is_relative_to(slot)
    earlier,={p/'libgcc_s.so' for p in [Path(x[2:]) for x in wild if x.startswith('-L') and len(x)>2]+[Path(x) for k,x in zip(wild,wild[1:]) if k=='-L'] if '/psm/' in str(p) and p.name=='out'}
    ep=Path(cold['file']['path'])
    assert earlier.is_relative_to(slot) and earlier.parent.is_dir() and not earlier.exists() and '-lgcc_s' in wild
    valid,bad=make_provider(earlier)
    ref=root/'reference.rlib';shutil.copyfile(insta,ref);ref.chmod(0o400)
    assert e.sha(insta)==e.sha(ref)
    members=subprocess.check_output(['ar','t',insta],text=True).splitlines()
    assert len(members)==len(set(members))==18
    blobs={m:e.digest(subprocess.check_output(['ar','p',insta,m])) for m in members}
    z(out/'reference.rlib.gz',ref.read_bytes())
    e.save(out/'enrollment.json',{'direct':str(insta),'cargo_product':str(jarchive),'all_aliases':line_set(insta),'reference':state(ref),
        'original':state(insta),'members':blobs,'e2e':str(ep),'native':str(earlier)})
    def warm(label,mode=None,provider=False,force=False,raw=False):
        if force and ep.exists():
            assert ep.is_relative_to(slot) and ep.resolve()==ep and ep.is_file()
            z(out/(label+'-removed-identity.json.gz'),json.dumps(state(ep)).encode());ep.unlink()
        return run(label,mode=mode,watch=insta,provider=earlier if provider else None,raw=raw)[0]
    warm('unarmed-hook-repeat')
    for pol in ('allow','hold'):
        for n in (1,2):warm(f'{pol}-repeat-{n}',pol)
        w.replace(repo,'reversed');warm(pol+'-edited',pol)
        w.replace(repo,'original');warm(pol+'-restored',pol)
    for pol in ('allow','hold'):
        for tag,data in [('valid',valid),('malformed',bad)]:
            assert not earlier.exists();earlier.write_bytes(data)
            warm(pol+'-'+tag,pol,provider=True)
            warm(pol+'-'+tag+'-force',pol,provider=True,force=True)
            assert earlier.read_bytes()==data;earlier.unlink()
            warm(pol+'-removed-'+tag,pol,provider=True)
            warm(pol+'-removed-'+tag+'-force',pol,provider=True,force=True)
    rust=repo/'crates/ty_server/tests/e2e/main.rs';original=rust.read_bytes()
    try:
        rust.write_bytes(original+b'\ncompile_error!("INSTA_ARCHIVE_DIAGNOSTIC_EARLY_STOP");\n')
        warm('hold-invalid-rust','hold')
    finally:rust.write_bytes(original)
    warm('hold-repaired-rust','hold')
    park('trained')
    # A preinstalled native-provider file is the only regular input in its empty store.
    for label,source,data in [('empty-edited','reversed',None),('empty-valid','original',valid),('empty-malformed','original',bad)]:
        w.replace(repo,source)
        assert not any(p.exists() for p in fresh())
        if data is not None:
            earlier.parent.mkdir(parents=True);earlier.write_bytes(data)
        inputs=[str(p) for base in fresh() for p in base.rglob('*') if p.is_file()]
        assert inputs==([str(earlier)] if data is not None else [])
        e.save(out/(label+'-starting-files.json'),inputs)
        run(label,provider=earlier if data is not None else None)
        park(label)
    e.save(out/'terminal.json',{'role':role,'visits':list(allrows),'records':{n:e.sha(out/n/'record.json') for n in allrows},
        'note':'One structural intervention at an existing signed Cargo output. No timings or workspace extrapolation.'})
if __name__=='__main__':main()
