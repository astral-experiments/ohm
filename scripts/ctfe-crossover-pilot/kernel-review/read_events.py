"""Independently close a raw kernel exec ledger. No path lookup or replacement of missing events."""
import argparse, gzip, hashlib, json, os, pathlib, re, stat
class Refused(ValueError): pass
def need(x,why):
    if not x:raise Refused(why)
def data(token):
    need(bool(re.fullmatch(r'(?:[0-9a-f]{2})*',token)),'noncanonical hex')
    return bytes.fromhex(token)
def read(path,expected_code=None,expected_sha=None,expected_schema=None):
    path=pathlib.Path(path);blob=path.read_bytes()
    if blob.startswith(b'\x1f\x8b'):blob=gzip.decompress(blob)
    return parse(blob,expected_code,expected_sha,expected_schema)
def parse(blob,expected_code=None,expected_sha=None,expected_schema=None):
    sha=hashlib.sha256(blob).hexdigest()
    need(expected_sha is None or sha==expected_sha,'raw ledger SHA')
    need(blob.endswith(b'\n'),'unterminated ledger')
    procs={}; live={}; images={}; execs=[]; open_ex={}; reaped=[]; discard=[]; creturn=[]; failed=[]; aborted=[]; roots=[]; terminal=None
    groups={}; parks={}
    def state(g,p):
        need(g in procs and procs[g]['pid']==p and live.get(p)==g,'unknown/reused native task')
        return procs[g]
    def birth(g,p):
        need(g>0 and p>0,'invalid lifetime')
        if g not in procs:
            need(g==len(procs)+1 and p not in live,'new lifetime collision or missing generation')
            procs[g]={'pid':p,'initial_tid':p,'parent':None,'tgid':None,'preexit':None,'terminal':None,'pending':None}
            live[p]=g
        return state(g,p)
    def active(g,p):
        s=state(g,p);need(s['parent'] is not None and s['tgid'] is not None and s['preexit'] is None,'not a live entered task');return s
    def number(xs):return tuple(int(x) for x in xs)
    shapes={'R':2,'B':3,'N':5,'I':8,'E':9,'C':4,'Y':3,'F':3,'A':3,'P':3,'L':3,'D':3,'X':3,'T':3,'OK':6,
            'G':3,'Q':6,'V':3}
    for row,raw in enumerate(blob[:-1].split(b'\n'),1):
        try:
            tag,*f=raw.decode('ascii').split('\t')
            need(terminal is None and tag in shapes and (len(f)==shapes[tag] or tag=='OK' and len(f)==8),
                 f'unknown or truncated record {tag!r}')
            # A parked peer never receives a user-mode restart; a committed group
            # exit caller can only report its irreversible EXIT and terminal wait.
            if tag in ('N','C','Y','F','A','P','L','D','E'):
                g=int(f[1] if tag=='E' else f[0])
                need(g not in parks and g not in groups,'active event after group teardown')
            if tag=='R':
                g,p=number(f);need(row==1 and g==1 and not roots,'duplicate root')
                s=birth(g,p);s['parent']=0;s['tgid']=p;roots.append(p)
            elif tag=='I':
                i,d,n,size=number(f[:4]);m=int(f[4],8)
                need(i==len(images)+1 and d>=0 and n>0 and size>=64 and stat.S_ISREG(m) and bool(re.fullmatch('[0-9a-f]{64}',f[7])),'invalid image')
                need(all(re.fullmatch(r'-?\d+\.\d{9}',x) for x in f[5:7]),'image timestamps')
                images[i]=dict(id=i,dev=d,ino=n,size=size,mode=m,mtime=f[5],ctime=f[6],sha256=f[7])
            elif tag=='B':
                g,p,tgid=number(f);s=birth(g,p)
                need(g>1 and tgid>0 and s['tgid'] is None,'duplicate birth stop');s['tgid']=tgid
                need(not any(q['verified'] and procs[leader]['pid']==tgid and procs[leader]['terminal'] is None
                             for leader,q in groups.items()),'late birth in sealed fork group')
            elif tag=='N':
                pg,p,k,g,ch=number(f);a=active(pg,p);s=birth(g,ch)
                need(k in (1,2,3) and g!=pg and s['parent'] is None and a['pending'] is None,'bad fork lineage')
                s['parent']=pg;s['create_kind']=k;a['pending']=ch
            elif tag=='G':
                g,p,code=number(f);s=active(g,p)
                need(s['tgid']==p and s.get('create_kind')==1 and not any(e['lifetime']==g for e in execs)
                     and s['pending'] is None and g not in groups and 0<=code<=255,'invalid exit_group caller')
                groups[g]={'code':code<<8,'verified':False,'peers':set()}
            elif tag=='Q':
                g,p,owner,tgid=number(f[:4]);kind=f[4];nr=int(f[5]);s=active(g,p);a=active(owner,tgid)
                gate=groups[owner]
                need(not gate['verified'] and a['tgid']==s['tgid']==tgid and g!=owner and p!=tgid and
                     g not in parks and g not in open_ex and s['pending'] is None,'unbound or unresolved parked peer')
                need((kind in ('i','x') and nr==-1) or (kind=='e' and 0<=nr<0x40000000
                     and nr not in (56,57,58,59,231,322,435)),'unsafe or unknown parked syscall')
                gate['peers'].add(g);parks[g]=owner
            elif tag=='V':
                owner,p,n=number(f);active(owner,p);gate=groups[owner]
                need(not gate['verified'] and n==len(gate['peers']) and
                     all(g==owner or s['tgid']!=p or s['preexit'] is not None or s['terminal'] is not None
                         or g in gate['peers'] for g,s in procs.items()) and
                     not any(s['tgid'] is None and s['parent'] is not None and procs[s['parent']]['tgid']==p
                             for s in procs.values()),'incomplete group park')
                gate['verified']=True
            elif tag in ('C','Y'):
                g,p,num=number(f[:3]);s=active(g,p);ch=int(f[3]) if tag=='C' else num
                if num>0:need(s['pending']==num==ch,'positive or interrupted create without exact child')
                else:need(tag=='C' and num<0 and ch==0 and s['pending'] is None,'inconsistent failed creation')
                creturn.append([tag,g,p,num,ch]);s['pending']=None
            elif tag=='E':
                i,g,p,old,image=number(f[:5]);need(i==len(execs)+1 and image in images and g not in open_ex,'positive exec ordinal/identity')
                s=active(g,old);need(s['tgid']==p,'foreign exec leader')
                if p!=old:
                    need(p not in live and any(x['pid']==p and x['terminal'] is not None for x in procs.values()),'invalid nonleader takeover')
                    del live[old];live[p]=g;s['pid']=p
                nm,cwd,fn,arg=(data(x) for x in f[5:])
                need(nm.startswith(b'/') and cwd.startswith(b'/') and bool(fn) and not any(b'\0' in z for z in [nm,cwd,fn]),'invalid installed identity')
                need(arg.endswith(b'\0') and len(arg)<8*1024**2,'truncated installed argv')
                execs.append(dict(ordinal=i,lifetime=g,pid=p,former_tid=old,image=images[image],exe=os.fsdecode(nm),cwd=os.fsdecode(cwd),
                                  execfn=os.fsdecode(fn),argv=[os.fsdecode(z) for z in arg[:-1].split(b'\0')]))
                open_ex[g]=i
            elif tag in ('P','L'):
                g,p,i=number(f);active(g,p);need(open_ex.pop(g,None)==i,'exec completion lacks matching irreversible image')
                if tag=='L':procs[g]['exec_interrupted']=i
            elif tag in ('F','A'):
                g,p,rc=number(f);s=active(g,p)
                need(g not in open_ex and ((tag=='F' and rc<0) or (tag=='A' and rc>=0 and 'aborted' not in s)),'failed/interrupted exec inconsistent')
                if tag=='A':s['aborted']=rc;aborted.append([g,p,rc])
                else:failed.append([g,p,rc])
            elif tag=='X':
                g,p,status=number(f);s=active(g,p);need(g not in open_ex and s['pending'] is None and s.get('aborted',status)==status,'unclosed exit')
                need(os.WIFSIGNALED(status) or os.WIFEXITED(status),'unrecognized exit event')
                owner=parks.get(g,g)
                if owner in groups:need(groups[owner]['verified'] and status==groups[owner]['code'],'group EXIT mismatch')
                s['preexit']=status
            elif tag=='T':
                g,p,rc=number(f);s=state(g,p);need(s['preexit']==rc and s['terminal'] is None,'wait mismatch')
                s['terminal']='wait';del live[p];reaped.append([g,p,rc])
            elif tag=='D':
                g,p,newg=number(f);s=state(g,p)
                need(s['tgid']==p and s['preexit'] is not None and s['terminal'] is None and newg in procs and procs[newg]['tgid']==p and
                     procs[newg]['pid']!=p and procs[newg]['preexit'] is None,'unproved displaced leader')
                s['terminal']='displaced';del live[p];discard.append((g,p,newg))
            elif tag=='OK':terminal=number(f)
        except (Refused,ValueError,IndexError,KeyError) as e:raise Refused(f'line {row}: {e}') from e
    need(terminal is not None and len(roots)==1 and not live and not open_ex,'missing terminal or live task')
    need(all(v['verified'] and procs[g]['preexit']==v['code'] and
         procs[g]['terminal']=='wait' for g,v in groups.items()),'missing group caller EXIT and wait')
    code,nexec,ntask,nborn,nwait,nd,*extra=terminal
    schema=2 if extra else 1
    need((expected_schema is None or schema==expected_schema) and
         (extra==[len(groups),len(parks)] if extra else not groups and not parks),'group receipt counts or schema')
    need((nexec,ntask,nborn,nwait,nd)==(len(execs),len(procs),len(procs)-1,len(reaped),len(discard)) and
         nwait+nd==ntask and nexec>0,'family counts')
    for g,s in procs.items():
        need(s['parent'] is not None and s['tgid'] and s['terminal'] and s['pending'] is None,'incomplete birth/exit')
    need(all(any(e['pid']==p and e['former_tid']!=p and e['lifetime']==g for e in execs) for _,p,g in discard),'uncommitted leader replacement')
    roots_reaped=[os.waitstatus_to_exitcode(st) for _,p,st in reaped if p==roots[0]]
    need(len(roots_reaped)==1,'root has no unique reaped status')
    target=roots_reaped[0];need(code==(target if target>=0 else 128-target) and (expected_code is None or code==expected_code),'root return')
    used={e['image']['id'] for e in execs};need(used==set(images),'unconsumed image')
    return dict(schema=schema,sha256=sha,code=code,images=len(images),lifetimes=ntask,reaped=nwait,displaced=nd,
                execs=execs,failed_exec_returns=failed,interrupted_execs=aborted,spawned=nborn)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('ledger');a.add_argument('--code',type=int);a.add_argument('--sha256');a.add_argument('--summary',action='store_true')
    p=a.parse_args();j=read(p.ledger,p.code,p.sha256)
    if p.summary:j['execs']=len(j['execs'])
    print(json.dumps(j,sort_keys=True))
