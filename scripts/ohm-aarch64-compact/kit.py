"""Bind the source-specific release capsule to the prior authenticated compiler."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-registers"))
import subject
from subject import capsule, rt
from study import load, need, save, sha

BEFORE = "d3538b42a2dc56edb9bffbc9cc2373fb93c35054"
AFTER = "f2edebc7a23b809749fb0cc44dd6ac902ca448ff"
TREE = "c4205f70f7807a7309d0a56abc7d772cb18899c1"
OLD_IR = "a51424740c111a4cfdfc67b39bf498907eb396b4b1f0800c27c4fcafc9e6eb72"
OLD_CAP = "d4a58ad69b0b2427f0fa1c4f3a9945783d7f2a9e3a4de9525d97f69db4f2a79b"


def bind():
    rt.PARENT, rt.CHILD = BEFORE, AFTER
    subject.BASE, subject.TREATMENT = BEFORE, AFTER


def import_original(archive, native):
    need(sha(archive) == OLD_CAP and load(native / "sdk-custody.json")["sha256"] == OLD_CAP, "unregistered original SDK")
    old = rt.ROOT / "previous-SDK"
    verified = capsule.verify(archive, "C", old)
    base = load(native / "C-sdk.json")
    need(base["source"] == BEFORE and base["tree"] == "5b86b3516db45ace6bbbdd536bbff9face291fbd", "wrong source")
    need({p.relative_to(old).as_posix() for p in old.rglob("*") if p.is_file()} == set(base["files"]) | set(rt.TOOLS), "different original kit operands")
    store = rt.CAP / "objects"
    store.mkdir(parents=True)
    for name,(key,size,mode) in base["files"].items():
        p = old / name
        need(p.stat().st_size==size and p.stat().st_mode & 0o777==mode and sha(p)==key, "changed original source-built member")
        obj = store/key
        if not obj.exists(): shutil.copyfile(p,obj)
        need(sha(obj)==key,"mutated retained original")
    for name,key in rt.TOOLS.items(): need(sha(old/name)==key,"incorrect original tool")
    need([v[0] for n,v in base["files"].items() if n.startswith("lib/librustc_driver")] == [OLD_IR], "wrong original physical compiler")
    save(rt.LOG/"P-sdk.json", base)
    save(rt.LOG/"imported-original.json",{"source":BEFORE,"archive":OLD_CAP,"sdk_sha":sha(native/"C-sdk.json"),"physical":verified,"runtime_files":len(base["files"])+len(rt.TOOLS)})


if __name__=="__main__":
    if sys.argv[1]=="import":
        import_original(Path(sys.argv[2]),Path(sys.argv[3]))
    else:
        bind()
        subject.main()
