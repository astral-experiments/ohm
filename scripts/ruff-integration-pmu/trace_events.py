"""Certify original exec argv against raw kernel stops on the four unmeasured preparations."""
from collections import Counter, defaultdict
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'branch-return-pmu'))
import worker as w

# A terminal task without an EXEC stop can have an undecodable entry or resume
# while its thread group exits. Never infer a path from its pointer values.
PREFIX=re.compile(rb"^(\d+)\s+(.*)\n$")
SYSCALL=re.compile(rb"^(?:execve(?:at)?\(|\?\?\?\(|<\.\.\. (?:execve(?:at)?|\?\?\?) resumed>)")
WAIT=re.compile(rb'^(?:/usr/bin/)?strace: \[wait\(0x([0-9a-f]+)\) = ([0-9]+)\] (.+)\n$')
NEW=re.compile(rb'^(?:/usr/bin/)?strace: new tcb for pid ([0-9]+), active tcbs:[0-9]+\n$')
DROP=re.compile(rb'^(?:/usr/bin/)?strace: dropped tcb for pid ([0-9]+), ([0-9]+) remain\n$')
OPTIONS=re.compile(rb'^(?:/usr/bin/)?strace: ptrace_setoptions = 0x([0-9a-f]+)\n$')
SHELL='/bin/sh'
SHELL_PROGRAM='error_file=$1; shift; exec 2>"$error_file"; exec "$@"'

def need(ok,reason):
    if not ok:raise ValueError(str(reason))

def compact(source,destination):
    with source.open('rb') as f, destination.open('xb') as out,gzip.GzipFile(filename='',mode='wb',fileobj=out,mtime=0,compresslevel=2) as gz:
        shutil.copyfileobj(f,gz,2**20)
    source.unlink()

