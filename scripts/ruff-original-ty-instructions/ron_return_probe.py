"""GDB checks the six-word Span ABI at two signed instructions of the real span_join."""
import gdb
import hashlib
import json
import os
from pathlib import Path
import struct

inf=gdb.selected_inferior()
folder=Path(os.environ['OHM_REAL_RON_PROBE'])
plan=json.loads((folder/'plan.json').read_bytes())
raw=Path('/proc/%s/cmdline'%inf.pid).read_bytes()
assert raw==b'\0'.join(os.fsencode(s)for s in plan['argv'])+b'\0'
image=Path(plan['driver'])
bits=[l.split()for l in Path('/proc/%s/maps'%inf.pid).read_text().splitlines()]
base,=[int(row[0].split('-')[0],16)for row in bits if len(row)>=6 and row[2]=='00000000' and Path(row[5])==image]
locations=(0x6b9e3b2,0x6b9e2f4)
with image.open('rb')as so:
    assert hashlib.file_digest(so,'sha256').hexdigest()==plan['signed_driver']
    so.seek(0);h=so.read(64)
    assert h[:6]==b'\x7fELF\x02\x01'
    off=struct.unpack_from('<Q',h,32)[0];ent,n=struct.unpack_from('<HH',h,54)
    segments=[]
    for i in range(n):
        so.seek(off+i*ent);kind,flags,at,va,_,length,_,_=struct.unpack('<IIQQQQQQ',so.read(56))
        if kind==1 and flags&1:segments.append((at,va,length))
    for site in locations:
        pos,=[at+site-va for at,va,length in segments if va<=site and site+12<=va+length]
        so.seek(pos);assert bytes(inf.read_memory(base+site,12))==so.read(12)
assert bytes(inf.read_memory(base+locations[0],7))==bytes.fromhex('c680a61b000001')
reg=lambda k:int(gdb.selected_frame().read_register(k))&((1<<64)-1)
word=lambda p,n:int.from_bytes(bytes(inf.read_memory(p,n)),'little')
pending={};rows=[];exit_codes=[]
gdb.events.exited.connect(lambda ev:exit_codes.append(getattr(ev,'exit_code',None)))

class Foreign(gdb.Breakpoint):
    def stop(self):
        tid=gdb.selected_thread().ptid[1]
        first,second=reg('r15'),reg('r14');a,b=reg('r12'),reg('rbp')
        ids=[bytes(inf.read_memory(p+16,16)).hex()for p in(a,b)]
        starts=[word(p+0x154,4) for p in(a,b)]
        pair=[[(v&0xffffffff)-s,(v>>32)&0xffff,v>>48]for v,s in zip((first,second),starts)]
        assert ids==[plan['source_id']]*2 and [x[:2]for x in pair]==[[549,1],[602,8]] and pair[0][2]==pair[1][2]
        assert tid not in pending and len(rows)<4
        pending[tid]=(reg('rbx'),first,second,pair)
        ret.enabled=True
        return False

class Return(gdb.Breakpoint):
    def stop(self):
        tid=gdb.selected_thread().ptid[1]
        if tid not in pending:return False
        obj,first,second,pair=pending.pop(tid)
        assert reg('rbx')==obj and word(obj,4)==1
        original=word(obj+4,8)
        assert (original&0xffffffff)==(first&0xffffffff)and (original>>48)==(first>>48)and ((original>>32)&0xffff)==61
        if plan['mode']=='first-operand':inf.write_memory(obj+4,first.to_bytes(8,'little'))
        after=word(obj+4,8);assert word(obj,4)==1 and after==(first if plan['mode']=='first-operand'else original)
        rows.append({'tid':tid,'range':pair,'original':hex(original),'returned':hex(after),'first':hex(first),'second':hex(second)})
        (folder/'returns-in-progress.json').write_text(json.dumps(rows)+'\n')
        ret.enabled=bool(pending)
        return False

before=Foreign('*'+hex(base+locations[0]),internal=True)
ret=Return('*'+hex(base+locations[1]),internal=True);ret.enabled=False

def finish():
    (folder/'returns.json').write_text(json.dumps({'returns':rows,'exit_codes':exit_codes,'pending':list(pending),'sites':[hex(x)for x in locations],'mode':plan['mode']})+'\n')
    assert not pending and len(rows)==3 and exit_codes==[1]
