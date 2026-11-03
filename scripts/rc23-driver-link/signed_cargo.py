"""One released asset supplies the identical Cargo executable to both native jobs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE=Path(__file__).resolve().parent
AUTH=json.loads((HERE/"signed.json").read_bytes())
REPO="astral-experiments/ohm"
ID=432227571
COORD="9c2397d36f033900a0864484714d526788d1dc77"
def sha(p):
    with p.open("rb") as f: return hashlib.file_digest(f,"sha256").hexdigest()

def verify_release(row):
    assert row["id"]==ID and row["target_commitish"]==COORD and row["immutable"] and not row["draft"] and not row["prerelease"] and row["tag_name"]==AUTH["tag"]
    asset,=[a for a in row["assets"] if a["id"]==AUTH["archive"]["id"]]
    assert {k:asset[k] for k in AUTH["archive"]}==AUTH["archive"]
    return asset

def install(release, archive, dest):
    asset=verify_release(release)
    assert archive.stat().st_size==asset["size"] and sha(archive)==asset["digest"].removeprefix("sha256:")
    cargo=dest/"cargo"
    count=0
    member="rust-1.99.0-dev-x86_64-unknown-linux-gnu/cargo/bin/cargo"
    sys.path.insert(0,str(HERE))
    import elf
    driver_member=member.rsplit("/cargo/",1)[0]+"/rustc/"+AUTH["driver"]["path"]
    driver=dest/"signed-original-driver.so"
    with tarfile.open(archive,"r|gz") as tar:
        for item in tar:
            if item.name==driver_member:
                assert item.isfile() and not driver.exists() and item.size==AUTH["driver"]["bytes"]
                with tar.extractfile(item) as src,driver.open("xb") as out:shutil.copyfileobj(src,out,1<<20)
            if item.name==member:
                assert item.isfile() and item.size==AUTH["cargo"]["bytes"] and item.mode&0o111
                with tar.extractfile(item) as src,cargo.open("xb") as out: shutil.copyfileobj(src,out,1<<20)
                count+=1
    assert sha(driver)==AUTH["driver"]["sha256"]
    census=elf.scan(driver,dest/"signed-driver.json.gz")
    assert census["sha256"]==AUTH["driver"]["sha256"]
    (dest/"signed-driver.json").write_text(json.dumps(census,sort_keys=True,indent=2)+"\n")
    driver.unlink()
    assert count==1 and sha(cargo)==AUTH["cargo"]["sha256"];cargo.chmod(0o755)
    banner=subprocess.check_output([cargo,"-Vv"],text=True)
    assert "7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed" in banner
    with (dest/"signed-cargo.json").open("x") as out:
        json.dump({"release":ID,"coordinator":COORD,"archive":AUTH["archive"],"member":member,"cargo":AUTH["cargo"],"banner":banner},out,indent=2,sort_keys=True);out.write("\n")
if __name__=="__main__":
    dest=Path(sys.argv[1]);dest.mkdir()
    if len(sys.argv)==4:
        install(json.loads(Path(sys.argv[2]).read_bytes()),Path(sys.argv[3]),dest)
    else:
        route=f"repos/{REPO}/releases"
        row=json.loads(subprocess.check_output(["gh","api",f"{route}/{ID}"]))
        asset=verify_release(row)
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/asset["name"]
            with path.open("xb") as out: subprocess.run(["gh","api","-H","Accept: application/octet-stream",f"{route}/assets/{asset['id']}"],stdout=out,check=True)
            install(row,path,dest)
