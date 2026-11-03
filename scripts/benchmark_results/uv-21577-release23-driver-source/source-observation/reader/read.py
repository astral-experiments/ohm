"""Reduce only a launch-time trace of the source/receipt predicate in one unchanged GNU/Linux rustc."""
import ast
import gzip
import hashlib
import json
import os
import re
from pathlib import Path

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def load(path):
    return json.loads(Path(path).read_bytes())

def save(path, data):
    with Path(path).open("x") as f:
        json.dump(data, f, sort_keys=True, indent=2)
        f.write("\n")

def require(condition, message):
    if not condition:
        raise ValueError(str(message))

PATH_ARG = re.compile(r'"(?:[^"\\]|\\.)*"')
SYSCALL = re.compile(r"^(\w+)\((.*)\)\s+=\s+(-?[0-9]+)(?:<[^>]*>)?(?:\s+([A-Z][A-Z0-9_]+))?")
SOURCE_STAT = {"statx", "newfstatat", "stat", "stat64", "fstatat64"}
OPEN = {"openat", "openat2", "creat", "open"}
STAT_ID = re.compile(r"(?:^|/)\b([0-9a-f]+)-([0-9a-f]+)\.rlib$")

def path_arg(name, args, cwd):
    m = PATH_ARG.search(args)
    if m is None:
        return None
    path = os.fsdecode(ast.literal_eval("b" + m.group()))
    if not path:
        return None
    if not os.path.isabs(path):
        prefix = args[:m.start()].strip()
        if name in {"statx", "newfstatat", "openat", "openat2", "fstatat64"} and not prefix.startswith("AT_FDCWD"):
            base = re.fullmatch(r"\d+<(/[^>]*)>,\s*", prefix)
            if not base:
                return None
            path = os.path.join(base[1], path)
        else:
            path = os.path.join(cwd, path)
    return os.path.normpath(path)

def integer_field(args, key):
    m = re.search(r"\b" + key + r"=(0x[0-9a-f]+|[0-9]+)\b", args)
    require(m, ("missing stat field", key, args))
    return int(m[1], 0)

def stat_values(name, args):
    if name == "statx":
        mask = re.search(r"\bstx_mask=([^,}]+)", args)
        require(mask and ("STATX_ALL" in mask[1] or "STATX_BASIC_STATS" in mask[1] or
                          all(key in mask[1] for key in ("STATX_INO","STATX_TYPE","STATX_SIZE"))), ("statx mask",args))
        major = integer_field(args, "stx_dev_major")
        minor = integer_field(args, "stx_dev_minor")
        ino, size = integer_field(args, "stx_ino"), integer_field(args, "stx_size")
        mode = re.search(r"\bstx_mode=(S_IF\w+)", args)
    else:
        m = re.search(r"\bst_dev=makedev\((0x[\da-f]+|\d+), (0x[\da-f]+|\d+)\)", args)
        require(m, ("abbreviated or unsupported stat result", args))
        major, minor = (int(v, 0) for v in m.groups())
        ino, size = integer_field(args, "st_ino"), integer_field(args, "st_size")
        mode = re.search(r"\bst_mode=(S_IF\w+)", args)
    require(mode, ("missing file type", args))
    return {"dev": os.makedev(major, minor), "ino": ino, "size": size, "type": mode[1]}

def stream(raw, cwd):
    events = []
    for line_no, line in enumerate(raw.decode("ascii").splitlines(), 1):
        if "<unfinished ...>" in line or "resumed>" in line:
            raise ValueError(("incomplete per-TID syscall", line))
        m = SYSCALL.match(line)
        if not m:
            require(not line.startswith(tuple(n+"(" for n in SOURCE_STAT | OPEN | {"clone","clone3"})),
                    ("unparsed selected syscall", line))
            continue
        name, args, rc, err = m.groups()
        rc = int(rc)
        path = path_arg(name, args, cwd) if name in SOURCE_STAT | OPEN | {"execve","execveat"} else None
        events.append((line_no, name, args, rc, err, path))
    return events

