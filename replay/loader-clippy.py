from pathlib import Path
import os,subprocess,shutil,tempfile,resource,threading,json,sys,platform,hashlib
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
archive=Path(sys.argv[1])
result={'archive':archive.name,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'platform':platform.platform()}
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp).resolve()
    subprocess.run(['tar','-xzf',archive,'-C',root],check=True)
    (original,)=list(root.glob('rust-*/clippy-preview/bin/clippy-driver'))
    tools=root/'stage2-tools-bin'
    tools.mkdir()
    source=tools/'clippy-driver'
    original.rename(source)
    bin=root/'stage2/bin'
    bin.mkdir(parents=True)
    driver=bin/'clippy-driver'
    (lib,)=list(root.glob('rust-*/rustc/lib'))
    (bin.parent/'lib').symlink_to(lib,target_is_directory=True)
    result['loader']=subprocess.check_output(['otool','-L',source],text=True)
    items={}
    for style in ['hardlink','copy']:
        driver.unlink(missing_ok=True)
        if style=='hardlink':driver.hardlink_to(source)
        else:shutil.copy2(source,driver)
        halt=threading.Event()
        def disturb():
            while not halt.is_set():
                with source.open('rb') as f:
                    f.read(1)
        warmup=subprocess.check_output([driver,'-vV'])
        result['compiler']=warmup.decode()
        t=threading.Thread(target=disturb)
        t.start()
        failures=[]
        try:
            for n in range(100):
                proc=subprocess.run([driver,'-vV'],capture_output=True)
                if proc.returncode:
                    stderr=proc.stderr.decode()
                    assert str(source) in stderr and '@rpath/' in stderr,(proc.returncode,stderr)
                    failures.append(stderr)
                    if len(failures)==2:break
                else:assert proc.stdout==warmup
        finally:
            halt.set()
            t.join()
        items[style]=dict(attempts=n+1,errors=failures)
    result['layout']=items
print(json.dumps(result,indent=2))
