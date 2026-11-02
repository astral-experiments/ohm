"""Read-only system-input capability observation. Leases are exercised only on new private controls."""
from pathlib import Path
import errno
import fcntl
import hashlib
import json
import mmap
import os
import signal
import stat
import struct
import subprocess
import sys


def op(fn):
    try:return {"result":fn()}
    except OSError as e:return {"errno":e.errno,"error":errno.errorcode.get(e.errno,str(e.errno))}


def run(out,system_copy,owned):
    assert os.geteuid()>0 and system_copy.stat().st_uid==0 and owned.stat().st_uid==os.getuid()
    status={k:v.strip() for k,v in [line.split(":",1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line]}
    assert all(int(status[k],16)==0 for k in ("CapEff","CapPrm","CapInh","CapBnd","CapAmb")) and status["NoNewPrivs"]=="1"
    members=[]
    for p in map(Path,("/usr/lib/x86_64-linux-gnu/libutil.a","/usr/lib/x86_64-linux-gnu/libgcc_s.so.1","/usr/lib/x86_64-linux-gnu/libc.so.6")):
        with p.open("rb") as f:
            s=os.fstat(f.fileno());assert stat.S_ISREG(s.st_mode) and s.st_uid==0 and not os.access(p,os.W_OK,effective_ids=True)
            seals=op(lambda:fcntl.fcntl(f,fcntl.F_GET_SEALS))
            # struct fsverity_digest { u16 algorithm, u16 capacity; u8 digest[]; }, FS_IOC_MEASURE_VERITY.
            verity=op(lambda:fcntl.ioctl(f,0xc0046686,struct.pack("=HH",0,64)+bytes(64)).hex())
            flags=op(lambda:struct.unpack("=Q",fcntl.ioctl(f,0x80086601,bytes(8)))[0])
            members.append({"file":str(p),"uid":s.st_uid,"mode":stat.S_IMODE(s.st_mode),"size":s.st_size,"sha256":hashlib.file_digest(f,"sha256").hexdigest(),
                            "mount":subprocess.check_output(["findmnt","-rn","-T",p,"-o","TARGET,FSTYPE,VFS-OPTIONS"],text=True).strip(),
                            "seals":seals,"verity":verity,"flags":flags,"writable":False})
    assert members[0]["size"]==8 and members[0]["sha256"]==hashlib.sha256(b"!<arch>\n").hexdigest()
    signal.signal(signal.SIGIO,signal.SIG_IGN)
    with system_copy.open("rb") as foreign:
        owner=op(lambda:fcntl.fcntl(foreign,fcntl.F_SETLEASE,fcntl.F_RDLCK))
        if "result" in owner:fcntl.fcntl(foreign,fcntl.F_SETLEASE,fcntl.F_UNLCK)
    with owned.open("rb") as guard:
        ours=op(lambda:fcntl.fcntl(guard,fcntl.F_SETLEASE,fcntl.F_RDLCK))
        if "result" in ours:fcntl.fcntl(guard,fcntl.F_SETLEASE,fcntl.F_UNLCK)
        with owned.open("r+b") as producer:m=mmap.mmap(producer.fileno(),0)
        with m:
            m[0]=m[0]
            mapping=op(lambda:fcntl.fcntl(guard,fcntl.F_SETLEASE,fcntl.F_RDLCK))
            if "result" in mapping:fcntl.fcntl(guard,fcntl.F_SETLEASE,fcntl.F_UNLCK)
    d={"source":os.environ.get("QA_SOURCE"),"boot":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"kernel":os.uname().release,"uid":os.getuid(),"caps":{k:status[k] for k in ("CapEff","CapBnd","NoNewPrivs")},"system":members,"private_root_owned_lease":owner,"private_own_lease":ours,"private_mapped_lease":mapping}
    out.write_text(json.dumps(d,indent=2)+"\n");print(json.dumps(d),flush=True)
    assert owner.get("errno") in (errno.EACCES,errno.EPERM) and ours=={"result":0} and mapping.get("errno") in (errno.EAGAIN,errno.EACCES)
    assert all(f["seals"].get("errno") in (errno.EINVAL,errno.ENOTTY,errno.EOPNOTSUPP) and f["verity"].get("errno") in (errno.ENODATA,errno.ENOTTY,errno.EOPNOTSUPP) for f in members)


if __name__=="__main__":run(*map(Path,sys.argv[1:]))
