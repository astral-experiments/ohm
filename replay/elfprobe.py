from pathlib import Path
import shutil,hashlib,subprocess,os,re,resource,statistics,time
which='additional_dirs::tests::returns_none_when_no_additional_dirs'

def capture(path,role,root):
    path=Path(path)
    files=[p for p in path.glob('targets/**/codex_tui-*') if p.is_file() and os.access(p,os.X_OK)]
    if not files:files=[p for p in path.glob('shared-build/**/codex_tui-*') if p.is_file() and os.access(p,os.X_OK)]
    chosen=[]
    for p in files:
        run=subprocess.run([p,'--list','--exact',which],capture_output=True,text=True,timeout=15)
        if which+': test'in run.stdout:chosen.append(p)
    assert len(chosen)==1,(files,chosen)
    binary=root/(role+'-bin')
    shutil.copy2(chosen[0],binary)
    def read(*args):
        return subprocess.run(['readelf','-W',*args,binary],capture_output=True,text=True).stdout
    debug=subprocess.run([binary,which,'--exact'],env=os.environ|{'LD_DEBUG':'statistics'},capture_output=True,text=True,check=True)
    assert '1 passed' in debug.stdout
    return dict(source=str(chosen[0]),bytes=binary.stat().st_size,sha256=hashlib.file_digest(binary.open('rb'),'sha256').hexdigest(),
                phdr=read('-l'),sections=read('-S'),dynamic=read('-d'),comment=read('-p','.comment'),loader=debug.stderr)
def times(root):
    # Repeat a single short test process, alternating binaries so the load
    # before each pair is the same. Report resource and elapsed counters.
    t={}
    for block in range(10):
        order=('control','candidate')if block%2==0 else ('candidate','control')
        for role in order:
            binary=root/(role+'-bin')
            cmd=[str(binary),which,'--exact']
            run=lambda:subprocess.run(cmd,capture_output=True,check=True)
            run()
            prior=resource.getrusage(resource.RUSAGE_CHILDREN)
            start=time.perf_counter()
            for _ in range(32):run()
            wall=time.perf_counter()-start
            post=resource.getrusage(resource.RUSAGE_CHILDREN)
            t.setdefault(role,[]).append(dict(block=block,runs=32,wall=wall,user=post.ru_utime-prior.ru_utime,kernel=post.ru_stime-prior.ru_stime,
                                               minor=post.ru_minflt-prior.ru_minflt,major=post.ru_majflt-prior.ru_majflt))
    return t
