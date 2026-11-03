"""Materialize the #436 Cargo source from packaging-only, digest-bound Git packs."""
import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent

def digest(path):
    with path.open("rb") as source:
        h=hashlib.sha256()
        while block:=source.read(1024*1024):
            h.update(block)
        return h.hexdigest()

def materialize(prior_pack, dest):
    base=json.loads((HERE/"plan.json").read_bytes())
    candidate=json.loads((HERE/"reader/plan.json").read_bytes())
    prior=base["prior_qa_source"]
    assert candidate["source"]=="4a6de7858c60e579fc30e01f5b60ddcaa84c2e30"
    assert candidate["tree"]=="1a128e47d068ee91f33ba94e416ee0c0e014de5a"
    packs=[(prior_pack, prior["pack_sha256"]), (HERE/"signed-delta.pack",base["delta_sha256"])]
    bundles=[(HERE/"candidate-v3.bundle",base["bundle_sha256"]), (HERE/"reader/overlay.bundle",candidate["sha256"])]
    for p,wanted in packs+bundles:
        assert digest(p)==wanted,p
    dest.mkdir()
    def git(*argv):
        return subprocess.check_output(["git","-C",dest,*argv]).decode().strip()
    git("init","--quiet","--template=","--object-format=sha1")
    for pack,_ in packs:
        with pack.open("rb") as input:
            subprocess.run(["git","-C",dest,"index-pack","--stdin"],stdin=input,stdout=subprocess.DEVNULL,check=True)
    (dest/".git/shallow").write_text(prior["source_sha"]+"\n"+base["parent"]+"\n")
    git("update-ref","refs/heads/release-parent",base["parent"])
    git("switch","--detach",base["parent"])
    assert git("rev-parse","HEAD^{tree}")==git("write-tree")==base["signed_tree"]
    git("fetch",str(bundles[0][0]),"HEAD:refs/qa/dep-info-recheck")
    git("switch","--detach",base["candidate"])
    for n,expect in enumerate([base["candidate"],base["second_candidate"],base["first_candidate"],base["parent"]]):
        assert git("rev-parse","HEAD"+"^"*n)==expect
    assert git("write-tree")==base["tree"] and candidate["predecessor"]==base["candidate"]
    git("fetch",str(bundles[1][0]),"HEAD:refs/qa/input-reader")
    git("switch","--detach",candidate["source"])
    assert git("rev-parse","HEAD^")==candidate["parent"]
    assert git("merge-base","HEAD",candidate["predecessor"])==candidate["predecessor"]
    assert git("rev-parse","HEAD^{tree}")==git("write-tree")==candidate["tree"]
    git("fsck","--strict","--full","--no-progress")
    assert not git("status","--porcelain")
    tree=subprocess.check_output(["git","-C",dest,"ls-tree","-rz","HEAD"])
    assert tree.endswith(b"\0")
    whole=hashlib.sha256();modes={}
    for entry in tree[:-1].split(b"\0"):
        header,name=entry.split(b"\t",1);mode,kind,blob=header.split(b" ")
        assert kind==b"blob" and mode in (b"100644",b"100755",b"120000")
        relative=Path(os.fsdecode(name))
        assert not relative.is_absolute() and ".." not in relative.parts
        file=dest/relative
        if mode==b"120000":
            assert file.is_symlink()
            body=os.fsencode(os.readlink(file))
        else:
            st=file.lstat();assert stat.S_ISREG(st.st_mode) and bool(st.st_mode&0o100)==(mode==b"100755")
            body=file.read_bytes()
        assert hashlib.sha1(b"blob "+str(len(body)).encode()+b"\0"+body).hexdigest().encode()==blob
        whole.update(entry+b"\0"+hashlib.sha256(body).digest())
        modes[mode.decode()]=modes.get(mode.decode(),0)+1
    assert modes=={"100644":2991,"100755":7,"120000":121}
    return {"source":candidate["source"],"tree":candidate["tree"],"files":sum(modes.values()),"modes":modes,"contents_sha256":whole.hexdigest(),"ls_tree_sha256":hashlib.sha256(tree).hexdigest()}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--prior-pack",required=True,type=Path);p.add_argument("--dest",required=True,type=Path)
    a=p.parse_args();print(json.dumps(materialize(a.prior_pack.resolve(strict=True),a.dest.resolve()),sort_keys=True))
