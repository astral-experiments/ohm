"""Replay signed Wild at its observed effective jobserver capacity and authenticated current inputs."""
import array,fcntl,json,os,re,stat,subprocess,sys,termios,time
from pathlib import Path
def count(fd):
    a=array.array('i',[0]);fcntl.ioctl(fd,termios.FIONREAD,a,True);return a[0]
def run(root,helper,tag,seq,process,threads,argv,stock,cwd,environment):
    flags=next(environment[k]for k in (b'CARGO_MAKEFLAGS',b'MAKEFLAGS',b'MFLAGS')if k in environment)
    pairs=re.findall(rb'--jobserver-(?:auth|fds)=(\d+),(\d+)',flags);assert pairs and len(set(pairs))==1
    nums=list(map(int,pairs[0]));assert 1<=threads<=4
    original=[]
    for i,num in enumerate(nums):
        path=Path('/proc')/str(process)/'fd'/str(num);s=path.stat();assert stat.S_ISFIFO(s.st_mode)
        mode=int(re.search(r'^flags:\s*([0-7]+)$',(path.parent.parent/'fdinfo'/str(num)).read_text(),re.M)[1],8)&3
        assert mode==i;original.append([num,s.st_dev,s.st_ino,s.st_mode,mode])
    assert original[0][1:4]==original[1][1:4]
    fds=os.pipe();status_tuple=[]
    try:
        if threads>1:assert os.write(fds[1],b'+'*(threads-1))==threads-1
        assert count(fds[0])==threads-1
        for i,fd in enumerate(fds):
            s=os.fstat(fd);status_tuple.append([nums[i],s.st_dev,s.st_ino,s.st_mode,fcntl.fcntl(fd,fcntl.F_GETFL)&3])
        delivered=root/(tag+'-'+str(seq)+'-stock-received');plan=root/(tag+'-'+str(seq)+'-stock-plan');cpus=sorted(os.sched_getaffinity(process))
        plan.write_text(json.dumps({'executable':str(stock),'argv':argv,'cpus':cpus,'jobserver':nums,'replace_fds':True,'expected_fds':status_tuple,'delivered':str(delivered)}))
        start=time.monotonic_ns();child=subprocess.Popen([sys.executable,'-IB',helper,plan,*map(str,fds)],cwd=cwd,env=environment,pass_fds=fds,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        levels=[];t=time.monotonic()+80
        while child.poll()is None:
            if time.monotonic()>t:child.kill();child.wait();raise TimeoutError(tag)
            levels.append(count(fds[0]));time.sleep(.002)
        out,err=child.communicate();elapsed=time.monotonic_ns()-start;assert child.returncode==0 and not out and not err,(child.returncode,err[:600])
        # The native Unix fork has published the ELF at parent return. Its child may
        # still own the authenticated GNU token while it drains its thread pool.
        on_return=count(fds[0]);until=time.monotonic()+45;begin_wait=time.monotonic_ns()
        while count(fds[0])!=threads-1 and time.monotonic()<until:time.sleep(.002)
        teardown_wait=time.monotonic_ns()-begin_wait
        assert count(fds[0])==threads-1 and (threads==1 or min(levels)==0)
        assert json.loads(delivered.read_bytes())==status_tuple
        return {'elapsed_ns':elapsed,'stock_token_at_return':on_return,'stock_extra_token_teardown_ns':teardown_wait,'typed_native_threads':threads,'private_tokens_supplied':threads-1,'minimum_before_return':min(levels)if levels else None,'actual_original_pipe':original,'exact_private_pipe':status_tuple,'affinity':cpus}
    finally:
        for fd in fds:os.close(fd)
