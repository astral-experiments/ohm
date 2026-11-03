"""Keep complete per-command native records; already signed SDK binaries stay in their original capsules."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

root=Path(os.environ["RUNNER_TEMP"])/"ruf009-v5-native"
out=root/"artifact";out.mkdir(exist_ok=True,parents=True)
m=root/"matrix"
files=[]
def add(path):
    if path.is_file() and not path.is_symlink():
        files.append(path)
    elif path.is_dir():
        files.extend(f for f in path.rglob("*") if f.is_file() and not f.is_symlink())
add(root/"source-receipts")
for path in (m/"dispatch",m/"complete.json"):
    add(path)
if m.is_dir():
    for cell in sorted(p for p in m.iterdir() if p.is_dir() and p.name!="dispatch"):
        for name in ("registration.json","complete.json","independent.json","out","proof"):
            add(cell/name)
        for p in cell.glob("*/evidence"):
            add(p)
        for p in cell.glob("*/src"):
            add(p)
files=sorted(set(files))
size=sum(p.stat().st_size for p in files)
assert size<2*2**30, size
entries=[str(p.relative_to(root)) for p in files]
z=out/"originals.tar.zst"
with z.open("wb") as dst:
    subprocess.run(["tar","--zstd","-C",root,"--null","-T","-","-cf","-"],input=b"".join(os.fsencode(p)+b"\x00" for p in entries),stdout=dst,check=True)
with z.open("rb") as src:digest=hashlib.file_digest(src,"sha256").hexdigest()
(out/"manifest.json").write_text(json.dumps({"files":entries,"raw_bytes":size,"archive_bytes":z.stat().st_size,"sha256":digest,"completed":(m/"complete.json").is_file()},sort_keys=True,indent=1)+"\n")
