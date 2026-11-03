"""Exercise the source-owned replay, linker fallback and preemption controls on the installed SDK."""
from pathlib import Path
import gzip
import json
import re
import shutil
import subprocess
import sys
import gate as g

FIXTURE="tests/run-make/ohm-driver-preemption-link-modes/driver.rs"
CASES={"untreated":"21 22","normal":"11 22","emit":"21 22","replay":"21 22","bfd":"21 22","bfd-user":"11 12",
       "fallback":"21 22","fallback-user":"11 12","genuine-old-cc":"21 22","genuine-old-cc-user":"11 12"}

def check(work,installed,srctree,tmp,qa,env):
    old=g.read(qa/"old-cc-inputs.json");cc=Path(old["gcc"])
    assert cc==work/"driver-oldcc/root/usr/bin/gcc-4.8" and g.sha(cc)==old["gcc_sha256"]
    source=srctree/FIXTURE;src=g.read(qa/"source.json")
    assert src["role"]=="T" and g.text(srctree,"rev-parse","HEAD")==src["commit"]
    assert g.text(srctree,"hash-object",str(source))==g.text(srctree,"rev-parse","HEAD:"+FIXTURE)
    out=tmp/"installed-link-modes";dest=qa/"link-modes";dest.mkdir()
    try:
        subprocess.run([sys.executable,"-ISB",g.HERE/"validate_modes.py",installed,source,out,"--old-cc",cc],env=env,check=True)
    finally:
        if out.is_dir():
            for name in ("accepted.json","progress.json"):
                if (out/name).is_file():shutil.copyfile(out/name,dest/name)
            for name in CASES:
                local=out/name
                if not local.is_dir():continue
                keep=dest/name;keep.mkdir()
                for file in ("stderr","exec.trace","linkers.json"):
                    if (local/file).is_file():
                        b=(local/file).read_bytes();assert len(b)<16<<20
                        (keep/(file+".gz")).write_bytes(gzip.compress(b,mtime=0))
    receipt=g.read(dest/"accepted.json")
    assert receipt["mode"]=="repaired" and receipt["rustc_sha256"]==g.sha(installed/"bin/rustc")
    assert receipt["fixture_sha256"]==g.sha(source) and "commit-hash: "+src["commit"] in receipt["banner"]
    assert set(receipt["cases"])==set(CASES)
    for name,expected in CASES.items():
        row=receipt["cases"][name];assert row["exit"]==0 and row["internal_preload"]==expected
        for k,file in {"kernel":"exec.trace","stderr":"stderr","linkers":"linkers.json"}.items():
            raw=gzip.decompress((dest/name/(file+".gz")).read_bytes())
            assert g.hashlib.sha256(raw).hexdigest()==row[k]
        links=json.loads(gzip.decompress((dest/name/"linkers.json.gz").read_bytes()))
        cc_cmd=[a for e,a in links if Path(e).name in {"old-cc","collect2"} or re.fullmatch(r"(?:[\w.+-]+-)?(?:gcc|clang|cc)(?:-[0-9.]+)?",Path(e).name)]
        assert cc_cmd and not any("-Bsymbolic-non-weak-functions" in v or "--export-dynamic-symbol-list=" in v for a in cc_cmd for v in a)
        if name.startswith("genuine-old-cc"):assert any(Path(e)==cc for e,_ in links)
    media={}
    for file in sorted((out/"emit").rglob("*")):
        if file.is_file() and (file.name=="driver.rlink" or (out/"emit/objects") in file.parents):
            data=file.read_bytes();assert len(data)<8<<20
            key=g.hashlib.sha256(data).hexdigest();(dest/(key+".gz")).write_bytes(gzip.compress(data,mtime=0))
            media[str(file.relative_to(out/"emit"))]={"bytes":len(data),"sha256":key}
    assert "driver.rlink" in media
    return {"role":src["role"],"source":src["commit"],"fixture_path":FIXTURE,"fixture_sha256":g.sha(source),
            "old_cc_inputs_sha256":g.sha(qa/"old-cc-inputs.json"),"old_cc_sha256":g.sha(cc),"reader_sha256":g.sha(g.HERE/"validate_modes.py"),
            "actual_native_sha256":g.sha(dest/"accepted.json"),"ordinary_opted_in":receipt["cases"]["normal"]["internal_preload"],
            "replayed":receipt["cases"]["replay"]["internal_preload"],"cases":CASES,"rlink_and_objects":media}
