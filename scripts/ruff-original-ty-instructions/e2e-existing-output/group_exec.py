"""Give an unmodified signed linker the registered argv and controlled jobserver FDs."""
import fcntl,json,os,sys
from pathlib import Path
plan=json.loads(Path(sys.argv[1]).read_bytes());real=plan['executable']
if plan['replace_fds']:
    # Move both out of the handoff range before recreating the original numbers; this
    # also handles a jobserver FD colliding with one of this helper's own inherited FDs.
    incoming=list(map(int,sys.argv[2:]));assert len(incoming)==2
    saved=[fcntl.fcntl(x,fcntl.F_DUPFD_CLOEXEC,512)for x in incoming]
    for i,x in enumerate(saved):os.dup2(x,plan['jobserver'][i],inheritable=True)
    for x in saved+incoming:
        if x not in plan['jobserver']:os.close(x)
os.sched_setaffinity(0,plan['cpus']);assert sorted(os.sched_getaffinity(0))==plan['cpus']
delivered=[]
for fd in plan['jobserver']:
    try:
        s=os.fstat(fd);delivered.append([fd,s.st_dev,s.st_ino,s.st_mode,fcntl.fcntl(fd,fcntl.F_GETFL)&3])
    except OSError:delivered.append([fd,None])
if plan['replace_fds']:assert delivered==plan['expected_fds'],(plan['jobserver'],delivered,plan['expected_fds'])
Path(plan['delivered']).write_text(json.dumps(delivered))
os.execve(real,plan['argv'],os.environb)
