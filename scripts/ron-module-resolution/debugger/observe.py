"""GDB callback reads only signed marker stores and an authenticated SourceFile or Span."""
import collections,hashlib,json,os,re,time
from pathlib import Path
import gdb
d=Path(os.environ['OHM_F_SPAN_LOG']).parent.parent
plan=json.loads((d/'plan.json').read_text());driver=Path(plan['driver']['path'])
inferior=gdb.selected_inferior();maps=Path('/proc/%s/maps'%inferior.pid)
actual=Path('/proc/%s/cmdline'%inferior.pid).read_bytes().split(b'\0')[:-1]
expected=[os.fsencode(i)for i in plan['argv']]
assert actual==expected,[(i,x[:180],y[:180])for i,(x,y)in enumerate(zip(actual,expected))if x!=y][:2]
exit_codes=[]
def on_exit(ev):exit_codes.append(getattr(ev,'exit_code',None))
gdb.events.exited.connect(on_exit)
start,=[int(z.split('-')[0],16) for z in maps.read_text().splitlines()if len(z.split())>5 and z.split()[2]=='00000000'and Path(z.split()[5])==driver]
regions={'debug':(0x433e399,None),'byte_range':(0x433fec3,'rax'),'join':(0x6b9e3b2,'r12'),'subspan':(0x433ed01,None),'source_text':(0x4341632,'r14'),'untracked_source_text':(0x4341665,'r14')}
def buf(a,n):return bytes(inferior.read_memory(a,n))
def reg(k):return int(gdb.selected_frame().read_register(k))&((1<<64)-1)
def w(a):return int.from_bytes(a,'little')
def module(pc):
 for line in maps.read_text().splitlines():
  xs=line.split();lo,hi=[int(y,16)for y in xs[0].split('-')]
  if lo<=pc<hi and len(xs)>5:return (Path(xs[5]).name,hex(pc-lo+int(xs[2],16)))
 return None
def source(a):
 b=buf(a,352);rows=set()
 for i in range(32,344,8):
  pointer=w(b[i:i+8])
  if pointer<=0xffffffff:continue
  for j in [i-8,i+8]:
   n=w(b[j:j+8])
   if not 3<=n<=1024:continue
   try:raw=buf(pointer,n);s=raw.decode()
   except (UnicodeError,gdb.error):continue
   if s.endswith('.rs')and not any(ord(x)<32 for x in s): rows.add((i,j,s))
 return dict(stable_id=b[16:32].hex(),eligibility_word=hex(w(b[232:240])),names=sorted(rows))
events=collections.Counter(); identities={};stacks={};first=[]
class B(gdb.Breakpoint):
 def __init__(self,which,relative,source_reg):
  self.which=which;self.source_reg=source_reg
  address=start+relative
  body=bytes.fromhex({'debug':'41c687a61b000001','byte_range':'c681a61b000001','untracked_source_text':'c680a71b000001'}.get(which,'c680a61b000001'))
  assert buf(address,len(body))==body,(which,buf(address,len(body)).hex())
  super().__init__('*'+hex(address),internal=True)
 def stop(self):
  which=self.which;events[which]+=1
  if which=='join':
   tid=gdb.selected_thread().ptid[1];assert tid not in pending
   pending[tid]=(reg('rbx'),reg('r15'),reg('r14'));returned_bp.enabled=True
   scope_join(events[which])
  if self.source_reg:
   o=source(reg(self.source_reg));k=which+':'+o['stable_id']
   if k not in identities:identities[k]={'hits':0,'object':o}
   identities[k]['hits']+=1
   if which=='join':assert buf(reg('r12')+16,16)==buf(reg('rbp')+16,16)
  if events[which]<=12:
   frame=gdb.newest_frame();stack=[]
   while frame and len(stack)<80:
    try:
     pc=frame.pc();case=module(pc);stack.append([case,frame.name()]);frame=frame.older()
    except gdb.error:break
   stacks[which+':'+str(events[which])]=stack
  if events[which]<=256:
   first.append({'event':which,'seq':events[which],'tid':gdb.selected_thread().ptid[1],'packed_spans':([hex(reg('r14'))]if which=='debug'else[]if which=='byte_range'else[hex(reg('r15'))])+([hex(reg('r14'))]if which=='join'else[]),'stack_derived':{'source_text_lo': w(buf(reg('rsp')+44,4))}if which=='source_text'else{}})
  if events[which]==20000: raise RuntimeError('diagnostic sample scope exceeded 19,999 events')
  return False

