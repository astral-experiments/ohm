"""Small native fd/identity calibration. It never invokes Cargo or rustc."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path
SRC = Path(__file__).resolve().parent
def calibrate(root, so):
    root.mkdir()
    actor = root/'actor'
    c = root/'actor.c'
    c.write_text('#define _GNU_SOURCE\n#include <fcntl.h>\n#include <sys/stat.h>\n#include <time.h>\n#include <unistd.h>\nint main(int n,char**v){struct timespec t[2]={{0,UTIME_OMIT},{1001,54321}}; int f=open(v[1],O_RDONLY);return n!=2||f<0||futimens(f,t)||close(f);}\n')
    subprocess.run(['cc','-Wall','-Werror',str(c),'-o',str(actor)],check=True)
    dep=root/'libinsta-test.rlib';dep.write_bytes(b'one two three');alias=root/'alias';os.link(dep,alias)
    ref=root/'ref';ref.write_bytes(dep.read_bytes());ref.chmod(0o444)
    foreign=root/'other';foreign.write_bytes(dep.read_bytes());other=root/'different-actor';shutil.copy(actor,other)
    config=root/'policy';log=root/'ledger';log.touch()
    var=os.environ|{'LD_PRELOAD':str(so),'QA_INSTA_CONFIG':str(config),'QA_INSTA_ACTOR':str(actor)}
    records=[]
    for who,p,mode,eq in [(actor,dep,'allow',True),(actor,alias,'hold',True),(actor,foreign,'hold',True),
                           (other,dep,'hold',True),(actor,dep,'hold',False)]:
        if not eq:dep.write_bytes(b'one two thrEe')
        os.utime(p,ns=(1_999_999_999,8_888_888_888))
        config.write_text(f'{mode} {dep.stat().st_dev} {dep.stat().st_ino} {ref} {log}\n')
        offset=log.stat().st_size;subprocess.run([who,p],env=var,check=True)
        held=(mode=='hold' and eq and who==actor and p.samefile(dep))
        assert p.stat().st_mtime_ns==(8_888_888_888 if held else 1001_000_054_321)
        line=log.read_bytes()[offset:].decode().strip()
        if not (who==actor and p.samefile(dep)):assert not line
        else:
            fields=line.split('\t');assert len(fields)==23 and [int(x) for x in fields[4:7]]==[int(eq),1,int(held)]
        records.append([who.name,p.name,mode,eq,held,line])
    return records
if __name__=='__main__':
    import json
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp);so=t/'observer.so'
        subprocess.run(['cc','-O2','-Wall','-Werror','-shared','-fPIC',SRC/'archive_time.c','-ldl','-o',so],check=True)
        print(json.dumps(calibrate(t/'cal',so),indent=2))
