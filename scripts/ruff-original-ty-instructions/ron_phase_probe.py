"""Snapshot one real compiler process through exit or a preregistered normal native frontier."""
import ctypes as C
import json
import os
from pathlib import Path
import gdb

folder=Path(os.environ['OHM_ROUND'])
plan=json.loads((folder/'plan.json').read_bytes())
inferior=gdb.selected_inferior()
assert Path(f'/proc/{inferior.pid}/cmdline').read_bytes()==b'\0'.join(os.fsencode(x)for x in plan['argv'])+b'\0'
assert len(inferior.threads())==1
events=[];stops=[];exitcodes=[]
gdb.events.exited.connect(lambda ev:exitcodes.append(getattr(ev,'exit_code',None)))
if plan['driver']:
    image=Path(plan['driver'])
    maps=[l.split()for l in Path(f'/proc/{inferior.pid}/maps').read_text().splitlines()]
    base,=[int(r[0].split('-')[0],16)for r in maps if len(r)>5 and r[2]=='00000000'and Path(r[5])==image]
    class Hook(gdb.Breakpoint):
        def __init__(self,k,a):
            self.k=k;self.a=a
            assert bytes(inferior.read_memory(base+a,12)).hex()==plan['preimages'][str(a)]
            super().__init__('*'+hex(base+a),internal=True)
        def stop(self):
            events.append((self.k,self.a,gdb.selected_thread().ptid[1]))
            if self.k==plan['frontier']:
                stops.append(self.k)
                return True
            return False
    hooks=[Hook(k,s)for k,values in plan['addresses'].items()for s in values]
lib=C.CDLL(plan['counter'],use_errno=True)
original_pid=inferior.pid
fd=lib.open_counter(original_pid)
assert fd>=0,C.get_errno()

def finish():
    if plan['frontier']:
        assert stops==[plan['frontier']]and not exitcodes and inferior.pid>0,(stops,events,exitcodes)
        gdb.execute('kill',to_string=True)
        assert inferior.pid==0 and not Path(f'/proc/{original_pid}').exists() and exitcodes in ([None],[]),exitcodes
    else:
        assert not stops and exitcodes==[0],(stops,exitcodes)
    counts=(C.c_uint64*3)()
    assert lib.finish_counter(fd,C.byref(counts))==1
    raw=list(counts)
    assert raw[0]>0 and raw[1]>0 and raw[1]==raw[2],raw
    (folder/'counter.json').write_text(json.dumps({'retired_user':raw[0],'enabled':raw[1],'running':raw[2],'events':events,'stops':stops,'exitcodes':exitcodes},sort_keys=True)+'\n')
