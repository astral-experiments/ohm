"""Count every hard-linked inode once across the private target and shared build roots."""
import json
import os
from pathlib import Path
import stat

from study import compress_bytes, need, save


def snapshot(work, out):
    records = []
    objects = {}
    sessions = {}
    for root in [work/"target", work/"shared"]:
        need(root.is_dir() and not root.is_symlink(), "unsafe accounting root")
        for group, dirs, names in os.walk(root,followlinks=False):
            group=Path(group)
            entries=[group] if group==root else []
            entries.extend(group/n for n in sorted(dirs+names))
            for path in entries:
                st=path.lstat()
                rel=path.relative_to(work)
                key=(st.st_dev,st.st_ino)
                identity=(st.st_size,st.st_blocks,stat.S_IFMT(st.st_mode))
                previous=objects.setdefault(key,[identity,set()])
                need(previous[0]==identity,"allocation or size changed during accounting")
                previous[1].add("incremental" in rel.parts)
                records.append([str(rel),*key,*identity,st.st_nlink])
                if path.is_dir() and not path.is_symlink() and path.name.startswith("s-") and path.parent.parent.name=="incremental":
                    sessions.setdefault(str(rel.parent),[]).append(path.name)
    values={"all":list(objects.values()),"only_incremental":[o for o in objects.values() if o[1]=={True}],
            "incremental_and_elsewhere":[o for o in objects.values() if o[1]=={True,False}]}
    out.mkdir(parents=True,exist_ok=True)
    raw=compress_bytes(out/"disk-inodes.json.gz",json.dumps(sorted(records),separators=(",",":")).encode())
    result = {n:{"inodes":len(items),"bytes":sum(m[0][0] for m in items),"allocated_bytes":512*sum(m[0][1] for m in items)} for n,items in values.items()}
    result.update(source_sha256=raw,incremental_sessions=sessions,entries=len(records))
    save(out/"disk.json",result)
    return result
