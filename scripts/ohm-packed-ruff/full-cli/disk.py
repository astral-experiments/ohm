"""Reopen every pathname with GNU stat and persist a portable paired-root ledger."""
import collections
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'harness'))
import count
from omission import publish, require


def allocated(target, shared, evidence, *, failed_sessions=()):
    target,shared=map(Path,(target,shared))
    roots=(target,shared); positions={p.name:p for p in roots}
    require(target!=shared and target.resolve()==target and shared.resolve()==shared and not target.is_relative_to(shared) and not shared.is_relative_to(target), 'separate canonical storage roots required')
    found=count.census(target,shared,evidence)
    names=subprocess.check_output(['/usr/bin/find',*roots,'-print0']).split(b'\0');require(names.pop()==b'','truncated pathname inventory')
    table={};paths={};members={p.name:set() for p in roots};packed={};working=set();permitted=set(failed_sessions)
    for start in range(0,len(names),128):
        group=names[start:start+128]
        raw=subprocess.check_output(['/usr/bin/stat','--printf','%d %i %h %f %b %s\\n','--',*group]).splitlines()
        require(len(group)==len(raw),'incomplete GNU stat group')
        for name,line in zip(group,raw,strict=True):
            path=Path(os.fsdecode(name));parent=next(p for p in roots if path.is_relative_to(p));rel=str(Path(parent.name)/path.relative_to(parent))
            d,ino,nlink,mode,blocks,size=line.split();row=(int(d),int(ino),int(nlink),int(mode,16),int(blocks),int(size));key=row[:2]
            require(table.setdefault(key,row)==row and rel not in paths,'changed alias or duplicate name');table[key]=row;paths[rel]=row;members[parent.name].add(key)
            if path.name.startswith('ohm-packed-object-') and stat.S_ISREG(row[3]):packed[key]=row[4]*512
            if path.name.startswith('s-') and path.name.endswith('-working') and 'incremental' in path.parts:
                require(rel in permitted,('unexpected unfinished incremental session',rel));working.add(rel)
    require(working==permitted,'failed-session inventory changed during allocation')
    independent=subprocess.check_output(['/usr/bin/find',*roots,'-printf','%D %i %b\\n']);inode={}
    for line in independent.splitlines():
        dev,i,b=map(int,line.split());require(inode.setdefault((dev,i),b)==b,'GNU find inconsistent alias')
    require({k:r[4] for k,r in table.items()}==inode,'GNU find and stat inode sets differ')
    totals={k:sum(table[i][4]*512 for i in keys) for k,keys in members.items()}
    shared_keys=set.intersection(*members.values());both=sum(table[i][4]*512 for i in shared_keys)
    union=sum(row[4]*512 for row in table.values());readers=json.loads((evidence/'allocation-readers.json').read_bytes())
    require(len(positions)==2 and totals==found['subtrees_within_each_root'] and union==sum(totals.values())-both,'unmeasured or overlapping tree')
    require(union==found['target_and_build_bytes']==readers['python_bytes']==readers['find_bytes']==readers['du_bytes'],'allocation readers disagree')
    publish(evidence/'path-inodes.json.gz',paths)
    result={'allocated':union,'roots':totals,'shared_inodes':len(shared_keys),'bytes_aliased_between_roots':both,'all_inodes':len(table),'all_names':len(paths),'packed_files':len(packed),'packed_bytes':sum(packed.values()),'older_exclusive_bytes':found['alternate_exclusive_bytes'],'sessions':found['sessions'],'failed_sessions':sorted(working)}
    publish(evidence/'storage.json',result);return result
