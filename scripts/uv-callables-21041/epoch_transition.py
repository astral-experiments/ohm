"""Qualify genuine default cross-compiler separation and same-compiler reuse in both directions."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

EXPECTED_ERROR="we asserted that an existing incremental cache directory should be successfully loaded, but it was not"
FIXTURE="5a9697f6f817af54e0d0d01047a12d9d043cc416c5aa6f52f51790893f141bda"
def need(ok,msg):
    if not ok:raise ValueError(msg)
def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def headers(cache):
    result=[]
    for name in ("dep-graph.bin","query-cache.bin"):
        for p in sorted(cache.rglob(name)):
            need(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(cache.resolve()),"cache member")
            with p.open("rb")as f:
                first=f.read(7);need(len(first)==7 and first[:4]==b"RSIC" and first[6]>0,"native cache header")
                ver=f.read(first[6]);need(len(ver)==first[6],"truncated cache version")
            result.append([p.relative_to(cache).as_posix(),int.from_bytes(first[4:6],"little"),ver.decode()])
    return sorted(result)
def validate(rows,roles,sources):
    need(len(rows)==4,"four native visits required")
    for n,(r,role,expect) in enumerate(zip(rows,(roles[0],roles[0],roles[1],roles[1]),("not-loaded","loaded","not-loaded","loaded"),strict=True)):
        epoch=sources[role]["epoch"];prefix=sources[role]["commit"][:9]
        need(r["sdk"]==role and r["expected"]==expect and "-Zassert-incr-state="+expect in r["argv"],"wrong actual compiler or asserted native state")
        active=[a for a in r["raw_headers"] if a[1]==epoch]
        need(len(active)==2 and {Path(q[0]).name for q in active}=={"dep-graph.bin","query-cache.bin"} and
             {Path(q[0]).parts[0]for q in active}=={r["cache_basename"]} and all(prefix in x[2] and "rustc-perf" not in x[2] for x in active),"incorrect active, mixed, or forced header")
        need(all(x[1] in {sources[v]["epoch"]for v in roles} and "rustc-perf" not in x[2]for x in r["raw_headers"]),"foreign header or forced identity")
        if n in (1,3):
            need(rows[n-1]["cache_basename"]==r["cache_basename"] and not r["header_rejections"],"same compiler did not reuse its own unchanged cache")
        elif n==2:
            need(rows[n-1]["cache_basename"]!=r["cache_basename"] or r["header_rejections"],"incompatible switch lacked a natural separation or epoch rejection")
        if n!=2:need(not r["header_rejections"],"unexpected native header rejection")
def gate(pair_roles):
    import core as c
    w,temp=c.host();origin=c.HERE/"epoch-fixture.rs";need(sha(origin)==FIXTURE,"changed native fixture")
    out=w/"trait-results/intake/natural-epoch-transition";out.mkdir()
    root=temp/"natural-production-epoch-check";root.mkdir()
    sources={r:c.PAIR["arms"][r]["source"]for r in pair_roles};pool=temp/"ctfe22-root-sdks"
    need([sources[r]["epoch"]for r in pair_roles]==[43310,43309],"wrong source-specific epochs")
    histories={};negatives={}
    for roles in (pair_roles,list(reversed(pair_roles))):
        name=roles[0]+"-to-"+roles[1];wd=root/name;wd.mkdir();q=out/name;q.mkdir()
        (wd/"lib.rs").write_bytes(origin.read_bytes());cache=wd/"cache";cache.mkdir();slot=wd/"sdk";rows=[]
        for n,(role,state)in enumerate(zip((roles[0],roles[0],roles[1],roles[1]),("not-loaded","loaded","not-loaded","loaded"),strict=True)):
            if slot.is_symlink():slot.unlink()
            sdk=pool/role;slot.symlink_to(sdk,target_is_directory=True)
            env={"PATH":str(slot/"bin")+":/usr/bin:/bin","LC_ALL":"C.UTF-8","HOME":str(wd),"RUSTC_BOOTSTRAP":"1"}
            argv=[str(slot/"bin/rustc"),"--sysroot",str(slot),"--edition=2024","--crate-name=ctfe_epoch","--crate-type=lib","--emit=metadata","-o","libepoch.rmeta",
                  "-Cmetadata=ctfe318","-Cincremental="+str(cache),"-Zpublic-api-hash","-Zincremental-info","-Zassert-incr-state="+state,"lib.rs"]
            raw=subprocess.run(argv,cwd=wd,env=env,capture_output=True,timeout=60);(q/f"{n}.stderr").write_bytes(raw.stderr);(q/f"{n}.stdout").write_bytes(raw.stdout)
            need(raw.returncode==0,(role,state,raw.stderr[-900:]));hs=headers(cache);epoch=sources[role]["epoch"]
            owner,={Path(a[0]).parts[0]for a in hs if a[1]==epoch}
            rejections=re.findall(r"\[incremental\] ignoring cache artifact `([^`]+)`: Wrong HEADER_FORMAT_VERSION",raw.stderr.decode())
            rows.append({"sdk":role,"expected":state,"argv":argv,"env":env,"stdout":sha(q/f"{n}.stdout"),"stderr":sha(q/f"{n}.stderr"),
                         "raw_headers":hs,"cache_basename":owner,"header_rejections":rejections,"rmeta":sha(wd/"libepoch.rmeta")})
        validate(rows,roles,sources)
        need(rows[0]["rmeta"]==rows[1]["rmeta"] and rows[2]["rmeta"]==rows[3]["rmeta"],"changed same-compiler metadata")
        # Deliberately request a loaded state on a new physical cache. It must be refused for the recorded native reason.
        virgin=wd/"virgin";virgin.mkdir();av=[("-Cincremental="+str(virgin)) if v.startswith("-Cincremental=") else v for v in argv]
        need("-Zassert-incr-state=loaded" in av,"negative not asserted");raw=subprocess.run(av,cwd=wd,env=env,capture_output=True,timeout=60)
        (q/"fresh-assert-loaded.stderr").write_bytes(raw.stderr);(q/"fresh-assert-loaded.stdout").write_bytes(raw.stdout)
        need(raw.returncode!=0 and EXPECTED_ERROR.encode()in raw.stderr,"known-empty native cache wrongly accepted")
        negatives[roles[1]]={"exit":raw.returncode,"diagnostic":EXPECTED_ERROR,"sha256":sha(q/"fresh-assert-loaded.stderr"),"argv":av}
        histories[name]=rows
    c.m.save(out/"passed.json",{"ordinary_only":True,"source_sha256":FIXTURE,"sources":sources,"histories":histories,"negative":negatives,"positive_native_calls":8,"negative_native_calls":2})
