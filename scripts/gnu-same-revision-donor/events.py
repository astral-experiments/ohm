"""Parse the event-only kernel trace. All registered images must be complete successful execs."""
import hashlib,os,stat
def need(test,msg):
    if not test:raise ValueError(msg)
def reopen(raw,code):
    rows=[line.split('\t') for line in raw.decode('ascii').splitlines()]
    need(rows and rows[0][0]=='R' and rows[-1][0]=='OK','unclosed kernel ledger')
    images={}; events=[]; known={}; births={}; exits={}; ends={}; displaced={};unreleased={};groups={};provisional={}
    root=int(rows[0][2]); known[1]=root
    for row in rows[1:-1]:
        k,*v=row
        if k=='I':
            i,dev,ino,n,m,mt,ct,dig=v; i=int(i);need(i==len(images)+1 and len(bytes.fromhex(dig))==32 and stat.S_ISREG(int(m,8)),'bad image identity')
            images[i]={'dev':int(dev),'ino':int(ino),'size':int(n),'sha256':dig,'mode':int(m,8),'mtime':mt,'ctime':ct}
        elif k=='N':
            p,pid,event,c,child=map(int,v);need(known[p]==pid and c not in known and event in (1,2,3),'bad child');known[c]=child
        elif k=='W':
            s,pid,status=map(int,v);need(s in known and known[s]==pid and s not in births,'bad never-released wait');births[s]=pid;unreleased[s]=pid
        elif k in ('B','U'):
            s,pid,tgid=map(int,v);need(s not in births and pid>0 and tgid>0,'bad birth');births[s]=pid;groups[s]=tgid
            if k=='U':unreleased[s]=pid
        elif k=='E':
            ordinal,s,pid,former,i=map(int,v[:5]); exe,cwd,execfn,argv=(bytes.fromhex(x) for x in v[5:])
            need(s not in unreleased and i in images and s in known and ordinal==len(events)+1 and argv.endswith(b'\0') and len(v)==9 and exe.startswith(b'/') and cwd.startswith(b'/') and execfn,'bad committed image')
            need(known[s] in (pid,former) and s not in exits,'unexplained exec lifetime');known[s]=pid
            events.append(dict(pid=pid,ordinal=ordinal,lifetime=s,exe=os.fsdecode(exe),cwd=os.fsdecode(cwd),execfn=os.fsdecode(execfn),argv=list(map(os.fsdecode,argv[:-1].split(b'\0'))),image=images[i]))
        elif k=='D':
            s,pid,by=map(int,v);need(s not in ends and s not in displaced and known[s]==pid and by in known and groups.get(by)==pid,'bad replaced leader');displaced[s]=by
        elif k in ('V','X','T'):
            s,pid,status=map(int,v);need((s in known and known[s]==pid) or k=='X' and unreleased.get(s)==pid,'bad terminal lineage')
            if k in ('X','V'):need(s not in exits,'duplicate exit');exits[s]=status
            else:
                need(s in exits and s not in ends,'duplicate or absent wait status')
                if exits[s]!=status:
                    need(groups.get(s,pid)!=pid,'mismatched group leader status');provisional[s]=status
                ends[s]=status
        else:raise ValueError(('invalid kernel record',row[:2]))
    code2,image_count,family,nb,nt,nd=map(int,rows[-1][1:])
    need(code2==code and events and image_count==len(events) and len(known)==family==len(births)+1 and len(births)==nb and len(ends)==nt and len(displaced)==nd and not ends.keys()&displaced.keys() and ends.keys()|displaced.keys()==known.keys() and exits.keys()==ends.keys(),'missing terminal family')
    for lifetime,status in provisional.items():
        need(any(known[k]==groups[lifetime] and val==status for k,val in ends.items()),'nonleader terminal not corroborated by group leader')
    owner=1; chain=set()
    while owner in displaced:
        need(owner not in chain,'cycled thread replacement');chain.add(owner);owner=displaced[owner]
    need(all(x in known for x in births) and known[owner]==root and all(lifetime in ends and pid==known[lifetime] for lifetime,pid in unreleased.items()) and not any(x['lifetime'] in unreleased for x in events) and os.waitstatus_to_exitcode(ends[owner])==code,'incorrect Cargo status')
    return dict(execs=events,terminal_groups=family,observed_births=nb,successful_execs=image_count,exits_before_release=len(unreleased),group_exit_overrides=len(provisional))
