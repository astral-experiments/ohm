"""Keep the signed, prior, and merged native Cargo inodes immutable across clocked installations."""
from pathlib import Path
import os,shutil
from study import load,need,save,sha
def stamp(p):
    s=p.stat();return [s.st_dev,s.st_ino,s.st_ctime_ns,s.st_mtime_ns,s.st_size,sha(p)]
def freeze(root):
    from versioned_select import CARGOS,choose
    top=root/"release-cargo-bins";top.mkdir()
    choose(root,"signed")
    active=root/"native/bin"
    for name,(rev,subject) in CARGOS.items():
        if name=="signed":continue
        dest=top/name
        shutil.copytree(active,dest,symlinks=True,copy_function=os.link,ignore=lambda p,n:["cargo"] if Path(p)==active else [])
        os.link(root/subject,dest/"cargo")
    rows={r:stamp(root/v[1]) for r,v in CARGOS.items()}
    control=top/"frozen.json";save(control,{"subjects":rows,"rustc":stamp(active/"rustc")})
    selected(root,"signed",CARGOS)
    return control
def selected(root,name,subjects):
    pool=root/"release-cargo-bins";proof=load(pool/"frozen.json")
    active=root/"native/bin"
    before,=[n for n,(_,s) in subjects.items() if (active/"cargo").samefile(root/s)]
    if before!=name:
        old=pool/before;new=pool/name
        need(not old.exists() and new.is_dir(),"invalid parked native Cargo state")
        active.rename(old)
        try:new.rename(active)
        except OSError:old.rename(active);raise
    need((active/"cargo").samefile(root/subjects[name][1]),"wrong physical Cargo")
    need(proof["subjects"]=={n:stamp(root/s) for n,(_,s) in subjects.items()} and stamp(active/"rustc")==proof["rustc"],"native Cargo/rustc time or identity changed")

if __name__=="__main__":
    import sys
    from versioned_select import choose
    root=Path(sys.argv[1]).resolve()
    assert load(root/"receipts/versioned/terminal.json")["passed"] and not load(root/"receipts/versioned/legacy/terminal.json")["signed_integrated_differences"]
    freeze(root)
    choose(root,"aware")
