"""Replay the physical stock Wild at one live input generation with real and controlled jobserver pipes."""
from collections import Counter
from pathlib import Path
import array,ctypes,fcntl,gzip,hashlib,json,os,re,stat,subprocess,sys,termios,time
import audit,libelf_data,elf_container
b=audit.b;w=audit.w;P=audit.P
def sig(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def occupancy(fd):
    value=array.array('i',[0]);fcntl.ioctl(fd,termios.FIONREAD,value,True);return value[0]
def match_pipe(env,pid):
    flags=next(env[n]for n in (b'CARGO_MAKEFLAGS',b'MAKEFLAGS',b'MFLAGS')if n in env)
    choices=re.findall(rb'--jobserver-(?:auth|fds)=(\d+),(\d+)',flags);assert choices and len(set(choices))==1,('unsupported jobserver transport',len(choices))
    ids=list(map(int,choices[0]));assert ids[0]!=ids[1]
    spec=[];opened=[]
    for i,fd in enumerate(ids):
        p=Path('/proc')/str(pid)/'fd'/str(fd);s=p.stat();assert stat.S_ISFIFO(s.st_mode)
        flags=int(re.search(r'^flags:\s*([0-7]+)$',(p.parent.parent/'fdinfo'/str(fd)).read_text(),re.M)[1],8)
        assert flags&3==i
        aux=os.open(p,(os.O_RDONLY,os.O_WRONLY)[i]|os.O_NONBLOCK|os.O_CLOEXEC);t=os.fstat(aux)
        assert (t.st_dev,t.st_ino,t.st_mode)==(s.st_dev,s.st_ino,s.st_mode)
        opened.append(aux);spec.append([fd,s.st_dev,s.st_ino,s.st_mode,flags&3])
    assert spec[0][1:4]==spec[1][1:4];return ids,opened,spec
def group_rows(raw):
    rows=[x.split('\t')for x in raw.decode().splitlines()]
    inputs=[x[1:]for x in rows if x[0]=='RO-INPUT'];groups=[x[1:]for x in rows if x[0]=='RO-GROUP'];typed=[x[1:]for x in rows if x[0]=='TYPED'];assert len(typed)==1 and inputs and groups
    entry=lambda s:int(re.search(r'\bentsize:\s*(\d+)',s)[1])
    by={}
    for group,count,file,section,attrs in inputs:
        group=int(group);assert int(count)>0 and file and section;by.setdefault(group,set()).add(entry(attrs))
    observed=[(int(g),entry(attrs))for g,attrs in groups]
    assert [g for g,_ in observed]==sorted(by) and all(v==(next(iter(by[g]))if len(by[g])==1 else 0)for g,v in observed)
    return {'available_threads':int(typed[0][4]),'group_count':len(groups),'input_sections':sum(map(lambda x:int(x[1]),inputs)),
            'last_group':observed[-1][0],'last_entsize':observed[-1][1],'per_group':observed,'inputs':inputs}
def run(tag,state,stop,stock,llvm,old_ready):
    limit=time.monotonic()+1200
    while time.monotonic()<limit:
        new=set(state.glob('ready-*'))-old_ready
        if new:ready,=new;break
        if stop.is_set():raise ValueError('ordinary command ended before selected Wild')
        time.sleep(.01)
    else:raise TimeoutError('ordinary Wild never entered')
    pid=int(ready.name[6:]);assert ready.read_bytes()==b'complete\n'
    actor=state/('actor-'+str(pid)+'.tsv');view,argv=audit.bound_inputs.receive(actor.read_text())
    env_path=state/('local-env-'+str(pid));pairs=[x.split(b'=',1)for x in env_path.read_bytes().rstrip(b'\0').split(b'\0')];env=dict(pairs);assert len(env)==len(pairs)
    assert not any(x in env for x in (b'LD_PRELOAD',b'LD_AUDIT',b'WILD_LOG',b'OHM_QA_GROUPS_CHILD'))
    cwd=Path('/proc')/str(pid)/'cwd';cwd=cwd.resolve();assert str(cwd)==json.loads(view['context']['CWD'][0][0])
    cpus=sorted(os.sched_getaffinity(pid));assert cpus
    flags=next(env[n]for n in (b'CARGO_MAKEFLAGS',b'MAKEFLAGS',b'MFLAGS')if n in env)
    scopes=re.findall(rb'--jobserver-(?:auth|fds)=(\d+),(\d+)',flags);assert scopes and len(set(scopes))==1
    ids=list(map(int,scopes[0]));source_fds=[];real=();missing=None
    observed={}
    for fd in ids:
        path=Path('/proc')/str(pid)/'fd'/str(fd)
        try:
            item=path.stat();observed[str(fd)]=[item.st_dev,item.st_ino,item.st_mode,os.readlink(path)if stat.S_ISFIFO(item.st_mode) else None]
        except FileNotFoundError:observed[str(fd)]=None
    try:_,real,source_fds=match_pipe(env,pid)
    except (OSError,AssertionError) as bad:missing=repr(bad)
    b.write(P/(tag+'-physical-original-descriptors.json'),{'pid':pid,'argv':argv,'expected_pipe_fds':ids,'accepted_original':bool(real),'source_fds':source_fds,'roles':observed,'failure':missing,'affinity':cpus})
    frozen=[r.split('\t')[1:]for r in actor.read_text().splitlines()if r.startswith('FROZEN\t')]
    assert len(frozen)==409
    def validate_native():
        rows=[]
        for dev,ino,size,dig,name in frozen:
            path=Path(name);before=path.stat();assert [before.st_dev,before.st_ino,before.st_size]==list(map(int,(dev,ino,size)))
            assert audit.donor.full_b3(path)==dig and sig(before)==sig(path.stat());rows.append([name,sig(before),dig])
        return rows
    inputs=validate_native();b.write(P/(tag+'-409-live-inputs.json.gz'),inputs)
    primary_threads=int(view['context']['TYPED'][0][4]);assert 1<=primary_threads<=4
    series=[('real-first',0,'stock','real',None),('no-fds',0,'stock','closed',None)]
    for j,n in enumerate([1,2,2,1]):
        series.append(('tokens-'+str(j)+'-'+str(n),n,'stock','private',None))
    series+= [('one-trace',1,'stock','private','trace'),('two-trace',2,'stock','private','trace'),
              ('one-explicit',1,'stock','private','override'),('two-explicit',2,'stock','private','override'),
              ('native-one',1,'source','private',None),('native-two',2,'source','private',None),('real-trace',0,'stock','real','trace'),('real-last',0,'stock','real',None)]
    if not real:series=[x for x in series if x[3]!='real']
    if primary_threads not in (1,2):series.append(('exact-source-count',primary_threads,'stock','private',None))
    assert time.monotonic()<limit
    rows={};seen_child_logs=set()
    try:
        for name,n,kind,mode,diag in series:
            token_pair=real if mode=='real'else(os.pipe() if mode=='private'else())
            if mode=='private'and n>1:assert os.write(token_pair[1],b'+'*(n-1))==n-1
            try:
                inherited=token_pair if mode!='closed'else()
                spec=[[ids[i],os.fstat(f).st_dev,os.fstat(f).st_ino,os.fstat(f).st_mode,fcntl.fcntl(f,fcntl.F_GETFL)&3]for i,f in enumerate(inherited)]
                if mode=='real':assert spec==source_fds
                pre=occupancy(inherited[0])if inherited else None
                x=list(argv)
                if diag=='override':x.append('--threads='+str(n))
                mapping=dict(env)
                if diag=='trace':mapping[b'WILD_LOG']=b'libwild::args=trace,wild::args=trace'
                if kind=='source':mapping[b'OHM_QA_GROUPS_CHILD']=b'1'
                executable=stock if kind=='stock'else Path(argv[0])
                inside=state/(tag+'-'+name+'-received.json');plan=state/(tag+'-'+name+'-fd-plan.json')
                data={'argv':x,'executable':str(executable),'cpus':cpus,'jobserver':ids,'replace_fds':bool(inherited),'expected_fds':spec,'delivered':str(inside)}
                plan.write_text(json.dumps(data))
                prior=set(state.glob('actor-*.tsv'));cmd=[sys.executable,'-IB',str(audit.H/'group_exec.py'),str(plan),*map(str,inherited)]
                begin=time.monotonic_ns();p=subprocess.Popen(cmd,cwd=cwd,env=mapping,pass_fds=tuple(inherited),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                levels=[];deadline=time.monotonic()+100
                while p.poll()is None:
                    if time.monotonic()>deadline:p.kill();p.wait();raise TimeoutError(name)
                    if inherited:levels.append(occupancy(inherited[0]))
                    time.sleep(.002)
                so,se=p.communicate();assert p.returncode==0,(tag,name,p.returncode,se[-1000:])
                output=so+se;signed_token_read=None;normalized=re.sub(rb'\x1b\[[0-9;]*m',b'',output)
                if diag=='trace':
                    line=next((line for line in normalized.splitlines()if b'Acquired jobserver tokens'in line),None)
                    if line is not None:
                        signed_token_read=int(re.search(rb'\bcount=(\d+)',line)[1])
                        if mode=='private':assert signed_token_read==n-1,(name,line)
                else:assert not output,(name,output[:600])
                if mode=='private' and n>1 and diag!='override':assert levels and min(levels)==0,(name,n,levels[:20])
                post=occupancy(inherited[0])if inherited else None
                if mode=='private':assert pre==post==n-1,(name,pre,post)
                container=elf_container.inspect(Path(argv[19]),llvm);sec=next(s for s in container['sections']if s['section']=='.rodata')
                value={'sha256':container['sha256'],'argv_sha256':hashlib.sha256(b'\0'.join(os.fsencode(v)for v in x)).hexdigest(),'source':kind,'mode':mode,'token_pre':pre,'token_post':post,'minimum_observed_tokens':min(levels)if levels else None,'maximum_observed_tokens':max(levels)if levels else None,'signed_trace_token_count':signed_token_read,'affinity':cpus,'delivered':json.loads(inside.read_bytes()),'controlled_threads':n,'requested_diagnostic':diag,'elapsed_ns':time.monotonic_ns()-begin,'entsize':sec['header'][9],'rodata_bytes':sec['header'][5],'libelf':libelf_data.inspect(argv[19],sec['index']),'trace':output.decode()if diag=='trace'else None}
                if name in ('tokens-0-1','tokens-1-2'):
                    strip=subprocess.run(['eu-strip','-o','/dev/null',argv[19]],cwd=cwd,capture_output=True,timeout=30)
                    value['elfutils_strip']={'exit':strip.returncode,'stderr':strip.stderr.decode(errors='replace'),'stdout':strip.stdout.decode(errors='replace'),
                                             'version':subprocess.check_output(['eu-strip','--version'],text=True).splitlines()[0]}
                    assert w.hf(Path(argv[19]))==container['sha256']
                aux=set(state.glob('actor-*.tsv'))-prior
                if kind=='source':
                    child,=aux;seen_child_logs.add(child.name);body=child.read_bytes();value['groups']=group_rows(body)
                    assert value['groups']['available_threads']==n and value['groups']['last_entsize']==value['entsize']
                    (P/(tag+'-'+name+'-native.tsv.gz')).write_bytes(gzip.compress(body,mtime=0))
                else:assert not aux
                b.write(P/(tag+'-'+name+'-elf.json.gz'),container);b.write(P/(tag+'-'+name+'-role.json'),value);rows[name]=value
            finally:
                if mode=='private':
                    for fd in token_pair:os.close(fd)
        for n in (1,2):
            got={v['sha256']for v in rows.values()if v['controlled_threads']==n}
            assert len(got)==1,('same-token/explicit/source disagreed',tag,n,got)
        assert rows['tokens-0-1']['sha256']!=rows['tokens-1-2']['sha256'],('thread hypothesis not reproduced',tag)
        assert validate_native()==inputs
        return {'inherited_real_transport_refusal':missing,'pid':pid,'actor_file':actor.name,'auxiliary_logs':sorted(seen_child_logs),'rows':rows,'primary_threads':primary_threads,
                'raw_jobserver':source_fds,'cpus':cpus,'role':view}
    finally:
        for fd in real:os.close(fd)
        reply=state/('answer-'+str(pid));tmp=reply.with_suffix('.next');tmp.write_text('full\n');tmp.rename(reply)
