"""Count allocated storage in the complete target + build tree and alternate sessions."""
from collections import Counter, defaultdict
import gzip
import json
import os
from pathlib import Path
import stat
import subprocess

def category(name):
    if name.endswith(".o"):
        return "codegen objects"
    if name in {"ohm-build-dep-graph.bin","dep-graph.bin"}:
        return name
    if "query-cache" in name:
        return name
    if name.endswith(".rmeta"):
        return "compiler metadata"
    if name.endswith(".bc"):
        return "LLVM bitcode"
    if name.endswith(".rgu"):
        return "codegen units"
    if name.startswith("s-") or name in {".",".."}:
        return "directories"
    return name

def session_dirs(roots):
    final={}
    for root in roots:
        for parent,dirs,_ in os.walk(root):
            parent=Path(parent)
            sessions=[d for d in dirs if d.startswith("s-") and not d.endswith("-working")]
            if "incremental" in parent.parts and sessions:
                latest=max(sessions,key=lambda s:(int(s.split("-")[1],36),s))
                for name in sessions:
                    final[parent/name]=name!=latest
                dirs[:]=[s for s in dirs if s not in sessions]
    return final

def settle_files(roots):
    """Flush only this installation's files before observing their final blocks."""
    seen=set()
    for root in roots:
        for parent,dirs,files in os.walk(root,topdown=False,followlinks=False):
            for path in [*(Path(parent)/n for n in files),Path(parent)]:
                info=path.lstat()
                inode=(info.st_dev,info.st_ino)
                if inode in seen or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    continue
                seen.add(inode)
                fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
                try:
                    opened=os.fstat(fd)
                    assert (opened.st_dev,opened.st_ino)==inode
                    os.fsync(fd)
                finally:
                    os.close(fd)


def census(target,shared,evidence=None):
    roots=(Path(target),Path(shared))
    settle_files(roots)
    sessions=session_dirs(roots)
    nodes={}
    per_tree={}
    paths={}
    for root in roots:
        per_tree[root.name]=set()
        def visit(path,alternate=False):
            info=path.lstat();inode=(info.st_dev,info.st_ino)
            paths[str(path)]=[info.st_dev,info.st_ino,info.st_nlink,info.st_mode,info.st_blocks,info.st_size]
            per_tree[root.name].add(inode)
            if path in sessions:
                alternate=sessions[path]
            row=nodes.setdefault(inode,[info.st_blocks*512,False,set(),info.st_size])
            assert row[0]==info.st_blocks*512 and row[3]==info.st_size
            row[1]|=not alternate
            if alternate:
                row[2].add("directories" if stat.S_ISDIR(info.st_mode) else category(path.name))
            if stat.S_ISDIR(info.st_mode):
                for child in path.iterdir():
                    visit(child,alternate)
        visit(root)
    split=Counter()
    for blocks,other,names,size in nodes.values():
        if not other:
            split[" | ".join(sorted(names))]+=blocks
    total=sum(row[0] for row in nodes.values())
    # GNU find is a second independent reader of the exact allocated inodes,
    # including a hard link shared across the two roots. Both scopes are whole trees.
    found=subprocess.check_output(["/usr/bin/find",*roots,"-printf","%D %i %b\\n"])
    by_inode={}
    for line in found.splitlines():
        dev,ino,blocks=map(int,line.split())
        assert by_inode.setdefault((dev,ino),blocks)==blocks
    found_bytes=sum(by_inode.values())*512
    du=subprocess.check_output(["/usr/bin/du","--summarize","--block-size=1","--",*roots],text=True)
    du_bytes=sum(int(line.split()[0]) for line in du.splitlines())
    if evidence is not None:
        receipt={"python_bytes":total,"find_bytes":found_bytes,"du_bytes":du_bytes,"python_inodes":len(nodes),
                 "find_inodes":len(by_inode),"du":du.splitlines()}
        (evidence/"allocation-readers.json").write_text(json.dumps(receipt,sort_keys=True)+"\n")
    if set(nodes)!=set(by_inode) or total!=found_bytes or total!=du_bytes:
        if evidence is not None:
            details=subprocess.check_output(["/usr/bin/du","--all","--block-size=1","--null","--",*roots])
            (evidence/"du-paths.bin.gz").write_bytes(gzip.compress(details,mtime=0))
            (evidence/"python-paths.json.gz").write_bytes(gzip.compress(json.dumps(paths,sort_keys=True).encode(),mtime=0))
            (evidence/"find-inodes.txt.gz").write_bytes(gzip.compress(found,mtime=0))
        raise RuntimeError(("inconsistent allocated-byte counts after fsync",total,found_bytes,du_bytes))
    return {"target_and_build_bytes":total,"subtrees_within_each_root":{k:sum(nodes[i][0] for i in ids) for k,ids in per_tree.items()},
            "alternate_exclusive_bytes":sum(split.values()),"alternate_by_file_type":dict(split.most_common()),
            "sessions":{str(p.relative_to(roots[0] if p.is_relative_to(roots[0]) else roots[1])):("older" if older else "latest") for p,older in sessions.items()},"du":du.splitlines()}

def record(root,target,build,role,phase):
    j=census(target,build)
    j.update(role=role,phase=phase)
    (root/"allocated.json").write_text(json.dumps(j,sort_keys=True,indent=2)+"\n")
