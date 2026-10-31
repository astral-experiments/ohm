"""Require a real forked reader and reject the same read after a foreign exec."""
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_trace import owner_reads
from registration import need, sha

PROGRAM = """
#include <unistd.h>
#include <pthread.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <stdlib.h>
static void *consume(void *arg) {
    char c = 0;
    int fd = open(arg, O_RDONLY);
    if (fd < 0 || read(fd, &c, 1) != 1 || c != 'E') _exit(4);
    return NULL;
}
int main(int argc, char **argv) {
    pid_t child = fork();
    if (child == -1) return 5;
    if (child == 0) {
        if (argv[1][0] == 'n') { execl("/usr/bin/cat", "cat", argv[2], (char *)0); _exit(6); }
        pthread_t worker;
        if (pthread_create(&worker, 0, consume, argv[2])) _exit(7);
        if (pthread_join(worker, 0)) _exit(8);
        _exit(0);
    }
    int status;
    return waitpid(child, &status, 0) == child && WIFEXITED(status) ? WEXITSTATUS(status) : 9;
}
"""


def check(root):
    root.mkdir()
    src=root/"probe.c";src.write_text(PROGRAM)
    payload=root/"payload.a";payload.write_bytes(b"ELF identity witness\n")
    exe=root/"witness";subprocess.run(["cc","-O1","-pthread",src,"-o",exe],check=True)
    result={"source":sha(src),"witness":sha(exe),"foreign_image":sha("/usr/bin/cat")}
    for role in ("positive","negative"):
        out=root/role;out.mkdir()
        cmd=["strace","-ff","-qq","-yy","-s","16384","-e","trace=execve,execveat,openat,clone,clone3,fork,vfork",
             "-o",str(out/"pid"),"/usr/bin/env",str(exe),role,str(payload)]
        p=subprocess.run(cmd,capture_output=True,check=True)
        need(p.stdout==(b"" if role=="positive" else payload.read_bytes()),"wrong real reader output")
        raw={int(f.suffix[1:]):f.read_text().splitlines() for f in out.glob("pid.*")}
        reads=[(pid,line) for pid,lines in raw.items() for line in lines
               if re.search(r"= [0-9]+<"+re.escape(str(payload))+r">$",line)]
        need(reads,"missing physical descriptor in observer calibration")
        def classify(path):
            return "wild" if path==str(exe) else "cargo" if path=="/usr/bin/env" else "other"
        if role=="positive":
            answer=owner_reads(raw,str(payload),classify)
            lineage=answer["linux_fd_evidence"][0]["lineage"]
            need([item["kind"] for item in lineage if "kind" in item]==["thread","process"],"lost physical process + thread witness")
            result[role]=answer
        else:
            try:
                owner_reads(raw,str(payload),classify)
            except ValueError as error:
                need(str(error)=="no authentic Cargo, Wild or read by that inherited image","unrelated observer rejection")
                need(all(any(line.startswith('execve("/usr/bin/cat",') and re.search(r"= 0$",line)
                             for line in raw[pid]) for pid,_ in reads),"missing foreign image transition")
                result[role]={"refused":str(error),"physically_read":reads}
            else:
                raise ValueError("attributed the foreign executable's read to its former image")
    return result
