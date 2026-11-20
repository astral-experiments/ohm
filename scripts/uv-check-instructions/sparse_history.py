"""Exercise slot reclamation in a checked graph as items disappear and return."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

rustc = Path(sys.argv[1]).resolve()
work = Path(sys.argv[2]).resolve()
sizes = [(0,160), (64,160), (128,160), (192,160), (224,160),
         (256,160), (0,160), (80,160), (80,8), (96,8),
         (0,160), (40,160), (80,160), (120,160), (160,160), (0,160)]

def source(start, count):
    items = ["pub trait Item { fn get(&self) -> u32; }"]
    for i in range(start, start+count):
        items.extend([f"pub struct Row{i};",
                      f"impl Item for Row{i} {{ fn get(&self)->u32 {{ {i} }} }}",
                      f"pub const C{i}: u32 = {i};"])
    return "\n".join(items)

def graph():
    path = max((work / "warm").rglob("*dep-graph.bin"), key=lambda f:f.stat().st_mtime_ns)
    data = path.read_bytes()
    end = b"rust-end-file"
    assert data.endswith(end)
    start, roots, magic, slots, live, edges = struct.unpack_from("<QQ8sQQQ", data, -48 - len(end))
    assert magic == b"OHMIDX01", (path,magic)
    offsets = struct.unpack_from("<" + "Q"*slots, data, start)
    records = sorted((offset,index) for index,offset in enumerate(offsets) if offset)
    assert len(records) == live
    rows = [None]*slots
    for i, (offset, index) in enumerate(records):
        assert index == struct.unpack_from("<I", data, offset+2)[0]
        limit = records[i+1][0] if i+1 < live else offset+38
        rows[index] = data[offset:limit]
    return dict(slots=slots, live=live, edges=edges), rows

def compile_crate(threads, i, warm):
    cache = "warm" if warm else "fresh"
    state = "loaded" if warm and i else "not-loaded"
    flags = [f"-Zthreads={threads}", f"-Cincremental={cache}", f"-Zassert-incr-state={state}",
             "-Zohm-shared-stages", "-Zpublic-api-hash", "-Zincremental-verify-ich"]
    result = subprocess.run(
        [rustc, "--crate-type=lib", "--emit=metadata", "--edition=2024", "-Cmetadata=fixed",
         *flags, "subject.rs"], cwd=work, capture_output=True,
        env=dict(os.environ, CARGO_PKG_NAME="subject", CARGO_PKG_VERSION="1.0.0", RUSTC_BOOTSTRAP="1"))
    assert result.returncode == 0, result.stderr.decode()
    if not warm:
        shutil.rmtree(work / "fresh")
    return hashlib.sha256((work/"libsubject.rmeta").read_bytes()).hexdigest(), result.stderr.decode()

def exercise(threads):
    work.mkdir()
    previous=[]
    for i,(start,count) in enumerate(sizes):
        (work/"subject.rs").write_text(source(start,count))
        warm = compile_crate(threads, i, True)
        fresh = compile_crate(threads, i, False)
        assert warm == fresh, (threads,i,warm,fresh)
        stats, rows = graph()
        previous_live = sum(x is not None for x in previous)
        filled = sum(x is None and y is not None for x,y in zip(previous, rows))
        kept = sum(x is not None and x == y for x,y in zip(previous[2:], rows[2:]))
        print(json.dumps(dict(threads=threads,edit=i,start=start,count=count,warm=warm,fresh=fresh,
            previous_slots=len(previous), previous_live=previous_live, filled_holes=filled,
            retained_rows=kept, **stats)), flush=True)
        previous=rows
    shutil.rmtree(work)

for threads in (1, 8):
    exercise(threads)
