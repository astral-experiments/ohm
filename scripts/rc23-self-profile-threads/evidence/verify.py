"""Check the committed raw records and optionally reopen allocated ELF sections from the full ZIP."""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import re
import struct
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from fixture import values

raw = zipfile.ZipFile(HERE/"original-records.zip")
read = raw.read
def doc(name):
    return json.loads(read(name))
def digest(data):
    return hashlib.sha256(data).hexdigest()
def allocated_file_sections(data):
    assert data[:6] == b"\x7fELF\x02\x01"
    off = struct.unpack_from("<Q", data, 40)[0]
    stride, count, index = struct.unpack_from("<HHH", data, 58)
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, off+j*stride) for j in range(count)]
    names = headers[index]
    strings = data[names[4]:names[4]+names[5]]
    return {strings[h[0]:].split(b"\0",1)[0].decode():digest(data[h[4]:h[4]+h[5]])
            for h in headers if h[2]&2 and h[1]!=8}

reg = json.loads((HERE.parent/"registration.json").read_bytes())
result = json.loads((HERE/"reopened.json").read_bytes())
for n, v in zip(["fixture.rs","client.rs","expected.txt"],values(),strict=True):
    assert read(n) == v.encode()
assert result["source_sha256"]==digest(read("fixture.rs"))
assert result["readbacks"]==39 and all(doc("completed.json")[key] for key in
    ["controls_ok","physical","all_successful_native_oracles","successful_profiles_recorded"])
for role, (rev, exe, lib) in reg["roles"].items():
    sdk = doc(role+"-sdk.json")
    assert (sdk["source"],sdk["rustc_sha256"],sdk["driver_sha256"])==(rev,exe,lib)
    assert re.findall(r"Build ID: (\w+)",read(role+"-elf-notes.txt").decode())==sdk["build_ids"]
counts=Counter()
loaded=defaultdict(lambda:defaultdict(set))
full=None
if len(sys.argv)==2:
    p=Path(sys.argv[1])
    with p.open("rb")as f:assert hashlib.file_digest(f,"sha256").hexdigest()==result["archive"]
    full=zipfile.ZipFile(p)
for label, code, kind, _ in result["profiles"]:
    role, mode, threads, counter, _attempt = label.split("-") if "-wall-time-" not in label else label.replace("-wall-time-","-wall_time-").split("-")
    prefix="runs/"+label+"/"
    s=doc(prefix+"result.json"); inv=doc(prefix+"invocation.json")
    assert s["code"]==code and s["executable_matched"] and s["mapped_driver"]
    assert ("-Zthreads="+threads[1:]) in inv["argv"]
    assert inv["rustc_bootstrap"]==("counter_fixture" if role=="stock" else None)
    if code:
        body=read(prefix+"stderr").decode()
        assert kind=="same-opt-interval" and s["first_panic"].startswith("thread 'opt ")
        assert "raw_event.rs:55:9" in s["first_panic"] and "assertion failed: start <= end" in body and "TimingGuard" in body
        assert ("rustc_codegen_llvm::back::write::"+("codegen" if role=="stock" else "optimize")) in body
    elif mode=="build":
        assert s["native"]["objects"]==32 and s["native"]["ok"] and read(prefix+"native.stdout")==read("expected.txt")
        if full is not None:
            h=s["native"]["elf_sha256"];elf=full.read("objects/"+h)
            assert digest(elf)==h
            for n,v in allocated_file_sections(elf).items():loaded[role][n].add(v)
    counts[role,mode,counter,threads,kind]+=1
if full is not None:
    for role,ss in loaded.items():
        assert len(ss)==27 and {k for k,v in ss.items() if len(v)!=1}=={".note.gnu.build-id"}
for k,v in sorted(counts.items()):print(*k,v)
