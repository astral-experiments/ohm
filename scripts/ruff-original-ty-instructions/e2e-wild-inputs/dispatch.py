"""Recreate the original, possibly absent GNU jobserver endpoints around a single native link."""
from pathlib import Path
import fcntl,json,os,re,sys
data=json.loads(Path(sys.argv[1]).read_bytes())
raw=(Path(data['private'])/'env.nul').read_bytes().rstrip(b'\0').split(b'\0')
env={os.fsdecode(s.split(b'=',1)[0]):os.fsdecode(s.split(b'=',1)[1])for s in raw}
assert len(raw)==len(env)
flags=env.get('CARGO_MAKEFLAGS',env.get('MAKEFLAGS',''))
pairs={tuple(map(int,m))for m in re.findall(r'--jobserver-(?:fds|auth)=(\d+),(\d+)',flags)}
fds={int(x[0]):(int(x[1]),x[2])for l in (Path(data['private'])/'fds').read_text().splitlines()if(x:=l.split(' ',2))}
if pairs:
    assert len(pairs)==1;rd,wr=pairs.pop()
    if rd in fds or wr in fds:
        assert rd in fds and wr in fds and fds[rd][1]==fds[wr][1]and fds[rd][1].startswith('pipe:[') and 0<=fds[rd][0]<=64
        a,b=os.pipe();x,y=[fcntl.fcntl(f,fcntl.F_DUPFD_CLOEXEC,64)for f in(a,b)]
        os.close(a);os.close(b);os.write(y,b'+'*fds[rd][0]);os.dup2(x,rd,inheritable=True);os.dup2(y,wr,inheritable=True);os.close(x);os.close(y)
os.chdir((Path(data['private'])/'cwd').read_text());args=data['command']
if 'phase' in data:
    assert data['phase'] in ('paths','audit','hash','sections','complete') and 'actor' in data
    env['OHM_QA_WILD_PHASE']=data['phase']
actor=data.get('actor',args[0])
if 'clock' in data:
    clock,record=data['clock'];os.execve(clock,[clock,record,actor,*args],env)
os.execve(actor,args,env)