# Recover real stack frames through ELF unwind tables without making GDB load Rust symbols.
import ctypes as C
lib=C.CDLL(str(d/'deep-joins/unwind.so'));lib.walk.argtypes=[C.c_int,C.POINTER(C.c_uint64),C.c_int];lib.walk.restype=C.c_int
all_stacks={};returns=[];pending={};known=set();entries=collections.Counter();reads=collections.Counter();matches=[];waiting={}
def stack_snapshot(key):
 paths=maps.read_text();ranges=[]
 for l in paths.splitlines():
  x=l.split();lo,hi=[int(y,16)for y in x[0].split('-')]
  if len(x)>5 and 'x'in x[1]:ranges.append((lo,hi,int(x[2],16),x[5]))
 all_stacks[key]={}
 for th in inferior.threads():
  tid=th.ptid[1];ips=(C.c_uint64*120)();count=lib.walk(tid,ips,len(ips));frames=[]
  if count>0:
   for pc in ips[:count]:
    hits=[(nm,hex(pc-a+o))for a,b,o,nm in ranges if a<=pc<b]
    frames.append(hits[0]if hits else None)
  all_stacks[key][str(tid)]={'count':count,'frames':frames,'selected':th==gdb.selected_thread()}
class Entry(gdb.Breakpoint):
 def __init__(self,k,a):
  self.k=k;super().__init__('*'+hex(start+a),internal=True)
 def stop(self):
  k=self.k;entries[k]+=1;maybe_macros()
  if k=='span_join':server_tid[gdb.selected_thread().ptid[1]]=reg('rsi')
  regs=[reg(x)for x in ('rdi','rsi','rdx','rcx','r8','r9')]
  hits=[(i,hex(v))for i,v in enumerate(regs)if v in known]
  if hits:
   reads[k]+=1
   if len(matches)<1500:matches.append([k,hits,len(returns),gdb.selected_thread().ptid[1]])
  if sum(entries.values())%10000==0:(d/'deep-joins/progress').write_text(str(dict(entries))+'\n')
  return False
class Joined(gdb.Breakpoint):
 def stop(self):
  tid=gdb.selected_thread().ptid[1];call=pending.get(tid)
  if call:
   assert reg('rbx')==call[0];obj=buf(call[0],12);tag=w(obj[:4]);out=w(obj[4:12]);assert tag==1
   returns.append({'tid':tid,'first':hex(call[1]),'second':hex(call[2]),'some_tag':tag,'returned':hex(out)})
   known.update(call[1:3]);known.add(out);del pending[tid]
   if not pending:self.enabled=False
  return False
returned_bp=Joined('*'+hex(start+0x6b9e2f4),internal=True);returned_bp.enabled=False
import bisect
debugs=[];debug_pending={};predicates=[];join_sources=[];server_tid={};macro_ptrs=[];macro_scopes={};macro_leaves={};macro_n=collections.Counter()
def table(sess):
 sm=w(buf(sess+0x1788,8))+0x10;lk=w(buf(sm+0xc8,8));v=buf(sm+0xd0,24);cap,ptr,n=[w(v[i:i+8])for i in (0,8,16)];assert lk&8==0 and 0<n<=cap<100000
 ptrs=[w(x)for x in zip8(buf(ptr,n*8))];rows=[(w(buf(x+0x154,4)),w(buf(x+0xe8,8))==0,x)for x in ptrs];assert all(a[0]<b[0]for a,b in zip(rows,rows[1:]));return rows
def zip8(bs):return [bs[i:i+8]for i in range(0,len(bs),8)]
def locate(rows,packed):
 ln=packed>>32&0xffff
 if ln>=0x8000:return {'packed':hex(packed),'requires_interner':True}
 lo=packed&0xffffffff;i=bisect.bisect_right([x[0]for x in rows],lo)-1
 if i<0:return {'packed':hex(packed),'below_table':True}
 start,imported,arc=rows[i];fields=source(arc);return {'packed':hex(packed),'global_start':start,'imported':imported,'relative_lo':lo-start,'len':ln,'ctx':packed>>48,'stable_id':fields['stable_id'],'names':fields['names']}
def owners(tid):
 return [x[0]for x in macro_scopes.get(tid,[])]
class MacroLeave(gdb.Breakpoint):
 def stop(self):
  tid=gdb.selected_thread().ptid[1];stack=macro_scopes.get(tid,[])
  if stack and stack[-1][1:]==(reg('rsp'),reg('rip')):stack.pop()
  return False
