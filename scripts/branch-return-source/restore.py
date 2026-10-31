"""Restore either exact native SDK from one base archive and one independently verified delta."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from registration import CARGO, ELF, HOST, SOURCE, WILD, WILD_SHA, need, sha


def valid(name):
    p=PurePosixPath(name)
    return bool(name) and str(p)==name and not p.is_absolute() and all(c not in ("..",".") for c in p.parts)


def extract(archive, dest, expected, overlay):
    read={}
    with subprocess.Popen(["zstd","-dcq",archive],stdout=subprocess.PIPE) as proc:
        with tarfile.open(fileobj=proc.stdout,mode="r|") as tar:
            for member in tar:
                n=member.name
                need(valid(n) and n in expected and n not in read and member.isreg() and not member.islnk(),"unknown SDK member")
                want=expected[n];need([member.size,member.mode]==want[1:],"SDK member geometry")
                path=dest/n;path.parent.mkdir(parents=True,exist_ok=True)
                if overlay:
                    need(path.is_file() and not path.is_symlink(),"bad candidate overlay")
                    path.unlink()
                h=hashlib.sha256()
                with tar.extractfile(member) as src,path.open("xb") as out:
                    while block:=src.read(1048576):out.write(block);h.update(block)
                path.chmod(member.mode);read[n]=[h.hexdigest(),path.stat().st_size,stat.S_IMODE(path.stat().st_mode)]
        need(not proc.stdout.read().strip(b"\0") and proc.wait()==0,"unread or damaged SDK trailer")
    need(read==expected,"missing or altered archived member")


def restore(transfer, dest, role, qa, run, attempt, digest):
    need(sha(transfer/"manifest.json")==digest,"foreign transfer manifest")
    m=json.loads((transfer/"manifest.json").read_bytes())
    reg=SOURCE()
    need((m["qa"],m["run"],m["attempt"],m["roles"])==(qa,str(run),str(attempt),{k:reg["roles"][k] for k in ("F","K")}),"wrong source enrollment")
    need(m["strict_cargo"]==CARGO and m["wild"]==WILD and m["host"]==HOST and m["qualified"] is True,"unqualified tools")
    need(set(m["files"])=={"F","K"} and set(m["files"]["F"])==set(m["files"]["K"]),"wrong SDK inventory")
    for files in m["files"].values():
        need(all(valid(p) and len(row)==3 for p,row in files.items()) and files["bin/cargo"][0]==ELF and files[WILD][0]==WILD_SHA and
             all(p in files for p in ("bin/rustc","bin/rustdoc",m["driver"])),"incomplete host identity")
    changes={n for n in m["files"]["F"] if m["files"]["F"][n]!=m["files"]["K"][n]}
    need(m["driver"] in changes and changes<={m["driver"],"bin/rustdoc"} and changes==set(m["delta"]),"unexpected role differences")
    need(set(m["products"])=={"F-sdk.tar.zst","K-delta.tar.zst"},"wrong transfer contents")
    for n,(h,size) in m["products"].items():
        p=transfer/n;need(p.is_file() and not p.is_symlink() and p.stat().st_size==size and sha(p)==h,"corrupt "+n)
    dest.mkdir()
    extract(transfer/"F-sdk.tar.zst",dest,m["files"]["F"],False)
    if role=="K":extract(transfer/"K-delta.tar.zst",dest,{n:m["files"]["K"][n] for n in changes},True)
    actual={str(p.relative_to(dest)):[sha(p),p.stat().st_size,stat.S_IMODE(p.stat().st_mode)]
            for p in dest.rglob("*") if p.is_file()}
    need(actual==m["files"][role] and not any(p.is_symlink() for p in dest.rglob("*")),"installed SDK differs")
    return dict(role=role,commit=m["roles"][role]["commit"],manifest=digest,driver=actual[m["driver"]],rustdoc=actual["bin/rustdoc"],cargo=actual["bin/cargo"],wild=actual[WILD],members=len(actual))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("transfer",type=Path);p.add_argument("destination",type=Path)
    p.add_argument("role",choices=["F","K"])
    for name in ("qa","run","attempt","manifest"):p.add_argument("--"+name,required=True)
    a=p.parse_args();print(json.dumps(restore(a.transfer,a.destination,a.role,a.qa,a.run,a.attempt,a.manifest),sort_keys=True))
