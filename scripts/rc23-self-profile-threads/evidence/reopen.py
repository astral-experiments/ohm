"""Independently read the original GitHub artifact, compiler receipts, ELF files and event pages."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import struct
import sys
import zipfile

ROOT = Path(sys.argv[4]) if len(sys.argv)>4 else Path.cwd()
archive, digest = Path(sys.argv[1]), sys.argv[2]
assert hashlib.file_digest(archive.open("rb"), "sha256").hexdigest() == digest
original = zipfile.ZipFile(archive)
names = original.namelist()
assert len(names) == len(set(names)) and all(not n.startswith("/") and ".." not in Path(n).parts for n in names)
def read(n):
    return original.read(n)
def doc(n):
    return json.loads(read(n))
def sha(b):
    return hashlib.sha256(b).hexdigest()

def streams(data):
    assert data[:8] == b"MMPD\x09\0\0\0"
    tags = {}
    ix = 8
    while ix < len(data):
        tag, size = struct.unpack_from("<BI", data, ix)
        ix += 5
        assert tag in (0,1,2) and size>0 and ix+size<=len(data)
        if tag not in tags:
            tags[tag] = {"head":data[ix:ix+4].decode("ascii"),"bytes":0}
        tags[tag]["bytes"] += size
        ix += size
    assert ix == len(data)
    return tags

roles = ["stock", "signed23", "pr329"]
sdk = {r:doc(r+"-sdk.json") for r in roles}
pin = json.loads((Path(sys.argv[3])/"registration.json").read_bytes())
for role, item in sdk.items():
    assert [item["source"],item["rustc_sha256"],item["driver_sha256"]]==pin["roles"][role]
    notes=read(role+"-elf-notes.txt")
    assert [v.decode() for v in re.findall(rb"Build ID: (\w+)",notes)]==item["build_ids"]
assert not sdk["stock"]["build_ids"] and len(sdk["signed23"]["build_ids"])==1 and len(sdk["pr329"]["build_ids"])==1
fixture_source=read("fixture.rs"); expected=read("expected.txt")
assert len(re.findall(rb"pub mod m\d+ \{",fixture_source))==48 and fixture_source.count(b"#[inline(never)]")==240
assert len(expected.strip().splitlines())==2
summaries=[]; verdicts=Counter(); native_sets={r:{} for r in roles}; failures=[]
for role in roles:
    for mode, ts in (("check",(1,)), ("build",(8,1))):
        for threads in ts:
            for counter in ("ordinary","wall-time","instructions:u"):
                count=3 if mode=="build" and counter=="instructions:u" else 1
                for attempt in range(count):
                    label=f"{role}-{mode}-t{threads}-{counter.replace(':','_')}-{attempt}"
                    prefix="runs/"+label+"/"
                    inv = doc(prefix+"invocation.json")
                    args=inv["argv"]
                    assert inv["rustc_bootstrap"] == ("counter_fixture" if role=="stock" else None)
                    assert args[0]==str(Path(sdk[role]["driver"]).parents[1]/"bin/rustc")
                    assert "-Copt-level=1" in args and "-Ccodegen-units=32" in args and "-Zthreads="+str(threads) in args
                    assert ("--emit=metadata" if mode=="check" else "--emit=dep-info,metadata,link") in args
                    assert ("-Zself-profile-counter="+counter in args) == (counter!="ordinary")
                    result=doc(prefix+"result.json");stderr=read(prefix+"stderr").decode(errors="replace")
                    assert result["executable_matched"] and result["mapped_driver"] and all(line.endswith(sdk[role]["driver"]) for line in result["mapped_driver"])
                    panic=next((l for l in stderr.splitlines() if "panicked at" in l),None)
                    assert panic==result["first_panic"]
                    raw_match=bool(panic and "measureme-" in panic and "/src/raw_event.rs:" in panic and "assertion failed: start <= end" in stderr)
                    first=stderr.split("stack backtrace:",1)[-1].split("note:",1)[0]
                    same_frame=raw_match and panic.startswith("thread 'opt ") and "TimingGuard" in first and ("rustc_codegen_llvm::back::write" in first or "rustc_codegen_ssa::back::write" in first)
                    assert bool(same_frame)==bool(result["matched_opt_interval"])
                    profile=[]
                    for n,(size,h,magic) in result["profile_files"].items():
                        data=read(prefix+n);assert len(data)==size and sha(data)==h and data[:8].hex()==magic
                        tag_map=streams(data)
                        if result["code"]==0:assert set(tag_map)=={0,1,2}
                        profile.append(tag_map)
                    rc=result["code"]
                    if counter!="ordinary" and not rc:assert len(profile)==1
                    if not rc and mode=="build":
                        native=result["native"]
                        assert native["ok"] and result["link_exit"]==0 and read(prefix+"native.stdout")==expected and not read(prefix+"native.stderr")
                        assert native["objects"]==sum(n.endswith(b".o") for n in read(prefix+"archive-members.txt").splitlines()) and native["objects"]>=8
                        for k,header in (("archive_sha256",b"!<arch>\n"),("elf_sha256",b"\x7fELF")):
                            h=native[k]; obj_key=(h,k)
                            if obj_key not in native_sets[role]:
                                data=read("objects/"+h);assert data.startswith(header) and sha(data)==h;native_sets[role][obj_key]=1
                    typ="same-opt-interval" if same_frame else "other-inverted-interval" if raw_match else "other-failure" if rc else "success"
                    verdicts[(role,mode,counter,threads,typ)]+=1
                    if rc:failures.append([label,rc,panic,[(x.strip()) for x in first.splitlines() if re.match(r"\s*\d+:",x)][:10],sha(stderr.encode())])
                    summaries.append([label,rc,typ,profile])
assert len(summaries)==39 and len([n for n in names if n.endswith("/result.json")])==39
comp=doc("completed.json");assert comp["count"]==39 and comp["physical"] and comp["all_successful_native_oracles"]
report={"archive":digest,"bytes":archive.stat().st_size,"roles":sdk,"boot":doc("machine.json"),"source_sha256":sha(fixture_source),"expected":expected.decode(),"readbacks":len(summaries),"ordinary_and_wall_result":comp["controls_ok"],"profiles":summaries,"outcomes":[[*k,v] for k,v in sorted(verdicts.items())],"failures":failures,"counts_source_bound":False}
path=ROOT/"reopened.json";path.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
print(path,sha(path.read_bytes()))
for k,v in sorted(verdicts.items()): print(*k,v)