class MacroEnter(gdb.Breakpoint):
 def __init__(self,name,a):
  self.name=name;super().__init__('*'+hex(a),internal=True)
 def stop(self):
  tid=gdb.selected_thread().ptid[1];sp=reg('rsp');ret=w(buf(sp,8));macro_scopes.setdefault(tid,[]).append((self.name,sp+8,ret));macro_n[self.name]+=1
  if ret not in macro_leaves:macro_leaves[ret]=MacroLeave('*'+hex(ret),internal=True)
  return False
def maybe_macros():
 if macro_ptrs:return
 spec=json.loads((d/'deep-joins/macro-entries.json').read_bytes());path=Path(spec['dylib']);sysmod=__import__('sys');sysmod.path.insert(0,str(Path(os.environ['OHM_F_SPAN_PY']).parent))
 from image import native_bases
 offsets=[int(v,16)for n,v in spec['symbols'].items()if n!='salsa_macros::token_stream_with_error']
 bases=native_bases(maps.read_text(),path.name,spec['same_physical_sha'],offsets)
 if not bases:return
 assert len(bases)==1,(str(path),bases)
 for name,s in spec['symbols'].items():
  if name!='salsa_macros::token_stream_with_error':macro_ptrs.append(MacroEnter(name,bases[0]+int(s,16)))
class DS(gdb.Breakpoint):
 def stop(self):
  tid=gdb.selected_thread().ptid[1];form=reg('rax')&255;# original byte as actually loaded at 433e2ab
  rows=table(reg('r15'));start,imported,arc=next((z for z in rows if z[1]),(None,None,None));sp=reg('rsp');obj=reg('rbx');key=(tid,obj);assert key not in debug_pending
  debug_pending[key]={'already_observed':form,'packed':hex(reg('r14')),'earliest_import_start':start,'source_files':len(rows),'raw_span_location':locate(rows,reg('r14')),'active_macros':owners(tid),'after_joins':len(returns)}
  return False
class DR(gdb.Breakpoint):
 def stop(self):
  tid=gdb.selected_thread().ptid[1];out=reg('rax');x=debug_pending.pop((tid,out));raw=buf(out,24);cap,ptr,n=map(w,zip8(raw));assert 0<n<=cap<=2048;s=buf(ptr,n).decode();m=re.fullmatch(r'#(\d+) bytes\((\d+)\.\.(\d+)\)',s);assert m,s
  ctx,lo,hi=map(int,m.groups());x['returned']=s;x['would_independently_observe']=bool(ctx or (x['earliest_import_start']is not None and x['earliest_import_start']<=hi));debugs.append(x)
  return False
dbgbps=[DS('*'+hex(start+0x433e2b2),internal=True),DR('*'+hex(start+0x433e4a4),internal=True)]
def scope_join(req):
 tid=gdb.selected_thread().ptid[1];rows=table(reg('rax'));s=server_tid[tid];sp=reg('rsp');first=reg('r15');second=reg('r14')
 joined={'macro_scope':owners(tid),'first':locate(rows,first),'second':locate(rows,second),'server_globals':[locate(rows,w(buf(s+i,8))) for i in (0x28,0x30,0x38)],'char_locs':[[w(v)for v in zip8(buf(sp+i,32))[1:]]for i in (0x18,0x38)]}
 assert buf(reg('r12')+16,16).hex()==joined['first']['stable_id']and buf(reg('rbp')+16,16).hex()==joined['second']['stable_id'];join_sources.append(joined)

physical_entries=[Entry(k,a)for k,a in json.loads((d/'deep-joins/fn-offsets.json').read_bytes()).items()if k in {'span_debug','span_source_text','span_byte_range','span_subspan','span_join','span_file','span_local_file','span_line','span_column','span_end','span_start','span_parent','span_source','span_resolved_at'}]

breaks=[B(k,*v)for k,v in regions.items()]
def finish():
 assert exit_codes==[0],exit_codes
 assert not pending and not debug_pending and len(debugs)==entries['span_debug']
 info={'debugs':debugs,'join_sources':join_sources,'macro_calls':dict(macro_n),'actual_returns':returns,'entry_counts':dict(entries),'matched_input_registers':dict(reads),'detailed_matches':matches,'native_stacks':all_stacks,'inferior_argv_sha':hashlib.sha256(b'\0'.join(actual)+b'\0').hexdigest(),'exit_codes':exit_codes,'events':dict(events),'identities':identities,'first':first,'stacks':stacks,'base':hex(start),'symbol_stores':{k:hex(v[0])for k,v in regions.items()}}
 Path(os.environ['OHM_F_SPAN_LOG']).write_text(json.dumps(info,indent=2,sort_keys=True)+'\n')
