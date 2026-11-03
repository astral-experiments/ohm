"""Connect Cargo's nominally dirty checks to the physical compiler and retained output pair."""
from collections import Counter
from pathlib import Path
import gzip
import hashlib
import subprocess


def need(condition,detail):
    if not condition:raise ValueError(detail)


def paths(artifacts, enrolled):
    result={}
    for record in artifacts:
        target=record['target']
        identity=(target['name'],target['kind'][0])
        if identity not in enrolled:continue
        key='/'.join(identity)
        need(key not in result and len(target['kind'])==1,'duplicate physical target')
        meta,=[Path(f) for f in record['filenames'] if f.endswith('.rmeta')]
        depinfo=meta.with_name(meta.name.removeprefix('lib')).with_suffix('.d')
        need(meta.is_file() and depinfo.is_file(),('absent actual rustc output',key))
        result[key]={'rmeta':meta,'dep-info':depinfo}
    return result


def snapshot(known, members):
    def seal(path,kind):
        def stat():
            st=path.stat()
            return {'path':str(path.resolve()),'dev':st.st_dev,'ino':st.st_ino,'mtime_ns':st.st_mtime_ns,
                    'ctime_ns':st.st_ctime_ns,'bytes':st.st_size,'nlink':st.st_nlink}
        first=stat()
        with path.open('rb')as f:key=hashlib.file_digest(f,'sha256').hexdigest()
        suffix='.rmeta.zst' if kind=='rmeta' else '.rustc-dep-info.gz'
        packed=members/(key+suffix)
        if not packed.exists():
            if kind=='rmeta':
                with packed.open('xb') as out:subprocess.run(['zstd','-q','-3','-c',path],stdout=out,check=True)
            else:
                raw=path.read_bytes();need(hashlib.sha256(raw).hexdigest()==key, 'changed dep-info')
                with packed.open('xb') as out:out.write(gzip.compress(raw,compresslevel=2,mtime=0))
        need(stat()==first,'rustc output changed during off-clock snapshot')
        return {**first,'sha256':key}
    return {key:{kind:seal(path,kind) for kind,path in pair.items()} for key,pair in known.items()}


def reconcile(nominal,physical,before,after,invalid=False):
    owner=('ruff_linter','lib')
    typed=Counter(map(tuple,nominal))
    actual=Counter(map(tuple,physical))
    expected=typed.copy()
    if invalid:expected[owner]+=1
    need(not (actual-expected),('physical compiler absent from Cargo report',actual-expected))
    need(not invalid or actual[owner]==1,'expected failing owner did not execute')
    missing=sorted((expected-actual).elements())
    for item in missing:
        key='/'.join(item)
        need(key in before and key in after and set(before[key])==set(after[key])=={'rmeta','dep-info'},('no physical witness for dirty-only row',item))
        for kind in ('rmeta','dep-info'):
            old,new=before[key][kind],after[key][kind]
            need(old==new,('nominally dirty target without rustc had a changed output',item,kind))
    return [list(i) for i in missing]


def check_stored(members,witness):
    for key,pair in witness.items():
        for kind,row in pair.items():
            need({'dev','ino','mtime_ns','ctime_ns','nlink','bytes','path','sha256'}==row.keys() and row['dev']>0 and row['ino']>0 and row['mtime_ns']>0 and row['ctime_ns']>0 and row['nlink']>0 and row['bytes']>=0,'incomplete prior output stamp')
            path=members/(row['sha256']+('.rmeta.zst' if kind=='rmeta' else '.rustc-dep-info.gz'))
            if kind=='dep-info':data=gzip.decompress(path.read_bytes());need(len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'],'different rustc dep-info')
            else:
                need(kind=='rmeta','unknown native product')
                with subprocess.Popen(['zstd','-dcq',path],stdout=subprocess.PIPE)as proc:
                    digest=hashlib.sha256();count=0
                    for chunk in iter(lambda:proc.stdout.read(1<<20),b''):
                        digest.update(chunk);count+=len(chunk)
                    need(proc.wait()==0 and digest.hexdigest()==row['sha256'] and count==row['bytes'],'different checked metadata')
