"""Bounded real instruction counts at provider entry/return. Valgrind reports cumulative guest Ir on the same thread at each breakpoint."""
import gdb,os,json,re,collections,hashlib
from pathlib import Path
s=json.loads(Path(os.environ['CG_REQUEST']).read_bytes());out=Path(s['outs']);gdb.execute('set python print-stack full');gdb.execute('set pagination off');gdb.execute('set confirm off');gdb.execute('set debuginfod enabled off');gdb.execute('set print thread-events off');gdb.execute('target remote | '+s['vgdb']+' --pid='+str(s['pid'])+' --vgdb-prefix='+s['prefix']);log=[];fault=[];active=collections.defaultdict(list);taps={};exitv=[]
gdb.events.exited.connect(lambda e:exitv.append(e.exit_code if hasattr(e,'exit_code')else None))
if s['relative']:
 gdb.execute('tbreak main');gdb.execute('continue');assert gdb.selected_frame().name()=='main',gdb.selected_frame().name();p=s['pid'];maps=[t.split(None,5)for t in Path('/proc/'+str(p)+'/maps').read_text().splitlines()];drv=Path(s['driver']);ss=[int(t[0].split('-')[0],16)for t in maps if len(t)==6 and int(t[2],16)==0 and Path(t[-1]).is_absolute()and Path(t[-1]).resolve()==drv.resolve()];assert len(ss)==1 and hashlib.sha256(drv.read_bytes()).hexdigest()==s['digest'];base=ss[0]
 for name,addr in s['symbols'].items():
  raw=gdb.selected_inferior().read_memory(base+addr,len(bytes.fromhex(s['opcodes'][name]))).tobytes().hex()
  assert raw==s['opcodes'][name],(name,raw,s['opcodes'][name])
 (out/'admitted-elf.json').write_text(json.dumps({'driver':str(drv),'base':hex(base),'opcodes':s['opcodes']}))
else:base=0
def readreg(name):return int(gdb.parse_and_eval('$'+name))&((1<<64)-1)
def total():
 # Valgrind's thread index is the GDB remote thread id, distinct from a kernel TID. Affirm status and single-running-thread identity in every observation.
 z=gdb.execute('monitor status internal',to_string=True);k=re.search(r'^events: ([^\n]+)$',z,re.M);assert k and k.group(1).strip()=='Ir',z
 tv={int(i):int(n.strip())for i,n in re.findall(r'^events-(\d+):\s*(\d+)\s*$',z,re.M)};assert tv,z;return tv
class Ret(gdb.Breakpoint):
 def __init__(self,address):self.addr=address;super().__init__('*'+hex(address),internal=True)
 def stop(self):
  try:
   th=tuple(gdb.selected_thread().ptid);stack=active[th];sp=readreg('rsp')
   if not stack or (stack[-1][0],stack[-1][1])!=(sp-8,self.addr):return False
   _,_,row,start=stack.pop();end=total();delta=sum(end.values())-sum(start.values());assert delta>0 and set(start)<=set(end)and all(end[i]>=start[i]for i in start),(row,start,end);row['end']=end;row['delta_all_threads']=delta;log.append(row)
  except BaseException as e:fault.append(repr(e));raise
  return False
class Start(gdb.Breakpoint):
 def __init__(self,name,address):self.name=name;super().__init__('*'+hex(address),internal=True)
 def stop(self):
  try:
   sp=readreg('rsp');ret=int.from_bytes(gdb.selected_inferior().read_memory(sp,8).tobytes(),'little');th=tuple(gdb.selected_thread().ptid)
   if ret not in taps:taps[ret]=Ret(ret)
   row={'symbol':self.name,'index':readreg('esi'if s['relative']else'edi')&0xffffffff,'thread':th,'entry':len(log),'caller':hex(ret-base),'stack':sp,'start':total()};active[th].append((sp,ret,row,row['start']))
  except BaseException as e:fault.append(repr(e));raise
  return False
starts=[Start(name,base+addr)for name,addr in s['symbols'].items()];gdb.execute('continue');assert all(not l for l in active.values())and not fault and exitv==[0],(fault,exitv,{k:len(v)for k,v in active.items()});(out/'cost.json').write_text(json.dumps({'rows':log,'exit':exitv[0],'fault':fault,'symbol_base':hex(base)},separators=(',',':'))+'\n')