def reduce(visit):
    visit = Path(visit)
    request = load(visit/"request.json")
    finished = load(visit/"trace.json")
    require(finished["exit"] == 0 and finished["request"] == digest((visit/"request.json").read_bytes()), "trace exit/start")
    domain = request["policy"]
    opens = []
    writes = []
    checks = []
    threads = {}
    sources = {}
    execs = {}
    require(sorted(v.name for v in visit.glob("syscall.*.gz"))==sorted(e["file"] for e in finished["files"]), "incomplete physical trace inventory")
    for entry in finished["files"]:
        filename = entry["file"]
        require(re.fullmatch(r"syscall\.[1-9][0-9]*\.gz", filename), ("unrecognized trace",filename))
        tid = int(filename.split(".")[1])
        keep = []
        raw = gzip.decompress((visit/filename).read_bytes())
        require(digest(raw) == entry["sha256"] and len(raw) == entry["bytes"], ("raw trace changed", filename))
        for line, name, args, rc, err, path in stream(raw, request["cwd"]):
            if name in {"execve","execveat"}:
                require(re.search(r", (?:0x[0-9a-f]+ /\* [0-9]+ vars \*/|NULL)(?:, [A-Z0-9_|]+)?$",args),
                        ("exec environment is not a redacted pointer",tid,line))
                if rc==0:execs.setdefault(tid,[]).append((line,path))
            if name in {"clone", "clone3"} and rc > 0 and "CLONE_THREAD" in args:
                require(rc not in threads, ("ambiguous thread birth",rc))
                threads[rc] = tid
            if name in OPEN and path and rc >= 0:
                if path == domain+"/driver" and "O_RDONLY" in args:
                    opens.append((tid, line))
                if re.fullmatch(re.escape(domain) + r"/[1-9][0-9]*\.exports", path) and ("O_WRONLY" in args or name == "creat") and ("O_CREAT" in args or name == "creat"):
                    writes.append((tid, line, int(Path(path).stem)))
            if name in SOURCE_STAT and path and path.endswith(".rlib"):
                keep.append((line,name,rc,err,path, stat_values(name,args) if rc == 0 else None))
                if str(Path(path).parent) == domain:
                    checks.append((tid, line))
        sources[tid] = keep
    require(len(writes) == 1, ("missing/excess PID-specific export write",opens,writes))
    end_tid, hi, pid = writes[0]
    earlier = [(t,n) for t,n in opens if t==end_tid and n < hi]
    require(len(earlier)==1, ("missing/excess owning entry before write",earlier,writes))
    tid, lo = earlier[0]
    require(tid == end_tid and lo < hi and pid in sources, ("thread/process boundary",opens,writes))
    require(execs.get(pid)==[(1,request["argv"][0])],("trace did not start at exec of the actual compiler",pid,execs.get(pid)))
    group_tid = tid
    while group_tid != pid:
        require(group_tid in threads, ("policy thread outside the original rustc PID",group_tid,pid))
        parent = threads[group_tid]
        require(parent != group_tid, "self thread birth")
        group_tid = parent
    require(checks and all(t == tid and lo < n < hi for t,n in checks), ("policy receipt outside selected region",checks))
    region = [e for e in sources[tid] if lo < e[0] < hi]
    require(len(region) == 2*len(checks), ("unpaired archive metadata operation",[(r[0],r[4]) for r in region]))
    rows = []
    for original, receipt in zip(region[::2],region[1::2]):
        sl,sc,rc,err,path,stat = original
        rl,rs,rr,re_,rp,receipt_stat = receipt
        require(str(Path(path).parent) != domain and rc == 0 and stat is not None and stat["type"] == "S_IFREG",
                ("unqualified archive stat", original))
        key = f"{stat['dev']:x}-{stat['ino']:x}"
        require(rl == sl+1, ("intervening syscall between source and receipt",sl,rl))
        require(rp == domain+"/"+key+".rlib", ("receipt does not name previous physical archive",original,receipt))
        require(rr == 0 or (rr == -1 and re_=="ENOENT"), ("unsupported receipt outcome",receipt))
        same = rr == 0 and (stat["dev"],stat["ino"]) == (receipt_stat["dev"],receipt_stat["ino"])
        rows.append({"source":path,"physical":stat,"key":key,"source_line":sl,"source_call":sc,
                     "receipt_line":rl,"receipt_call":rs,"receipt_stat":receipt_stat,"errno":re_ if rr < 0 else None,
                     "matched":same})
    require(len({r["source"] for r in rows}) == len(rows), "repeated CStore archive path requires investigation")
    return {"pid":pid,"tid":tid,"policy":domain,"start_line":lo,"finish_line":hi,"driver_opens":[list(x)for x in opens],"rows":rows}
