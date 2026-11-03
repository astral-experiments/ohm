"""Authenticate the immutable release, calibrate the reference meters, and collect one independent eight-pair panel."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common21577 import *
import birth, host as prior

def sealed(w,head):
    manifest=(HERE/"SHA256SUMS").read_text().splitlines()
    seen=set()
    for line in manifest:
        digest,n=line.split("  ",1);assert n==Path(n).name and n not in seen and sha(HERE/n)==digest;seen.add(n)
    assert seen=={p.name for p in HERE.iterdir() if p.is_file()}-{"SHA256SUMS"}
    lock=read(HERE/"donor.json")
    lines=subprocess.check_output(["git","-C",w/"coordinator","ls-tree","-r",head,"--",*lock["dirs"]],text=True).splitlines()
    got={z.split("\t",1)[1]:z.split()[2]for z in lines};assert got==lock["files"]
def main(mode):
    w,tmp,head=birth.identity();out=w/"trait-results";sealed(w,head)
    if mode=="start":
        assert not out.exists() and shutil.disk_usage(tmp).free>=32<<30
        out.mkdir();birth.start(out,tmp,head);prior.release(out,"before");return
    birth.current(out);prior.current=birth.current
    m,scoped=prior.proper(w,tmp)
    if mode=="calibrate":
        m.pmu(w,tmp)[0].calibrate();mask=prior.pin(out);scoped.calibrate();blocking=prior.clock(out,"pre",mask)
        save(out/"boot-attestation.json",{**birth.current(out),"affinity":mask,"inherited":sha(out/"calibration.json"),"threads":sha(out/"per-rustc-calibration/calibration.json"),"blocking":blocking,"tools":prior.tools(out,tmp)})
        return
    mask=prior.pin(out);assert prior.tools(out,tmp)==read(out/"boot-attestation.json")["tools"]
    if mode=="assets":
        from panel21577 import prepare_sdk
        prepare_sdk(out,tmp);return
    if mode=="study":
        from panel21577 import run
        run(out,w/"uv-source",tmp/"driver-binding-sdks",os.environ["SERIES"]);return
    assert mode=="finish"
    prior.clock(out,"post",mask);prior.release(out,"after")
    assert read(out/"panel/complete.json")["protocol"]==sha(HERE/"protocol.json")
    assert not any(p.is_symlink() for p in out.rglob("*"))
    files={str(p.relative_to(out)):blob(p) for p in sorted(out.rglob("*")) if p.is_file()}
    assert sum(v[0]for v in files.values())<850<<20
    save(out/"original-index.json",files)
if __name__=="__main__":main(sys.argv[1])
