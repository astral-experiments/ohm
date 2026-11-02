"""Replay an unwrapped ordinary owner with its original inputs and pre-build incremental files."""
import collections
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
HERE=Path(__file__).resolve().parent;sys.path[:0]=[str(HERE),str(HERE.parent)]
import worker as w
from audit import checked_exec,exec_environment,run,save,sha
from reader_owner import freeze
from ordinary_edges import native_roster
from contact import ar_members

def tree(path):
    return {str(p.relative_to(path)):sha(p) for p in sorted(path.rglob('*')) if p.is_file()}

def clone(source,dest):
    assert source.is_dir() and not dest.exists()
    subprocess.run(['cp','-a','--reflink=auto','--',source,dest],check=True)
    before=tree(source);assert before==tree(dest)
    return before

def inputs(case,state,phase):
    private=w.ROOT/('private-trivia-replay-'+case);private.mkdir()
    if case=='edit':
        previous=json.loads((phase.parent/'old'/'normal-paths.json').read_bytes());binding={}
        for key,path in previous.items():
            source=Path(path);assert source.is_relative_to(state)
            binding[key]=clone(source,private/('prior-'+key))
        save(phase/'prior-files.json',binding)
    return private

def ordinary(trace):
    result=[]
    for record in trace.glob('exec.*'):
        for line in record.read_text(errors='replace').splitlines():
            raw=checked_exec(line)
            if not raw:continue
            exe,argv=raw
            if not exe.endswith('/bin/rustc') or not Path(exe).samefile(w.SDK/'bin/rustc'):continue
            if '--crate-name' in argv and argv[argv.index('--crate-name')+1]=='ruff_python_trivia':
                env=exec_environment(line)
                assert all(x not in env for x in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','LD_PRELOAD','RUSTC_FORCE_RUSTC_VERSION'))
                result.append((argv,env,int(record.suffix[1:])))
    assert len(result)<=1
    return result[0] if result else None

def execute(cmd,env,phase):
    flags=' '.join(env.get(k,'') for k in ('CARGO_MAKEFLAGS','MAKEFLAGS','MFLAGS'))
    pairs={(int(a),int(b)) for a,b in re.findall(r'--jobserver-(?:auth|fds)=(\d+),(\d+)',flags)}
    assert len(pairs)<=1 and 'fifo:' not in flags,(flags,pairs)
    pair=next(iter(pairs),None);backing=[];low=[]
    if pair:
        assert min(pair)>=3 and len(set(pair))==2 and max(pair)<508
        low=os.pipe();os.write(low[1],b'+++')
        backing=[fcntl.fcntl(fd,fcntl.F_DUPFD_CLOEXEC,512) for fd in low]
        for fd in low:os.close(fd)
    with (phase/'replay.stdout').open('xb') as out,(phase/'replay.stderr').open('xb') as err:
        child=os.fork()
        if child==0:
            try:
                os.chdir(w.SRC);os.dup2(out.fileno(),1);os.dup2(err.fileno(),2)
                for source,target in zip(backing,pair or ()):os.dup2(source,target,inheritable=True)
                os.execve(cmd[0],cmd,env)
            except BaseException as e:
                os.write(2,repr(e).encode());os._exit(127)
        for fd in backing:os.close(fd)
        _,status=os.waitpid(child,0)
    assert os.waitstatus_to_exitcode(status)==0,(cmd[:2],status,(phase/'replay.stderr').read_text(errors='replace')[-1900:])
    return child,pair

def collect(case,root,phase,private,trace,dirs,typed_env):
    observed=ordinary(trace)
    if observed is None:return
    argv,env,regular_pid=observed;signed=w.SDK/'bin/rustc'
    assert Path(argv[0]).samefile(signed) and sha(signed)==json.loads((w.LOG/'tools.json').read_bytes())['sha256']['bin/rustc']
    inc_root,=[Path(x.partition('incremental=')[2]) for x in argv if x.startswith(('incremental=','-Cincremental='))]
    inc,=[p for p in inc_root.glob('ruff_python_trivia-*') if p.is_dir()]
    output=Path(argv[argv.index('--out-dir')+1])
    assert inc.is_relative_to(root) and output.is_relative_to(root) and output.parent.parent.name=='ruff_python_trivia' and output.name=='out'
    assert '--crate-type' in argv and argv[argv.index('--crate-type')+1]=='lib' and not any('self-profile' in x for x in argv)
    files={'inc':inc,'out':output};save(phase/'normal-paths.json',{k:str(p) for k,p in files.items()})
    provider,=[Path(x.partition('=')[2]) for x in argv if x.startswith('ruff_source_file=')]
    assert provider.is_relative_to(root) and provider.suffix=='.rmeta'
    original={'argv':argv,'provider_path':str(provider),'provider_sha256':sha(provider),'pid':regular_pid,
              'env_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest(),'env':env}
    prior_sessions={p.parent.name for p in (private/'prior-inc').glob('s-*/dep-graph.bin')}
    regular_graph,=[p for p in inc.glob('s-*/dep-graph.bin') if not p.parent.name.endswith('-working') and p.parent.name not in prior_sessions]
    original['graph_path']=str(regular_graph);original['prior_sessions']=sorted(prior_sessions)
    original['graph']=freeze(regular_graph,phase/'regular-graph.gz')
    save(phase/'original.json',original)
    normal_rlib,=output.glob('libruff_python_trivia-*.rlib')
    before_members=ar_members(normal_rlib)
    save(phase/'native-normal.json',{'rlib':sha(normal_rlib),'members':before_members})
    profiles=private/'profiles';profiles.mkdir()
    for what,p in files.items():
        p.rename(private/('ordinary-'+what))
        if case=='edit':
            (private/('prior-'+what)).rename(p)
        else:p.mkdir()
    try:
        before={p:p.stat().st_ino for p in inc.glob('s-*/dep-graph.bin') if not p.parent.name.endswith('-working')}
        cmd=[*argv,'-Zself-profile='+str(profiles),'-Zself-profile-events=default,query-keys']
        child,fds=execute(cmd,env,phase)
        graph,=[p for p in inc.glob('s-*/dep-graph.bin') if not p.parent.name.endswith('-working') and before.get(p)!=p.stat().st_ino]
        profile,=profiles.glob('*.mm_profdata')
        suffix=profile.stem.rsplit('-',1)[1]
        assert suffix.isdigit() and int(suffix)==child,(profile.name,child)
        rec={'pid':child,'argv':cmd,'rustc':sha(signed),'graph_path':str(graph),'profile_path':str(profile),'cwd':str(w.SRC),
             'regular_pid':regular_pid,'jobserver':fds,'original_env_sha256':original['env_sha256'],'alias':graph.with_name('ohm-build-dep-graph.bin').exists()}
        if rec['alias']:assert sha(graph)==sha(graph.with_name('ohm-build-dep-graph.bin'))
        for name,p in [('graph',graph),('profile',profile),('provider',provider)]:rec[name]=freeze(p,phase/(name+'.gz'))
        save(phase/'process.json',rec);assert rec['provider']['sha256']==original['provider_sha256']
        after_members=ar_members(normal_rlib)
        def objects(m):return [(n,s,h) for n,s,h in m if n.endswith('.o')]
        assert objects(before_members)
        results={'rlib':sha(normal_rlib),'members':after_members,'original_native_equal_in_order':objects(before_members)==objects(after_members),
                 'sorted_original_native_equal':sorted(objects(before_members))==sorted(objects(after_members)),
                 'normalized_names_and_order_and_payloads_equal':native_roster(before_members)==native_roster(after_members)}
        save(phase/'native-replayed.json',results)
        native_equal=results['normalized_names_and_order_and_payloads_equal']
        cmd=['rustc','+ohm','--edition=2024',HERE/'trivia.rs','--extern','ruff_python_trivia='+str(normal_rlib)]
        for d in dirs:cmd+=['-L','dependency='+str(d)]
        exe=private/'typed-replayed';run([*cmd,'-o',exe],typed_env,w.SRC)
        typed=run([exe],typed_env,w.SRC);assert not typed.stderr and typed.stdout==(phase/'ruff_python_trivia-typed.txt').read_bytes()
        (phase/'replayed-typed.txt').write_bytes(typed.stdout)
    finally:
        for what,p in files.items():
            if p.exists():p.rename(private/('replayed-'+what))
            (private/('ordinary-'+what)).rename(p)
    return native_equal