def parse(raw,debug):
    new=Counter();drops=Counter();finals=defaultdict(list);commits=Counter();hard_stops=Counter();flags=[];remaining=None
    for line in debug:
        if m:=OPTIONS.fullmatch(line):flags.append(int(m[1],16));continue
        if m:=NEW.fullmatch(line):new[int(m[1])]+=1;continue
        if m:=DROP.fullmatch(line):drops[int(m[1])]+=1;remaining=int(m[2]);continue
        if b'[wait(' not in line:
            need(not any(text in line for text in (b'Stray PTRACE_EVENT_EXEC',b'PTRACE_SETOPTIONS:',b'PTRACE_DETACH:',b'wait4(__WALL):')),
                 ('tracer could not follow an image',line[:300]));continue
        m=WAIT.fullmatch(line);need(m,('invalid raw wait status',line[:180]));status,pid=int(m[1],16),int(m[2]);label=m[3]
        if os.WIFSTOPPED(status):
            if status>>16==4:
                need(os.WSTOPSIG(status)==signal.SIGTRAP and label==b'WIFSTOPPED,sig=SIGTRAP,EVENT_EXEC (4)','inconsistent kernel EXEC record')
                commits[pid]+=1
            else:
                need(b'EVENT_EXEC' not in label,'spurious kernel EXEC label')
                if status>>16==128:hard_stops[pid]+=1
        elif os.WIFEXITED(status):
            n=os.WEXITSTATUS(status);need(label==f'WIFEXITED,exitcode={n}'.encode(),'conflicting final exit');finals[pid].append(n)
        elif os.WIFSIGNALED(status):
            need(label.startswith(b'WIFSIGNALED,'),'conflicting terminal wait signal');finals[pid].append(-os.WTERMSIG(status))
        else:raise ValueError(('unsupported raw GNU wait',status,label))
    # TRACEFORK, TRACEVFORK, TRACECLONE, TRACEEXEC and TRACEEXIT are required. Every
    # allocated task must have one real terminal wait. Do not accept an early detach.
    need(len(flags)==1 and flags[0]&0x5e==0x5e and len(new)>0 and new==drops and remaining==0 and
         all(v==1 for v in new.values()) and set(new)==set(finals) and all(len(v)==1 for v in finals.values()),'incomplete tracer task lifetimes')
    original=list(raw);indexed=defaultdict(list)
    for line in original:
        m=PREFIX.fullmatch(line);need(m,('unowned or truncated strace line',line[:160]))
        if SYSCALL.match(m[2]):
            pid=int(m[1]);need(pid in new,('syscall for unknown task',pid));indexed[pid].append(line)
    quarantined={}
    for pid,lines in indexed.items():
        opaque=any(b'???' in line or b'<detached ...>' in line for line in lines)
        try:
            decoded=w.processes.execs(io.StringIO(b''.join(lines).decode('utf-8')))
        except (AssertionError,ValueError):
            opaque=True;decoded=None
        if not opaque:continue
        # Both sources remain intact. Refuse missing or inconsistent argv for any
        # task with an actual installed image, unknown lifetime or successful exec.
        need(not decoded and not commits[pid] and hard_stops[pid] and finals[pid][0]>=0,
             ('uncertain syscall in an executing, unenrolled or killed task',pid))
        for row in lines:
            text=PREFIX.fullmatch(row)[2]
            explicit_error=re.search(rb'\)\s+= -1 (?:[A-Z][A-Z0-9_]+(?: \(.*\))?|\(errno [0-9]+\))$',text)
            incomplete=(text.endswith((b'<detached ...>',b'<unfinished ...>')) or re.search(rb'\)\s+= \?(?: <unavailable>)?$',text))
            need(explicit_error or incomplete,('non-error syscall in kernel-uncommitted task',pid,row[:260]))
        quarantined[pid]={'terminal':finals[pid][0],'kernel_exec_events':0,'initial_stops':hard_stops[pid],
                          'opaque_task_syscall_rows':len(lines),'original_rows_sha256':hashlib.sha256(b''.join(lines)).hexdigest()}
    keep=[]
    for line in original:
        m=PREFIX.fullmatch(line)
        if int(m[1]) not in quarantined or not SYSCALL.match(m[2]):keep.append(line)
    normalized=b''.join(keep);success=w.processes.execs(io.StringIO(normalized.decode('utf-8')))
    need(commits==Counter(pid for pid,exe,argv in success) and set(commits)<=set(new) and sum(commits.values())>0,
         'kernel installed image without exactly one fully decoded successful syscall, or vice versa')
    return normalized,{'waited_tasks':len(new),'installed_images':sum(commits.values()),'installed_pids':len(commits),
                       'supplied_argv_sha256':hashlib.sha256(normalized).hexdigest(),
                       'noninstalled_terminal_tasks':{str(p):v for p,v in sorted(quarantined.items())}}



def capture(argv,env,cwd,where,timeout=2400,record=None):
    raw=where/'strace.raw'; dbg=where/'ptrace-waits';err=where/'child.stderr'
    # The shell replaces itself with the actual command. Only the shell and its children
    # get the child stderr. The kernel wait ledger is written by strace to a separate FD.
    args=['/usr/bin/strace','-d','-f','-qq','--seccomp-bpf','-s','262144','-e','trace=execve,execveat','-o',str(raw),'--',
          SHELL,'-c',SHELL_PROGRAM,'ohm-separate-stderr',str(err),*map(str,argv)]
    need(not any(p.exists() for p in (raw,dbg,err,where/'exec.raw')),'existing trace output')
    with dbg.open('xb') as log:
        result=subprocess.run(args,cwd=cwd,env=env,input=b'',stdout=subprocess.PIPE,stderr=log,timeout=timeout)
    stderr=err.read_bytes()
    if record is not None:record(result.returncode,result.stdout,stderr,args)
    try:
        with raw.open('rb') as r,dbg.open('rb') as d:normalized,proof=parse(r,d)
        rows=w.processes.execs(io.StringIO(normalized.decode()))
        need(rows[0][1:]==(SHELL,args[args.index(SHELL):]) and len(rows)>1,'missing real control shell')
        (where/'exec.raw').write_bytes(normalized)
        w.b.save(where/'kernel-commits.json',proof|{'syscall_sha256':w.b.sha(raw),'kernel_sha256':w.b.sha(dbg),'observer_argv':args})
    finally:
        if raw.is_file():compact(raw,where/'strace.raw.gz')
        if dbg.is_file():compact(dbg,where/'ptrace-waits.gz')
    return result.returncode,result.stdout,stderr,args


