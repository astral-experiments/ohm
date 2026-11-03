"""Read normal compiler partition sizes without attaching a score to the private replay."""
import copy,fcntl,hashlib,json,os,re,shutil,subprocess,sys,traceback
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import actor
w,old,library,need,put=actor.w,actor.old,actor.library,actor.need,actor.put
cfg=json.loads((HERE/'registration.json').read_bytes())
reg=actor.registration
def objects(session):
    result={p.name:old.record_file(p)for p in sorted(session.glob('*.o'))if not p.is_symlink()}
    need(len(result)==245,('native project objects',len(result)));return result
def bodies(records):return {k:v['sha256']for k,v in records.items()}
def retained(a,b):return sum(all(a[n][k]==b[n][k]for k in ('dev','ino','sha256'))for n in a.keys()&b.keys())
def scalar(p):return os.fsdecode(p.read_bytes())
def values(p):
    v=p.read_bytes().split(b'\0');need(v.pop()==b''and v,'terminated original vector');return list(map(os.fsdecode,v))
def replay(argv,env,cwd,out,err):
    words=set(re.findall(r'--jobserver-(?:auth|fds)=(\d+),(\d+)',' '.join(env.get(k,'')for k in ('MAKEFLAGS','CARGO_MAKEFLAGS','MFLAGS'))))
    need(len(words)<=1 and 'fifo:'not in env.get('CARGO_MAKEFLAGS',''),'unsupported jobserver tokens')
    pid=os.fork()
    if pid==0:
        try:
            os.chdir(cwd)
            with open(os.devnull,'rb')as i,out.open('xb')as o,err.open('xb')as e:
                os.dup2(i.fileno(),0);os.dup2(o.fileno(),1);os.dup2(e.fileno(),2)
            if words:
                rr,ww=next(iter(words));nn,mm=map(int,(rr,ww));assert nn>=3 and mm>=3 and nn!=mm and max(nn,mm)<256
                r,s=os.pipe();os.write(s,b'+++')
                a,b=[fcntl.fcntl(fd,fcntl.F_DUPFD_CLOEXEC,260)for fd in (r,s)];os.close(r);os.close(s);os.dup2(a,nn);os.dup2(b,mm);os.close(a);os.close(b)
            os.execve(argv[0],argv,env)
        except BaseException:
            traceback.print_exc();os._exit(126)
    _,status=os.waitpid(pid,0);return os.waitstatus_to_exitcode(status),sorted(words)
