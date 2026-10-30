"""Reopen every original, uncompressed file in all overlapping snapshots, guarding pre-clock evidence."""
import argparse,hashlib,json,zipfile
from pathlib import Path

def inspect(archives):
    previous={};reports=[]
    for path in archives:
        with path.open('rb') as f:physical=hashlib.file_digest(f,'sha256').hexdigest()
        with zipfile.ZipFile(path) as z:
            infos=[q for q in z.infolist() if not q.is_dir()]
            names=[q.filename for q in infos]
            assert len(names)==len(set(names)) and all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names)
            members={}
            for name in names:
                with z.open(name) as f:members[name]=hashlib.file_digest(f,'sha256').hexdigest()
            removed=sorted(set(previous)-set(members));changed=sorted(n for n in previous.keys()&members.keys() if previous[n]!=members[n])
            assert not removed and not changed, (path.name,removed,changed)
            root=hashlib.sha256(json.dumps(members,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            reports.append({'file':path.name,'sha256':physical,'bytes':path.stat().st_size,'members':len(members),'carried_unchanged':len(previous),'file_map_sha256':root})
            previous=members
    return reports
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archives',type=Path,nargs='+');p.add_argument('--output',type=Path);a=p.parse_args()
    rows=inspect(a.archives);s=json.dumps(rows,sort_keys=True,indent=2)+'\n'
    print(s,end='')
    if a.output:
        if a.output.exists():assert a.output.read_text()==s
        else:a.output.write_text(s)
