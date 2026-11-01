"""Exercise natural compiler identities and the shared rustc-perf identity, in both directions."""
from pathlib import Path
import hashlib,json,os,re,subprocess,sys
H=Path(__file__).resolve().parent
def save(p,o):
 with p.open("x") as f:json.dump(o,f,sort_keys=True,indent=2);f.write("\n")
def header_rows(cache):
 rows=[]
 for name in ("dep-graph.bin","query-cache.bin"):
  for p in cache.rglob(name):
   with p.open("rb") as f:
    h=f.read(7);assert len(h)==7 and h[:4]==b"RSIC";version=f.read(h[6]).decode();assert version
   rows.append((str(p.relative_to(cache)),int.from_bytes(h[4:6],"little"),version))
 return sorted(rows)
def run(stock,traits,out,tmp):
 src=H/"fixture/right.rs";assert hashlib.sha1(b"blob "+str(src.stat().st_size).encode()+b"\0"+src.read_bytes()).hexdigest()=="0f2bb7d7f6da8a0d7221796bfd8ad0bd4a8c7a2c"
 sdks={"stock_ctfe318":(stock,43310),"fa7a_stack_ctfe318":(traits,43309)};results={};tmp.mkdir();out.mkdir()
 for mode in ("ordinary","shared-rustc-perf-version"):
  results[mode]={}
  for first,second in (tuple(sdks),tuple(reversed(sdks))):
   key=first+"-to-"+second;wd=tmp/(mode+"-"+key);wd.mkdir();cache=wd/"cache";cache.mkdir();(wd/"lib.rs").write_bytes(src.read_bytes());rows=[]
   for seq,(role,state) in enumerate(((first,"not-loaded"),(first,"loaded"),(second,"not-loaded"),(second,"loaded"))):
    sdk,epoch=sdks[role];slot=wd/"sdk"
    if slot.is_symlink():slot.unlink()
    slot.symlink_to(sdk,target_is_directory=True)
    env={"PATH":str(slot/"bin")+":/usr/bin:/bin","LC_ALL":"C.UTF-8","HOME":str(tmp),"RUSTC_BOOTSTRAP":"1"}
    if mode!="ordinary":env["RUSTC_FORCE_RUSTC_VERSION"]="rustc-perf"
    argv=[str(slot/"bin/rustc"),"--sysroot",str(slot),"--edition=2024","--crate-name=ctfe_epoch","--crate-type=lib","--emit=metadata","-o","libepoch.rmeta","-Cmetadata=ctfe318","-Cincremental="+str(cache),"-Zpublic-api-hash","-Zincremental-info","-Zassert-incr-state="+state,"lib.rs"]
    tag=mode+"-"+key+"-"+str(seq);raw=subprocess.run(argv,cwd=wd,env=env,capture_output=True,timeout=120)
    (out/(tag+".stdout")).write_bytes(raw.stdout);(out/(tag+".stderr")).write_bytes(raw.stderr);assert raw.returncode==0,(tag,raw.stderr[-1600:])
    headers=header_rows(cache);active=[q for q in headers if q[1]==epoch]
    assert {Path(p).name for p,e,v in active}=={"dep-graph.bin","query-cache.bin"}
    crates={Path(p).parts[0] for p,e,v in active};assert len(crates)==1;crate,=crates
    bad=re.findall(r"\[incremental\] ignoring cache artifact `([^`]+)`: Wrong HEADER_FORMAT_VERSION",raw.stderr.decode())
    if seq!=2:assert not bad and (seq==0 or rows[-1]["cache_basename"]==crate)
    elif mode!="ordinary" or rows[-1]["cache_basename"]==crate:assert rows[-1]["cache_basename"]==crate and any("dep-graph" in f or "query-cache" in f for f in bad)
    if mode!="ordinary":assert {v for p,e,v in active}=={"rustc-perf"}
    rows.append({"sdk":role,"expected":state,"cache_basename":crate,"header_rejections":bad,"raw_headers":headers,"stdout":hashlib.sha256(raw.stdout).hexdigest(),"stderr":hashlib.sha256(raw.stderr).hexdigest(),"argv":argv})
   results[mode][key]=rows
 save(out/"passed.json",{"source_sha256":hashlib.sha256(src.read_bytes()).hexdigest(),"modes":results,"native_processes":16})
if __name__=="__main__":run(*(Path(v).resolve() for v in sys.argv[1:]))
