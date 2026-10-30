"""Require exact standalone marker rules on the actual cross compiler and bundle controls."""
from pathlib import Path
import shutil
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/"ohm-aarch64-compact"))
from version_kit import PARENT, CHILD
from classifier import PRIOR, NEW
from kit import rt
from study import digest, save, sha

def main(role):
    source=HERE.parent/"ohm-aarch64-compact"/"gnu_aarch64.rs"
    check=rt.ROOT/"rust/tests/run-make/ohm-checked-dep-info/gnu_aarch64.rs"
    assert source.read_bytes()==check.read_bytes()
    work=rt.ROOT/("direct-version-"+role);work.mkdir()
    shutil.copyfile(source,work/source.name);(work/"payload.bin").write_bytes(b"\0"*4)
    dest=rt.LOG/("direct-version-"+role)
    hard=b"/dev/null/ohm-untracked-relink-inputs:"
    old=b"/dev/null/ohm-recheck-dependent-links:"
    new=b"/dev/null/ohm-recheck-dependent-links-v2:"
    rows={};allowed={"ordinary","general_only","vector_only","compact_input","compact_copy"}
    args=["rustc","+ohm",source.name,"--crate-type=rlib","--target",rt.TARGET,"-Zohm-check-relink-inputs","--emit=link,dep-info=-"]
    supported=new if role=="C" else old
    def visit(label,extra,want,status=0):
        result=rt.record([*args,*extra],dest/label,work,rt.environment(),status)
        got=[k for k in (old,new,hard) if k in result.stdout.splitlines()]
        assert got==[want],(label,got,want,result.stdout[:1100])
        rows[label]={"expected":want.decode(),"status":result.returncode,"depfile":digest(result.stdout),"diagnostic":digest(result.stderr)}
        return result
    for cfg in PRIOR+NEW:
        visit(cfg,["--cfg",cfg],supported if cfg in allowed else hard)
    visit("external",["--cfg","ordinary","-lstatic:-bundle=qa_unavailable_library"],supported)
    failure=visit("bundled",["--cfg","ordinary","-lstatic=qa_unavailable_library"],hard,1)
    assert b"qa_unavailable_library" in failure.stderr
    (work/"payload.bin").unlink()
    for cfg in ("file","escape","compact_file"):
        (work/"libgnu_aarch64.rlib").unlink(missing_ok=True)
        error=visit("missing-"+cfg,["--cfg",cfg],hard,1)
        assert b"payload.bin" in error.stderr and not (work/"libgnu_aarch64.rlib").exists()
    src={"P":PARENT,"C":CHILD}[role]
    save(dest/"complete.json",{"source":src,"driver":{f.name:sha(f) for f in (rt.SDK/"lib").glob("librustc_driver*.so")},"fixture":sha(source),"cases":rows})
if __name__=="__main__":main(sys.argv[1])