def reference(where,env,lane,rc,arm):
    need(lane=='structural' and rc==0,'kernel witness only on uncounted genuine clean references')
    def record(code,stdout,stderr,observer):
        # Preserve the real Cargo verdict even if subsequent independent task/argv
        # reconciliation refuses. The measured invocation never calls this adapter.
        for k,data in (('stdout',stdout),('stderr',stderr)):
            (where/f'cargo.{k}.gz').write_bytes(gzip.compress(data,compresslevel=2,mtime=0))
        w.publish(where/'cargo.json.gz',dict(argv=w.CARGO,observer_argv=observer,cwd=str(w.kit.TREE),env=env,expected=0,exit=code,
                 stdin_sha256=w.digest(b''),stdout_sha256=w.digest(stdout),stderr_sha256=w.digest(stderr)))
    code,stdout,stderr,observer=capture(w.CARGO,env,w.kit.TREE,where,record=record)
    (where/'child.stderr').unlink()
    need(code==0,('real empty Cargo failed',code))
    try:
        phys=w.processes.inventory(where/'exec.raw',arm)
        need(phys['cargos'][0]['argv'][1:]==w.CARGO[2:],'wrong actual Cargo exec');w.publish(where/'native-execs.json.gz',phys)
    finally:w.processes.compact(where/'exec.raw',where/'exec.raw.gz')
    rows=list(map(json.loads,stdout.splitlines()))
    need(rows[-1]=={'reason':'build-finished','success':True} and not any(m['reason']=='compiler-message' and m['message']['level']=='error' for m in rows),'wrong empty Cargo stream')
    return rows,None,phys


def checked_replay(where):
    proof=json.loads((where/'kernel-commits.json').read_bytes())
    with gzip.open(where/'strace.raw.gz','rb') as a:raw=a.read()
    with gzip.open(where/'ptrace-waits.gz','rb') as a:debug=a.read()
    normalized,rebuilt=parse(io.BytesIO(raw),io.BytesIO(debug))
    need(all(proof[k]==v for k,v in rebuilt.items()) and hashlib.sha256(raw).hexdigest()==proof['syscall_sha256'] and
         hashlib.sha256(debug).hexdigest()==proof['kernel_sha256'],'different native raw trace or reconciliation')
    if (where/'exec.raw.gz').exists():
        with gzip.open(where/'exec.raw.gz','rb') as f:need(normalized==f.read(),'normalized argv provenance')
    else:need(normalized==(where/'exec.raw').read_bytes(),'calibration normalized argv provenance')
    return rebuilt,normalized,debug


def controls(where):
    proof,normalized,debug=checked_replay(where)
    rows=w.processes.execs(io.StringIO(normalized.decode('utf-8')))
    need([r[1] for r in rows]==['/bin/sh','/bin/sh','/bin/false','/bin/true','/usr/bin/printf'] and
         len({x[0] for x in rows})==3 and proof['installed_images']==5,'actual successful images in calibration')
    # The command emits a fake tracer-looking line on its stderr. Only the tracer
    # has the wait-ledger descriptor, so tracee output cannot pass as kernel data.
    need((where/'child.stderr').read_bytes()==b'/usr/bin/strace: [wait(0x04057f) = 1] false-in-child\n' and
         b'false-in-child' not in debug,'tracee stderr mixed into the kernel channel')
    return proof


def calibrate(where):
    where.mkdir()
    version=subprocess.check_output(['/usr/bin/strace','-V']).decode().splitlines()[0]
    need(version.endswith('version 6.8'),('unsupported tracer version',version))
    code,out,err,_=capture(['/bin/sh','-c','printf "/usr/bin/strace: [wait(0x04057f) = 1] false-in-child\\n" >&2; /bin/false; /bin/true; exec /usr/bin/printf "genuine result\\n"'],
                           {"PATH":"/usr/bin:/bin","LC_ALL":"C"},where,where,20)
    need(code==0 and out==b'genuine result\n','native calibration exit or bytes');proof=controls(where)
    w.b.save(where/'calibration.json',{'version':version,'strace_sha256':w.b.sha('/usr/bin/strace'),'proof':proof})
