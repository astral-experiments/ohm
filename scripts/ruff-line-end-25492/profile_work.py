"""Capture disjoint instruction samples and call chains after restoring Cargo's environment."""
from collections import Counter
import gzip
import os
from pathlib import Path
import re
import shutil
import subprocess

from audit import run,save,sha

PERIOD=2500003
ROW=re.compile(rb'\s*(\d+)\s+(\d+)\s+([0-9a-fA-F]+)\s+(.+?)\s+\((.*)\)\s*')
SPAWN=re.compile(r'^(?:(?:clone3?|fork|vfork)\(|<\.\.\. (?:clone3?|fork|vfork) resumed>).* = ([1-9][0-9]*)$')


def record(perf,data,env):
    return [str(perf),'record','--no-buildid-cache','-q','-e','instructions:u','-c',str(PERIOD),'-P','--call-graph','dwarf,4096','-o',str(data),'--',
            '/usr/bin/env','-i',*(k+'='+v for k,v in sorted(env.items()))]


def select(env,private):
    paths=sorted(Path('/usr/lib/linux-tools').glob('*/perf'))
    for i,perf in enumerate(reversed(paths)):
        raw=private/('profile-probe-'+str(i)+'.data')
        cmd=[*record(perf,raw,env),private/'loop','0','30000000','1']
        if run(cmd,env,private,exact=None).returncode:continue
        args=[perf,'script','-G','--no-demangle','-i',raw,'-F','pid,period,ip,sym,dso']
        p=run(args,env,private,exact=None)
        rows=[ROW.fullmatch(l) for l in p.stdout.splitlines() if l.strip()]
        if p.returncode==0 and len(rows)>=10 and all(v and int(v[2])==PERIOD for v in rows) and sum(v[5].endswith(b'/loop') for v in rows)>=6:
            return perf
    raise AssertionError('no hardware instruction sampler matched the arithmetic native control')


def tool_state(sdk,private,env):
    # Re-opening for stat does not add directory entries or change inode ctime.
    candidates=set(sdk.joinpath('bin').glob('*'))|set(sdk.joinpath('lib').glob('*.so*'))
    for directory in sdk.joinpath('lib/rustlib').glob('*/bin'):
        candidates.update(p for p in directory.rglob('*') if p.is_file())
    candidates.update(private.joinpath('proxies').glob('*'))
    for n in ('cc','c++','gcc','g++','ar','as','ld','ld.bfd','ranlib','nm','strip','objcopy','objdump','clang','clang++','pkg-config','cmake','make','ninja','sh','git','rustup','rustdoc','cargo','rustc'):
        p=shutil.which(n,path=env['PATH'])
        if p:candidates.add(Path(p))
    state={}
    for p in sorted(candidates):
        if not p.is_file():continue
        st=p.stat()
        state[str(p)]={'dev':st.st_dev,'ino':st.st_ino,'nlink':st.st_nlink,'size':st.st_size,'ctime_ns':st.st_ctime_ns,'mtime_ns':st.st_mtime_ns}
    return state


def parents(trace):
    mapping={}
    for f in trace.glob('exec.*'):
        parent=int(f.suffix[1:])
        with f.open(errors='replace') as q:
            for line in q:
                m=SPAWN.match(line.rstrip())
                if m:
                    child=int(m[1])
                    assert child not in mapping or mapping[child]==parent
                    mapping[child]=parent
    return mapping


def write(folder,private,env,perf,trace,procs,links,ordinary_clock):
    profile=private/'edit.data'
    assert 0<profile.stat().st_size<=256<<20
    cmd=[perf,'script','-G','--no-demangle','-i',profile,'-F','pid,period,ip,sym,dso']
    p=run(cmd,env,private,exact=None)
    (folder/'sample-stderr.txt').write_bytes(p.stderr)
    with gzip.open(folder/'primary-samples.txt.gz','wb',compresslevel=3) as f:f.write(p.stdout)
    pids={};owners={r['pid']:r['crate'] for r in procs};wild={r['pid'] for r in links};ancestors=parents(trace)
    counts=Counter();n=0;invalid=[]
    for l in p.stdout.splitlines():
        if not l.strip():continue
        m=ROW.fullmatch(l)
        if not m or int(m[2])!=PERIOD:
            invalid.append(l[:200].decode(errors='replace'));continue
        n+=1;pid=int(m[1])
        if pid not in pids:
            path=[pid]
            while path[-1] in ancestors:
                pp=ancestors[path[-1]]
                assert pp not in path
                path.append(pp)
            if any(i in wild for i in path):label='Wild'
            elif pid in owners:label='rustc '+owners[pid]
            elif any(i in owners for i in path):label='child of rustc '+next(owners[i] for i in path if i in owners)
            else:label='other'
            pids[pid]=label
        counts[pids[pid]]+=1
    chain=[str(x) for x in cmd if x!='-G']
    with gzip.open(folder/'stack-samples.txt.gz','wb',compresslevel=3) as out,(folder/'stack-stderr.txt').open('wb') as err:
        with subprocess.Popen(chain,env=env,cwd=private,stdout=subprocess.PIPE,stderr=err) as proc:
            shutil.copyfileobj(proc.stdout,out);ret=proc.wait(timeout=900)
    with profile.open('rb') as source,gzip.open(folder/'physical.perf.data.gz','wb',compresslevel=2) as fout:shutil.copyfileobj(source,fout)
    coverage=n*PERIOD/ordinary_clock
    verdict=p.returncode==ret==0 and not invalid and b'lost' not in p.stderr.lower() and .90<=coverage<=1.05
    save(folder/'sample-ledger.json',{'qualifies':verdict,'raw_sha256':sha(profile),'samples':n,'period':PERIOD,'invalid':invalid[:8],'invalid_count':len(invalid),
         'coverage':coverage,'native_roster':dict(owners),'wild':sorted(wild),'owner_sample_counts':dict(counts),'pid_owner':pids,'parents':ancestors,
         'clock_in_profiled_child':ordinary_clock,'primary_returncode':p.returncode,'stack_returncode':ret})
    return verdict