def main():
    need(os.environ['GITHUB_REF_NAME']==reg['branch']and os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']and os.environ['GITHUB_RUN_ATTEMPT']=='1','wrong enrollment')
    need(w.git('rev-parse','HEAD')==old.new and w.git('rev-parse','HEAD^')==old.old,'actual Ruff edit')
    need(subprocess.check_output(['git','-C',Path(os.environ['GITHUB_WORKSPACE'])/'qa','rev-parse','HEAD'],text=True).strip()==os.environ['GITHUB_SHA'],'actual receiver')
    kit=json.loads((library.B/'binding.json').read_bytes());w.guard();token=os.environ['OHM_SDK_READ_TOKEN'];env=w.install();roles=library.acquire(w,kit,token);del token
    w.sdk.rename(w.root/'signed-reference');roles['C'].rename(w.sdk)
    driver,=(w.sdk/'lib').glob('librustc_driver-*.so');tools={k:old.record_file(p)for k,p in {'driver':driver,'rustc':w.sdk/'bin/rustc','wild':w.sdk/'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'}.items()}
    need(tools['driver']['sha256']==cfg['driver']==reg['candidate_driver']and kit['driver']['C']==cfg['driver'],'actual C compiler')
    put(w.proof/'input.json',{'admission':cfg,'normal':reg,'tools':tools,'qa':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID']})
    private=w.root/'eligibility-private';private.mkdir(mode=0o700);trace=w.root/'capture-inputs'
    subprocess.run([sys.executable,'-IB',HERE/'capture-source.py',actor.LIB.parent/'exec_count.c',trace,private,w.sdk/'bin/rustc'],check=True)
    old.remove_outputs();old.state(old.old);subprocess.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],cwd=w.work,env=env,check=True);env['CARGO_NET_OFFLINE']='true'
    need(library.unit_graph(env,w.proof)==reg['graph_sha256'],'different actual closure')
    known=None;expected={};reference={};ordinary={}
    def phase(n,rev,observe=False,snapshot=False,oracle=True):
        nonlocal known
        w.guard();td=w.proof/'ordinary'/n;td.mkdir(parents=True);old.state(rev)
        ide=old.sessions();project=actor.work_products('ty_project')
        command=actor.want
        if observe:(td/'tasks').mkdir();command=[trace,td/'tasks',*command]
        with (td/'stdout.jsonl').open('xb')as o,(td/'stderr').open('xb')as e:subprocess.run(command,cwd=w.work,env=env,stdout=o,stderr=e,check=True)
        rows,_=old.result_rows(td,True);shape=sorted((r['package_id'],r['target']['name'],r['target']['kind'],sorted(r['features']),json.dumps(r['profile'],sort_keys=True))for r in rows)
        need(len(shape)==259 and (known is None or shape==known),'different normal units');known=shape;dirty=sorted(r['target']['name']for r in rows if not r['fresh'])
        if n in ('old','independent-clean'):need(len(dirty)==259,'not truly cold')
        if n=='edit':need(dirty==['ty_ide','ty_project'],'different real edit')
        if n=='unchanged':need(not dirty,'non-fresh unchanged')
        fact={'source':rev,'dirty':dirty};ordinary[n]=fact
        if observe:
            owners=actor.tool_owners(td,tools);put(td/'actual-processes.json',owners);fact['executed']=sorted(owners)
            need(set(owners)==({'ty_ide','ty_project'}if n=='edit'else set()),'different real compiler/link roster')
        if snapshot:
            library.snapshot(ide,rows,td)
            sess,=actor.work_products('ty_project')-project;reference[n]=objects(sess)
            j={'session':str(sess),'objects':reference[n],'raw':{}}
            for f in ('work-products.bin','dep-graph.bin','query-cache.bin'):
                path=sess/f;need(path.is_file()and 0<path.stat().st_size<1024**3,('bounded retained original',f));j['raw'][f]=old.keep(path)
            put(td/'project-session.json',j);expected[n]=(rows,td)
            if n=='old':
                seed=w.root/'pristine-project';seed.mkdir();dest=seed/sess.parent.name
                need(sum(p.stat().st_size for p in sess.parent.rglob('*')if p.is_file())<2*1024**3,'bounded original')
                original_ide=library.products(rows)['ty_ide']['rlib']
                saved_ide=w.root/'original-ide'/original_ide.name
                saved_ide.parent.mkdir();shutil.copy2(original_ide,saved_ide)
                need(w.hf(saved_ide)==w.hf(original_ide),'preserve genuine prior dependent')
                shutil.copytree(sess.parent,dest,copy_function=shutil.copy2)
                need(bodies(objects(dest/sess.name))==bodies(reference[n]),'changed copied prior')
        if oracle:
            fact['oracle']=library.oracle(rows,env,td,rev);need(fact['oracle']['elf']['sha256']==reg['old_elf'if rev==old.old else'new_elf'],'wrong real client')
        put(td/'result.json',fact);return rows
    phase('old',old.old,snapshot=True);phase('edit',old.new,observe=True,snapshot=True);phase('unchanged',old.new,observe=True,oracle=False)
    need(retained(reference['old'],reference['edit'])==241,'original own edit did not preserve 241/245')
    a,b=(json.loads((w.proof/'ordinary'/n/'native.json').read_bytes())['objects']for n in ('old','edit'));need(retained(a,b)==171,'different actual ty_ide scope')
    a=values(private/'argv');vals=values(private/'environment');e=dict(x.split('=',1)for x in vals);need(len(e)==len(vals)and not any(k in e for k in ('GITHUB_TOKEN','GH_TOKEN','OHM_SDK_READ_TOKEN','RUSTFLAGS','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')),'different or sensitive real compiler environment')
    cwd=Path(scalar(private/'cwd'));compiler=(w.sdk/'bin/rustc').resolve();need(Path(a[0]).samefile(compiler)and a[a.index('--crate-name')+1]=='ty_project','wrong true compiler')
    kernel=json.loads((w.proof/'ordinary/edit/actual-processes.json').read_bytes())['ty_project'];need(a==kernel['argv'],'different real argv')
    put(w.proof/'compiler-contact.json',{'argv':a,'cwd':str(cwd),'exe_sha256':w.hf(compiler),'environment_sha256':w.hf(private/'environment'),'env_names':sorted(e),'real_donor_reuse':241})
    original=a[a.index('--out-dir')+1];inputs={n.split('=',1)[0]:v for i,n in enumerate(a)if i and a[i-1]=='--extern'and '='in n for v in [n.split('=',1)[1]]}
    need(inputs and all(Path(v).is_file()for v in inputs.values()),'missing real --extern bodies')
    input_bytes={n:w.hf(Path(v))for n,v in inputs.items()};put(w.proof/'external-inputs.json',input_bytes)
    failures={};diagnostic={}
    for state,rev in (('edit',old.new),('old',old.old)):
        try:
            old.state(rev);w.guard();td=w.proof/'diagnostic'/state;td.mkdir(parents=True);pr=w.root/('private-'+state);pr.mkdir()
            inc=pr/'incremental';shutil.copytree(w.root/'pristine-project',inc,copy_function=shutil.copy2);srcdir,=inc.iterdir()
            before={p for p in srcdir.glob('s-*')if p.is_dir()and (p/'work-products.bin').is_file()};base,=before;donors=objects(base);need(bodies(donors)==bodies(reference['old']),'private old corpus changed')
            dest=pr/'out';dest.mkdir();prof=td/'profile';prof.mkdir();args=a.copy();out_arg=args.index('--out-dir')+1;args[out_arg]=str(dest)
            ii,=[i for i,x in enumerate(args)if x.startswith('incremental=')and i and args[i-1]=='-C'];args[ii]='incremental='+str(inc)
            args+=['-Zself-profile='+str(prof),*cfg['profile']]
            put(td/'invocation.json',{'argv':args,'changed_indices':[ii,out_arg],'cwd':str(cwd),'flags':cfg['profile'],'inputs':len(inputs),'source':rev})
            rc,pipe=replay(args,e,cwd,td/'compiler.stdout',td/'compiler.stderr');put(td/'return.json',{'code':rc,'jobserver':pipe});need(rc==0,'private rustc returned '+str(rc))
            profiles=list(prof.glob('*.mm_profdata'));need(len(profiles)==1 and 0<profiles[0].stat().st_size<128*1024**2,'wrong self-profile')
            after={p for p in srcdir.glob('s-*')if p.is_dir()and (p/'work-products.bin').is_file()};newsession,=after-before;native=objects(newsession)
            fresh={k for k in donors if any(donors[k][cell]!=native[k][cell]for cell in ('ino','dev','sha256'))}
            need(bodies(native)==bodies(reference[state]),'changed actual native CGU body')
            lib,=dest.glob('libty_project-*.rlib');need(any(lib.name==Path(v).name for x in expected[state][0]if x['target']['name']=='ty_project'for v in x['filenames']),'changed output rlib identity')
            rows=copy.deepcopy(expected[state][0]);row,=[r for r in rows if r['target']['name']=='ty_project'and 'lib'in r['target']['kind']]
            row['filenames']=[str(lib)if v.endswith('.rlib')else v for v in row['filenames']]
            if state=='old':
                ide_row,=[r for r in rows if r['target']['name']=='ty_ide'and 'lib'in r['target']['kind']]
                saved_ide,=(w.root/'original-ide').glob('*.rlib')
                ide_row['filenames']=[str(saved_ide)if v.endswith('.rlib')else v for v in ide_row['filenames']]
            shutil.copyfile(expected[state][1]/'stdout.jsonl',td/'stdout.jsonl');verdict=library.oracle(rows,env,td,rev)
            need(verdict['elf']['sha256']==reg['old_elf'if state=='old'else'new_elf'],'private consumer mismatch')
            need(all(w.hf(Path(v))==input_bytes[n]for n,v in inputs.items()),'input changed during isolated diagnostic')
            diagnostic[state]={'retained':len(donors)-len(fresh),'compiled':sorted(fresh),'actual_profile':old.record_file(profiles[0]),'oracle':verdict,'object_count':len(native),'all_245_equal_ordinary':True,'ordinary_branch':state,'counter_scope_admitted':state=='edit'and fresh=={n for n,v in reference['old'].items()if v['ino']!=reference['edit'][n]['ino']}}
            put(td/'closed.json',diagnostic[state])
        except Exception:
            failures[state]=traceback.format_exc();put(w.proof/('diagnostic-'+state+'-refused.json'),{'error':failures[state]})
    old.state(old.new)
    bad=w.proof/'invalid';bad.mkdir();src=w.work/'crates/ty_ide/src/lib.rs';raw=src.read_bytes()
    try:
        src.write_bytes(raw+b'\nconst _: u8 = "invalid";\n')
        with (bad/'stdout.jsonl').open('xb')as o,(bad/'stderr').open('xb')as err:rc=subprocess.run(actor.want,cwd=w.work,env=env,stdout=o,stderr=err).returncode
        _,out=old.result_rows(bad,False);need(rc==101 and any(q['reason']=='compiler-message' and(q['message'].get('code')or{}).get('code')=='E0308'for q in out),'invalid/clean false success')
    finally:src.write_bytes(raw)
    phase('repair',old.new)
    old.remove_outputs();phase('independent-clean',old.new)
    put(w.proof/'closed.json',{'ordinary':{n:{'source':x['source'],'dirty':len(x['dirty']),'oracle':x.get('oracle',{}).get('elf')}for n,x in ordinary.items()},'diagnostics':diagnostic,'failures':failures})
    need(not failures,'observational diagnostic refused; retain the evidence')
if __name__=='__main__':main()
