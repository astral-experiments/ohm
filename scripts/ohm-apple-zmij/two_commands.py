"""Time two actual Cargo commands with separate outputs and no observer between them."""
import contextlib
import os
import signal
import subprocess
import tempfile
import threading
import time

from calibrate import fields
from study import compress_bytes, need, save


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
