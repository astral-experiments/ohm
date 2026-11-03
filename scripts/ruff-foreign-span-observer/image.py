"""Find a loaded native image without mistaking rustc's separate metadata mmap for it."""
from pathlib import Path
import hashlib
def native_bases(text,name,expected_sha,text_offsets):
    rows=[]
    for line in text.splitlines():
        s=line.split()
        if len(s)<=5 or Path(s[5]).name!=name:continue
        low,high=(int(v,16)for v in s[0].split('-'))
        rows.append((low,high,s[1],int(s[2],16),Path(s[5])))
    found=[]
    for base,_,_,offset,path in rows:
        if offset or not all(any(lo<=base+at<hi and 'x'in rights and file==path for lo,hi,rights,_,file in rows)for at in text_offsets):continue
        with path.open('rb') as file:
            assert hashlib.file_digest(file,'sha256').hexdigest()==expected_sha
        found.append(base)
    return sorted(set(found))
