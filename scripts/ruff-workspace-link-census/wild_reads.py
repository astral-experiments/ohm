"""Summarize only the actual Wild process and its kernel-cloned workers, including failed lookups."""
from pathlib import Path
import ast
import collections
import hashlib
import json
import os
import re
import stat
import time
import census

NAMES={"lib"+n+ext for n in ("gcc_s","util","rt","pthread","m","dl","c") for ext in (".so",".a")}


def capture(folder,whole_cost,visible):
    native=json.loads((folder/"native-processes.json").read_bytes())
    links=native["linkers"]
    if not links:return census.put(folder/"wild-files.json",{"linkers":0,"selection":None})
    assert len(links)==1,(folder,len(links))
    pid=links[0]["pid"];parents={}
    rows={}
    for log in folder.glob("exec.[0-9]*"):
        p=int(log.suffix[1:]); rows[p]=log
        for line in log.read_text(errors="replace").splitlines():
            m=re.match(r'^(?:clone3?\(|fork\(|vfork\(|<\.\.\. (?:clone3?|fork|vfork) resumed>).* = (\d+)$',line)
            if m:parents[int(m[1])]=p
    def is_wild(p):
        while p!=pid and p in parents:p=parents[p]
        return p==pid
    opens=set();read_write=set();failed=collections.defaultdict(set);active=[];maps={};unknown=set()
    for p,log in rows.items():
        if not is_wild(p):continue
        for s in log.read_text(errors="replace").splitlines():
            if s.startswith("mmap("):
                m=re.match(r'mmap\([^,]+, (\d+), [^,]+, [^,]+, \d+<([^>]+)>, ',s)
                if m and "= -1 " not in s:maps[m[2]]=maps.get(m[2],0)+int(m[1])
                continue
            if not s.startswith(("open(","openat(","openat2(","access(","faccessat","stat(","lstat(","statx(","newfstatat(","readlink")):continue
            path=re.search(r'"((?:[^"\\]|\\.)*)"',s)
            if not path:continue
            name=ast.literal_eval('"'+path[1]+'"')
            if not name:continue
            if not os.path.isabs(name):unknown.add(name);continue
            err=re.search(r'= -1 (\w+)',s)
            if err:failed[name].add(err[1])
            elif s.startswith(("open(","openat(","openat2(")) and re.search(r'= \d+',s) and ("O_RDONLY" in s or "O_RDWR" in s):
                (read_write if "O_RDWR" in s else opens).add(name)
            if Path(name).name in NAMES or name.endswith("active.o"):
                active.append([p,s])
    def info(name):
        try:s=os.stat(name)
        except OSError:return None
        return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
    candidates={name:info(name) for name in sorted(opens)}
    observed={name:sorted(v) for name,v in sorted(failed.items())}
    stable={};search_err=[n for n in sorted(failed) if Path(n).name in NAMES]
    for name,st in candidates.items():
        if not st or not stat.S_ISREG(st[2]) or name.startswith(("/proc/","/dev/","/sys/")):continue
        stable.setdefault(tuple(st[:2]),name)
    trials=[];sums={}
    if whole_cost:
        size=sum(candidates[n][5] for n in stable.values());assert size<2**30
        for i in range(5):
            t=time.monotonic_ns();c=time.process_time_ns();states={}
            for n in search_err:
                try:os.lstat(n);states[n]=True
                except FileNotFoundError:states[n]=False
            mid=time.monotonic_ns();c1=time.process_time_ns()
            new={}
            for n in stable.values():
                with open(n,"rb") as f:new[n]=hashlib.file_digest(f,"sha256").hexdigest()
            end=time.monotonic_ns();c2=time.process_time_ns()
            if i:assert sums==new
            sums=new
            trials.append({"negative_names":len(states),"negatives_still_absent":sum(not v for v in states.values()),"lstat_elapsed_ns":mid-t,"lstat_cpu_ns":c1-c,
                           "read_sha256_elapsed_ns":end-mid,"read_sha256_cpu_ns":c2-c1,"hashed_files":len(stable),"hashed_bytes":size})
    census.put(folder/"wild-files.json",{"linkers":1,"wild_pid":pid,"threads":sorted(p for p in rows if is_wild(p)),
         "even_failing_probes":observed,"read_opens":candidates,"writable_opens_excluded":sorted(read_write),"mmap_lengths_by_fd_name":maps,"relative_names":sorted(unknown),"native_lookup_syscalls":active,
         "selected_candidate":str(visible),"selected_candidate_opened":str(visible) in opens,
         "distinct_postlink_regular_inodes":len(stable),"postlink_regular_bytes":sum(candidates[n][5] for n in stable.values()),
         "distinct_native_negative_names":search_err,"hashed_digests":sums,"hot_observation_only":trials})
