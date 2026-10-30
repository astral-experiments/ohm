"""Reuse the enrolled M compiler, then bind the newly built versioned marker candidate."""
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-compact"))
import kit
from kit import capsule, rt, subject
from study import load, need, save, sha
from transport import SOURCES

PARENT = kit.AFTER
CHILD = SOURCES["rust"]["source"]
OLD_DRIVER = "2a232a6c250f30b7c8214be0bbba21ef125f514da3dfd720291c377909d14545"
OLD_CAP = "7e591c1d2340f06a72c56893dde67bb52dab9a6ac9715efece486714af8f343f"

def bind():
    rt.PARENT, rt.CHILD = PARENT, CHILD
    subject.BASE, subject.TREATMENT = PARENT, CHILD

def import_parent():
    kit.bind()
    inbox = rt.ROOT / "inputs"
    archive, native = inbox / "sdk.tar.zst", inbox / "native"
    need(sha(archive) == load(native / "sdk-custody.json")["sha256"] == OLD_CAP, "parent archive mismatch")
    old = rt.ROOT / "previous-SDK"
    verified = capsule.verify(archive, "C", old)
    base = load(native / "C-sdk.json")
    need((base["source"], base["tree"]) == (PARENT, kit.TREE), "parent source mismatch")
    need({p.relative_to(old).as_posix() for p in old.rglob("*") if p.is_file()} == set(base["files"]) | set(rt.TOOLS), "wrong parent members")
    store = rt.CAP / "objects"
    store.mkdir(parents=True)
    for name, (key, size, mode) in base["files"].items():
        source = old / name
        need((source.stat().st_size, source.stat().st_mode & 0o777, sha(source)) == (size, mode, key), name)
        obj = store / key
        if not obj.exists():
            shutil.copyfile(source, obj)
        need(sha(obj) == key, name)
    need(all(sha(old / name) == key for name, key in rt.TOOLS.items()), "signed tools differ")
    need([row[0] for n, row in base["files"].items() if n.startswith("lib/librustc_driver")] == [OLD_DRIVER], "wrong original compiler")
    save(rt.LOG / "P-sdk.json", base)
    save(rt.LOG / "imported-original.json", {"source": PARENT, "archive": OLD_CAP, "parent_manifest": sha(native / "C-sdk.json"), "physical": verified})

if __name__ == "__main__":
    if sys.argv[1] == "import":
        import_parent()
    else:
        bind()
        subject.main()
