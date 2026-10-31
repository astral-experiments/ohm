"""Verify each submitted lineage against original native PID logs, including exec barriers."""
import re

def verify(raw, claim, resolved):
    def require(v,m):
        if not v:raise ValueError(m)
    def calls(lines):
        pending=None;out=[]
        for s in lines:
            if s.startswith(b'<... '):
                tag,end,rest=s[5:].partition(b' resumed>')
                if pending and end and pending.startswith(tag+b'('):
                    s=pending+rest;pending=None
                else:
                    out.append(b'???(');pending=None;continue
            if pending is not None:
                out.append(b'???(');pending=None
            if s.endswith(b' <unfinished ...>'):pending=s[:-len(b' <unfinished ...>')]
            else:out.append(s)
        if pending is not None:out.append(b'???(')
        return out
    parsed={k:calls(v) for k,v in raw.items()}
    def barrier(x):
        return x.startswith(b'???(') or (x.startswith((b'execve(',b'execveat(')) and bool(re.search(rb'= 0$',x)))
    witnesses=claim['linux_fd_evidence'];require(witnesses,'no actual FD')
    pids=set()
    for fd in witnesses:
        n=fd['pid'];t=fd['event'];x=parsed[n][t];pids.add(n)
        require(x.startswith(b'openat(') and b'O_RDONLY' in x and bool(re.search(rb'= '+str(fd['fd']).encode()+rb'<'+re.escape(resolved)+rb'>$' ,x)), 'expected returned descriptor on resolved archive')
        visited=set()
        for item in fd['lineage']:
            require(n==item['pid'] and n not in visited, 'discontinuous lineage')
            visited.add(n)
            if 'creator' in item:
                require(not any(barrier(x) for x in parsed[n][:t]),'an intervening/opaque exec prevents inheriting this image')
                c=item['creator'];i=item['event'];line=parsed[c][i]
                require(bool(re.fullmatch(item['syscall'].encode()+rb'\(.*\)\s+= '+str(n).encode(),line)) and ('thread' if b'CLONE_THREAD' in line else 'process')==item['kind'],'wrong kernel parent or birth')
                n,t=c,i
            else:
                i=item['event'];line=parsed[n][i]
                require(item['image']=='wild' and n in claim['wild'] and item['exec'].endswith('/bin/wild-ld/ld.bfd') and line.startswith(b'execve("'+item['exec'].encode()+b'",') and re.search(rb'= 0$',line) and not any(barrier(z) for z in parsed[n][i+1:t]),'wrong last Wild image')
        require('creator' not in item and item['image']=='wild','missing true native exec')
    require(pids==set(claim['archive_read_by']),'different returned descriptor set')
    return len(witnesses)
