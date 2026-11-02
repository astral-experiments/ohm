"""Install and authenticate the exact landed source and the ordinary public offline Cargo registry."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
CASE = json.loads((HERE / "source-case.json").read_bytes())
CRLF = json.loads((HERE / "source-attributes.json").read_bytes())
INDEX = "index.crates.io-1949cf8c6b5b557f"
V = Path("/tmp/ohm-over18-named-test")
S = V / "source"
E = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "HOME": str(V/"home"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM":"1", "GIT_NO_LAZY_FETCH":"1", "GIT_ALLOW_PROTOCOL":"file"}
def sha(b):return hashlib.sha256(b).hexdigest()
def filehash(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def save(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n")
def git(path,*args):return subprocess.check_output(["/usr/bin/git","-C",path,*args],env=E,stderr=subprocess.PIPE)
def auth_source(src,state):
    commit=CASE[state];tree=CASE[state+"_tree"]
    assert git(src,"rev-parse","HEAD","HEAD^{tree}").decode().split()==[CASE["A"],CASE["A_tree"]]
    assert git(src,"rev-parse","refs/tags/"+CASE["tag"]).decode().strip()==CASE["tag_object"]
    assert git(src,"rev-parse",CASE["B"]+"^",commit+"^{tree}").decode().split()==[CASE["A"],tree]
    tag=git(src,"describe","--long","--abbrev=7","--tags","--match",CASE["tag"]).decode().strip()
    assert tag=="0.12.2-16-g5d4a62d"
    def entries(ref):
        rows={}
        for item in git(src,"ls-tree","-rz",ref).split(b"\0")[:-1]:
            head,name=item.split(b"\t",1);mode,kind,oid=head.decode().split();assert kind=="blob"
            rows[name.decode()]=(mode,oid)
        return rows
    A=entries(CASE["A"]);wanted=A if state=="A" else entries(CASE["B"])
    index={}
    for item in git(src,"ls-files","-s","-z").split(b"\0")[:-1]:
        head,name=item.split(b"\t",1);mode,oid,stage=head.decode().split();assert stage=="0";index[name.decode()]=(mode,oid)
    assert index==A and set(A)==set(wanted) and len(A)==CASE["tracked"]==1608
    for name,(mode,oid) in wanted.items():
        p=src/name
        if mode=="120000":data=os.fsencode(os.readlink(p))
        else:
            assert p.is_file() and not p.is_symlink() and bool(p.stat().st_mode&0o111)==(mode=="100755")
            data=p.read_bytes()
        if name in CRLF:
            assert sha(data)==CRLF[name]["raw_sha256"]
            data=data.replace(b"\r\n",b"\n")
            assert sha(data)==CRLF[name]["canonical_sha256"]
        assert hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==oid,(name,mode)
    changed={name:wanted[name][1] for name in wanted if wanted[name]!=A[name]}
    assert changed==({}if state=="A" else CASE["changed_files"])
    assert filehash(src/"Cargo.lock")==CASE["Cargo_lock_sha256"] and not git(src,"ls-files","--others","--exclude-standard")
    return dict(source=commit,head=CASE["A"],tree=tree,index=sha(git(src,"ls-files","-s","-z")),tag=tag,tracked=len(wanted),changed=changed,lock=filehash(src/"Cargo.lock"))
def install(donor,src=S):
    assert not src.exists() and donor.is_dir()
    src.mkdir()
    git(src,"init","--quiet");git(src,"config","core.autocrlf","false");git(src,"config","core.hooksPath","/dev/null")
    git(src,"fetch","--quiet","--no-tags","--depth=40","file://"+str(donor.resolve()),CASE["B"])
    git(src,"fetch","--quiet","--no-tags","--depth=40","file://"+str(donor.resolve()),"+refs/tags/"+CASE["tag"]+":refs/tags/"+CASE["tag"])
    git(src,"checkout","--quiet","-B","feature-A",CASE["A"])
    return auth_source(src,"A")
def edit(src=S):
    assert auth_source(src,"A")
    for name,oid in CASE["changed_files"].items():
        path=src/name;before=path.stat()
        path.write_bytes(git(src,"cat-file","blob",oid))
        after=path.stat();assert (before.st_dev,before.st_ino)==(after.st_dev,after.st_ino) and after.st_mtime_ns>before.st_mtime_ns
    return auth_source(src,"B")
def registry(bank):
    archive=HERE/"public-sparse-index.tar.xz";assert filehash(archive)==CASE["sparse_tar_sha256"]
    idx=bank/"index"/INDEX;idx.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as t:
        rows=t.getmembers();assert len(rows)==len(CASE["sparse_entries"])==len({r.name for r in rows})
        for r in rows:
            assert r.isfile() and r.name in CASE["sparse_entries"] and not r.name.startswith("/") and ".." not in Path(r.name).parts
            fn=idx/".cache"/r.name;fn.parent.mkdir(parents=True,exist_ok=True)
            raw=t.extractfile(r).read();assert sha(raw)==CASE["sparse_entries"][r.name]
            if fn.exists():assert fn.read_bytes()==raw
            else:fn.write_bytes(raw)
    save(idx/"config.json",{"dl":"https://static.crates.io/crates", "api":"https://crates.io"})
    cache=bank/"cache"/INDEX;cache.mkdir(parents=True,exist_ok=True)
    def hydrate(package):
        name,version,checksum=package
        assert re.fullmatch(r"[a-zA-Z0-9_-]+",name) and re.fullmatch(r"[a-zA-Z0-9.+_-]+",version)
        filename=f"{name}-{version}.crate";out=cache/filename
        if not out.exists():
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(f"https://static.crates.io/crates/{name}/{filename}",timeout=40) as resp:raw=resp.read(64<<20)
                    assert sha(raw)==checksum
                    out.write_bytes(raw);break
                except OSError:
                    if attempt==2:raise
                    time.sleep(1+attempt)
        assert filehash(out)==checksum
        return out.stat().st_size
    with ThreadPoolExecutor(max_workers=8) as ex:sizes=list(ex.map(hydrate,CASE["packages"]))
    assert len(sizes)==658 and sum(sizes)==CASE["registry_archive_bytes"]
    return dict(count=len(sizes),bytes=sum(sizes),archives_manifest=sha(json.dumps(CASE["packages"],sort_keys=True).encode()),index=CASE["sparse_tar_sha256"],canonical_registry=INDEX)


def configured_registry(bank):
    """Authenticate an existing trusted cache without changing Cargo's configured source."""
    caches=list((bank/"cache").iterdir());indexes=list((bank/"index").iterdir())
    assert len(caches)==len(indexes)==1 and caches[0].name==indexes[0].name
    cache,idx=caches[0],indexes[0]
    for filename,digest in CASE["sparse_entries"].items():
        assert filehash(idx/".cache"/filename)==digest
    total=0
    for name,version,digest in CASE["packages"]:
        archive=cache/f"{name}-{version}.crate";assert filehash(archive)==digest
        total+=archive.stat().st_size
    assert total==CASE["registry_archive_bytes"]
    return dict(count=len(CASE["packages"]),bytes=total,index=CASE["sparse_tar_sha256"],original_configuration_unchanged=True)

