"""Count allocated storage in the complete target + build tree and alternate sessions."""
from collections import Counter, defaultdict
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

def census(target,shared):
    roots=(Path(target),Path(shared))
    sessions=session_dirs(roots)
    nodes={}
    per_tree={}
    for root in roots:
        per_tree[root.name]=set()
        def visit(path,alternate=False):
            info=path.lstat();inode=(info.st_dev,info.st_ino)
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
    du=subprocess.check_output(["du","-s","-x","-B1","--",*roots],text=True)
    assert sum(int(line.split()[0]) for line in du.splitlines())==total
    return {"target_and_build_bytes":total,"subtrees_within_each_root":{k:sum(nodes[i][0] for i in ids) for k,ids in per_tree.items()},
            "alternate_exclusive_bytes":sum(split.values()),"alternate_by_file_type":dict(split.most_common()),
            "sessions":{str(p.relative_to(roots[0] if p.is_relative_to(roots[0]) else roots[1])):("older" if older else "latest") for p,older in sessions.items()},"du":du.splitlines()}

def record(root,target,build,role,phase):
    j=census(target,build)
    j.update(role=role,phase=phase)
    (root/"allocated.json").write_text(json.dumps(j,sort_keys=True,indent=2)+"\n")
