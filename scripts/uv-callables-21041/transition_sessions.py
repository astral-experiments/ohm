"""Enroll the one genuinely new committed incremental session and keep every retained header and digest."""
from pathlib import Path
import hashlib,os,re,stat
NAMES=("dep-graph.bin","query-cache.bin")
def sha(p):
    with p.open("rb")as f:return hashlib.file_digest(f,"sha256").hexdigest()
def inventory(cache):
    if not cache.exists():return {"complete":{},"unfinished":[]}
    assert cache.is_dir() and not cache.is_symlink();done={};unfinished=[]
    for crate in sorted(cache.iterdir()):
        assert re.fullmatch(r"reader-[a-z0-9]+",crate.name) and crate.is_dir() and not crate.is_symlink(),crate
        for session in sorted(crate.iterdir()):
            if not session.is_dir():
                assert session.is_file() and not session.is_symlink() and session.name.endswith(".lock"),session
                continue
            assert not session.is_symlink() and re.fullmatch(r"s-[a-z0-9-]+",session.name),session
            key=crate.name+"/"+session.name
            if session.name.endswith("-working") or not all((session/n).is_file() for n in NAMES):
                unfinished.append(key);continue
            files={}
            for name in NAMES:
                p=session/name;a=p.lstat();assert stat.S_ISREG(a.st_mode)and not p.is_symlink()
                with p.open("rb")as f:
                    header=f.read(7);assert len(header)==7 and header[:4]==b"RSIC"and header[6]>0
                    version=f.read(header[6]);assert len(version)==header[6];rawhead=header+version
                h=sha(p);b=p.stat();assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)==(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns)
                files[name]={"dev":a.st_dev,"ino":a.st_ino,"size":a.st_size,"mtime_ns":a.st_mtime_ns,"sha256":h,
                             "epoch":int.from_bytes(header[4:6],"little"),"version":version.decode(),"raw_header_hex":rawhead.hex()}
            st=session.stat();done[key]={"dir_dev":st.st_dev,"dir_ino":st.st_ino,"files":files}
    return {"complete":done,"unfinished":unfinished}
def select(before,after,version):
    assert not after["unfinished"],"successful compiler left an unfinished cache"
    old,new=before["complete"],after["complete"];fresh=set(new)-set(old)
    assert len(fresh)==1,("expected exactly one newly committed reader session",sorted(fresh))
    key,=fresh
    for former in old.keys()&new.keys():
        assert old[former]==new[former],("retained session changed in place",former)
    val=new[key];assert set(val["files"])==set(NAMES)
    assert all(f["epoch"]==43309 and f["version"]==version for f in val["files"].values()),("unexpected active compiler header",key)
    assert len({f["raw_header_hex"]for f in val["files"].values()})==1
    return key
def check_switch(before,after,previous,active,shared_identity):
    old,new=before["complete"],after["complete"]
    assert previous in old and active in new and active not in old
    prior_base=previous.split("/")[0];base=active.split("/")[0]
    assert (base==prior_base)==shared_identity,("cache family identity",prior_base,base,shared_identity)
    if shared_identity:
        assert [p for p in old if p.split("/")[0]==base]==[previous],("more than one possible shared previous session",sorted(old))
    else:
        assert previous in new and old[previous]==new[previous]and all(p.split("/")[0]!=base for p in old),("missing unchanged foreign-version cache or ambiguous natural cold start",previous,base)
