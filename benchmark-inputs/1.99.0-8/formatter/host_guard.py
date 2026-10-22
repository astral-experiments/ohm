"""Record host activity and reject benchmark runs that overlap unrelated work."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

COMPILERS = {'cargo','cargo-nextest','nextest','rustc','rustdoc','rustfmt','cargo-fmt','clippy-driver','rust-lld','ld','ld.bfd','ld.lld','clang','clang++','cc1','cc1plus','wild','ninja','cmake','make','cc','gcc','g++'}
MINIMUM_FREE = 60 * 1024**3

def overlap_observation(rows, owned):
    tests = []
    for pid in owned:
        if pid not in rows or rows[pid]['state'] == 'Z':
            continue
        try:
            executable = os.readlink(f'/proc/{pid}/exe')
        except (OSError, ProcessLookupError):
            continue
        if executable.startswith('/tmp/codex-cargo-targets/ohm/isolated/release-1.99.0-8/') and '/deps/' in executable:
            tests.append({'pid':pid, 'name':rows[pid]['name'], 'executable':executable})
    test_descendants = set()
    for test in tests:
        test_descendants |= descendants(rows, test['pid'])
    compilers = [
        {'pid':pid, 'name':rows[pid]['name']}
        for pid in owned - test_descendants
        if pid in rows and rows[pid]['state'] != 'Z' and rows[pid]['name'] in {
            'rustc','rustdoc','clippy-driver','rust-lld','ld','ld.bfd','ld.lld',
            'clang','clang++','cc1','cc1plus','wild','cc','gcc','g++',
        }
    ]
    return {'tests':tests, 'compilers_outside_test_process_trees':compilers,
            'simultaneous':bool(tests and compilers), 'sampling_interval_seconds':2}

def snapshot():
    rows = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            raw = path.read_text(); left = raw.index('('); right = raw.rindex(')'); fields = raw[right+2:].split()
            rows[int(path.parent.name)] = {'parent':int(fields[1]),'name':raw[left+1:right], 'ticks':int(fields[11])+int(fields[12]), 'start':fields[19], 'state':fields[0], 'group':int(fields[2]), 'session':int(fields[3]), 'uid':path.parent.stat().st_uid, 'cgroup':(path.parent/'cgroup').read_text().strip()}
        except (FileNotFoundError, ProcessLookupError):
            continue
    if not rows: raise RuntimeError('Cannot inspect host processes')
    cpu = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return {'processes':rows, 'cpu':cpu, 'monotonic':time.monotonic(), 'time':time.time()}

def descendants(rows, owner):
    owned = {owner}
    while True:
        children = {p for p,v in rows.items() if v['parent'] in owned}
        if children <= owned: return owned
        owned |= children

def interval(before, after, owned):
    rows = after['processes']; prior = before['processes']; elapsed = after['monotonic'] - before['monotonic']
    contributors = []
    for pid,v in rows.items():
        if pid in owned or pid not in prior or prior[pid]['start'] != v['start']: continue
        ticks = max(0,v['ticks']-prior[pid]['ticks'])
        if ticks: contributors.append({'pid':pid, **v, 'cpu_ticks':ticks})
    contributors.sort(key=lambda v:v['cpu_ticks'],reverse=True)
    scale = os.sysconf('SC_CLK_TCK') * elapsed * os.cpu_count()
    def fraction(predicate):return sum(v['cpu_ticks'] for v in contributors if predicate(v)) / scale
    security = lambda v:v['uid']==0 and v['name'].startswith('falcon-sensor')
    delta = [b-a for a,b in zip(before['cpu'],after['cpu'])];total = sum(delta)
    if elapsed<=0 or total<=0: raise RuntimeError('Invalid CPU sampling interval')
    return {'time':after['time'],'interval_seconds':elapsed,'global_cpu_ticks_before':before['cpu'],'global_cpu_ticks_after':after['cpu'],'logical_cpu_count':os.cpu_count(),'clock_ticks_per_second':os.sysconf('SC_CLK_TCK'),'benchmark_uid':os.getuid(),'idle_fraction':delta[3]/total,'iowait_fraction':delta[4]/total,'steal_fraction':delta[7]/total,
        'external_user_cpu_fraction':fraction(lambda v:v['uid']==os.getuid()),'external_nonsecurity_cpu_fraction':fraction(lambda v:not security(v)),
        'external_cpu_fraction':fraction(lambda v:True),'external_cpu_contributors':contributors,
        'competing_processes':[{'pid':p,**v} for p,v in rows.items() if p not in owned and v['state']!='Z' and v['name'] in COMPILERS]}

def quiet(root, receipt):
    import shutil
    samples=[]; before=snapshot()
    for _ in range(6):
        time.sleep(5);after=snapshot();s=interval(before,after,descendants(after['processes'],os.getpid()));s['free_bytes']=shutil.disk_usage(root).free;samples.append(s);before=after
        receipt.write_text(json.dumps({'samples':samples,'passed':False},indent=2)+'\n')
        if s['idle_fraction']<.95 or s['iowait_fraction']>.005 or s['steal_fraction']>.001 or s['competing_processes'] or s['free_bytes']<MINIMUM_FREE:
            raise RuntimeError('Host did not pass the quiet preflight; retained telemetry')
    receipt.write_text(json.dumps({'samples':samples,'passed':True},indent=2)+'\n')

def run(command, *, env, cwd, output, receipt):
    import shutil
    before=snapshot();failures=[];groups=set();sessions=set();streak=0;count=0
    process=subprocess.Popen(command,env=env,cwd=cwd,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    groups.add(process.pid);sessions.add(process.pid)
    try:
        with receipt.open('x') as trace:
            while True:
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired: pass
                after=snapshot();rows=after['processes'];owned=descendants(rows,process.pid)
                groups.update(rows[p]['group'] for p in owned if p in rows);sessions.update(rows[p]['session'] for p in owned if p in rows)
                owned|={p for p,v in rows.items() if v['group'] in groups or v['session'] in sessions};owned.add(os.getpid())
                s=interval(before,after,owned);s['free_bytes']=shutil.disk_usage(cwd).free;s['runner_running']=process.poll() is None
                s['test_build_overlap']=overlap_observation(rows,owned)
                streak=streak+1 if s['external_nonsecurity_cpu_fraction']>.05 else 0
                reasons=[]
                if s['competing_processes']:reasons.append('unrelated compiler')
                if s['external_user_cpu_fraction']>.05:reasons.append('unrelated same-user CPU above 5%')
                if streak>=3:reasons.append('unrelated nonsecurity CPU above 5% for three intervals')
                if s['free_bytes']<MINIMUM_FREE:reasons.append('free space below 60 GiB')
                s['violations']=reasons;trace.write(json.dumps(s)+'\n');trace.flush();count+=1
                if reasons:failures.append(s);raise RuntimeError('Host activity invalidated this suite: '+', '.join(reasons))
                if process.poll() is not None:break
                before=after
    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=30)
            except subprocess.TimeoutExpired:raise RuntimeError('Benchmark did not stop; inspect its own process group')
        proof={'passed':not failures and process.returncode==0,'violations':failures,'samples':count,'returncode':process.returncode,'monitor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'trace_sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
        receipt.with_suffix('.json').write_text(json.dumps(proof,indent=2)+'\n')
    if process.returncode:raise subprocess.CalledProcessError(process.returncode,command)
