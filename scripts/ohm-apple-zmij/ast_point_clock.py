"""Time one endpoint per independent installation. The combined pair has no observer between Cargos."""
import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

from calibrate import fields
from cgu_inputs import witness
from local_incremental import environment_receipt, preparation
from measure import capture, fresh, phase as library_phase, products, retire, select, typed
from study import ARGS, change_source, check_host, compress_bytes, env_for, need, save, sdk_id, source_values
import verbs

POINTS=('edit-plus-repeat','edit','repeat-1','repeat-2')


def combined(argv, repo, env, out):
    samples=(out/'edit',out/'repeat-1')
    for d in samples:d.mkdir(parents=True)
    timer=out/'combined-time.txt'
    with contextlib.ExitStack() as stack:
        logs=[stack.enter_context(tempfile.TemporaryFile()) for _ in range(4)]
        later=[f.fileno() for f in logs[2:]]
        need(all(2<fd<10 for fd in later),'unsupported POSIX shell output descriptor')
        script=f'"$@" && exec "$@" >&{later[0]} 2>&{later[1]}'
        cmd=['/usr/bin/time','-l','-o',str(timer),'/bin/sh','-c',script,'ordinary-cargo',*argv]
        proc=None
        expired=threading.Event()
        def timeout():
            expired.set()
            if proc is not None:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
        watchdog=threading.Timer(1200,timeout);watchdog.start()
        try:
            start=time.monotonic_ns()
            proc=subprocess.Popen(cmd,cwd=repo,env=env,stdout=logs[0],stderr=logs[1],pass_fds=later,start_new_session=True)
            status=proc.wait();stop=time.monotonic_ns()
        finally:watchdog.cancel()
        need(not expired.is_set(),'combined ordinary Cargo watchdog expired')
        for f in logs:f.seek(0)
        chunks=[f.read() for f in logs]
    readings={'ns':stop-start,'start_ns':start,'stop_ns':stop,**fields(timer.read_text())}
    save(out/'combined.json',{'shell':script,'argv':argv,'exit':status,'clock':readings,'intermediate_native_reference':False})
    results=[]
    for i,d in enumerate(samples):
        stdout,stderr=chunks[2*i:2*i+2]
        streams={'stdout':compress_bytes(d/'stdout.gz',stdout),'stderr':compress_bytes(d/'stderr.gz',stderr)}
        results.append((0,stdout,stderr,None,{'streams':streams}))
    need(status==0 and all(chunks[i] for i in (0,2)), 'one or both consecutive ordinary Cargo builds failed')
    return results,readings


def run(root,verb,role,point,out,reference,patterns):
    from ast_developer import product, match, typed_fingerprint
    from ast_developer_witness import before,timed_final
    from ast_archive import examine,live_cgu
    from ast_macho_witness import identity
    check_host(root,8);repo=root/'ruff';work=root/('study-work' if verb=='build' else 'native-verbs-work');work.mkdir(exist_ok=True)
    sdk=select(root,role);env=env_for(work,sdk);fresh(work,root/'seed')
    save(out/'empty.json',preparation(work));save(out/'developer-environment.json',environment_receipt(env))
    before_sdk=sdk_id(sdk,env);argv=ARGS if verb=='build' else verbs.ARGS['test']
    values=source_values(repo) if verb=='build' else None
    def restore(state):
        if verb=='build':change_source(repo,values,state)
        else:verbs.restore(repo,state)
    def check_stream(label,cap,directory):
        code,stdout,_,rows,_=cap;need(code==0 and rows is None,'not an ordinary successful Cargo')
        arts,dirty,codes,roster=typed(stdout,True)
        [zmij]=[r for r in arts if r['target']['name']=='zmij' and r['target']['kind']==['lib']]
        fp=typed_fingerprint({'roster':roster,'dirty':dirty})
        need(all(p['roles'][role][label]['typed']==fp and p['roles'][role][label]['zmij_fresh']==zmij['fresh'] for p in patterns),
             'standalone+combined typed roster or freshness changed')
        save(directory/'typed.json',{'fingerprint':fp,'zmij_fresh':zmij['fresh'],'units':len(arts),'dirty':len(dirty)})
        return arts
    restore('old');plain=capture(argv,repo,env,out/'cold')
    check_stream('cold',plain,out/'cold')
    restore('new')
    if point=='edit-plus-repeat':
        caps,clock=combined(argv,repo,env,out)
        check_stream('edit',caps[0],out/'edit')
        label='repeat-1';cap=caps[1]
    else:
        seq=('edit','repeat-1','repeat-2')
        for label in seq[:seq.index(point)]:
            cap=capture(argv,repo,env,out/label)
            check_stream(label,cap,out/label)
        label=point
        cap=capture(argv,repo,env,out/label,clock=True)
        clock=cap[4]
    phase=out/label;arts=check_stream(label,cap,phase)
    if verb=='test':
        selected=verbs.result_unit(verb,arts)
        target=selected['executable'];original=Path(target).read_bytes()
        proof=witness(root,phase,original,target)
        row=verbs.phase('test',root,work,sdk,env,role,'new',label,None,phase,captured=cap)
        need(row['product']['raw']==proof['raw'],'timed test binary changed during own readback')
        row['test_debug']=identity(proof)
    else:
        lib,_=products(arts);states=before(work);need(len(states)==1,'ambiguous timed AST library generation')
        [path]=states
        _,proof=examine(lib.read_bytes(),live_cgu(work/path))
        save(phase/'ast-archive-work-products.json',{'session':path,'archive':str(lib),'proof':proof})
        row=library_phase(root,work,sdk,env,role,label,'new',None,phase,captured=cap)
    need(match(verb,product(verb,row),reference['new']),f'{verb}/{point}/{role} output differs from own independent clean or retained native inputs')
    timed_final(work,out);need(before_sdk==sdk_id(sdk,env),'selected compiler changed')
    finish={'purpose':point,'verified_ending_phase':label,'role':role,'cargo':clock,'native':product(verb,row),
            'complete_raw_equal':(product(verb,row)==reference['new'])}
    save(out/'observed.json',finish)
    retire(work)
    return finish
