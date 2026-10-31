"""Exercise Rust-mangled symbols in real dylib consumers while the producer's Rust-visible hash stays put."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native import HERE, HOST, PARENT, blob, call, environment, need, save, sha, subjects

CASES = {"foreign-adt-abi": ("type_of", 17, 4294967313), "foreign-adt-section": ("codegen_fn_attrs",17,17),
         "exact-private-impl-body": ("def_span",1,2), "pure-rust-dylib-client": ("type_of",17,4294967313)}
PHASES = ("cold-A","unchanged-A","edit-B","unchanged-B","return-A","return-B","invalid-A",
          "repair-A","empty-B","empty-A","empty-invalid-A")
CMD = ["cargo","+ohm","build","-p","dylib_owner","--lib","--locked","--offline","-j4","--message-format=json"]


def specification(case):
    d=json.loads((HERE/"fixtures/dylib"/(case+".json")).read_bytes())
    pure = case=="pure-rust-dylib-client"
    cmd = ["cargo","+ohm","build","-p","dylib_client","--bin","dylib_client",*CMD[6:]] if pure else CMD
    if pure:
        need(all("unsafe" not in source and 'extern "C"' not in source for name,source in d["files"].items() if name.endswith(".rs")),
             "unexpected native language escape")
    else:
        need('#[unsafe(no_mangle)]' in d['files']['owner/src/lib.rs'],"missing dynamic test entry")
    need(d["commands"] == cmd and not any('no_mangle' in t or 'export_name' in t for t in (d['A'],d['B'],d['files']['dep/src/lib.rs'])),
         "unexpected externally named producer")
    return d


def symbols(path, case, native_state):
    p=subprocess.run(["nm","-D","-C","--defined-only",path],check=True,capture_output=True)
    names=[l for l in p.stdout.decode().splitlines() if " as core::convert::From<dylib_leaf::hidden::Input>>::from" in l]
    expected="core::net::ip_addr::Ipv4Addr" if case=="exact-private-impl-body" else "core::time::Duration"
    need(len(names)==1 and " T <"+expected in names[0] and
         sum(l.endswith(" T dylib_native_value") for l in p.stdout.decode().splitlines())==int(case!="pure-rust-dylib-client"),("wrong dynamic symbol",case,names))
    sections = subprocess.check_output(["readelf","-WS",path],text=True)
    custom = re.findall(r"\s(\.ohm\.private\.[ab]+)\s", sections)
    want = [".ohm.private." + ("aaaa" if native_state=="A" else "bbbb")] if case=="foreign-adt-section" else []
    need(custom == want, ("incorrect actual linked section",case,native_state,custom))
    return names[0],custom


def run(out, work, case, sdk, revision):
    d=specification(case)
    cmd=d["commands"]
    out.mkdir(parents=True)
    env=environment(work,sdk)
    save(out/"subject.json",{"versions":subjects(sdk,env,revision), "revision":revision,"case":case,
                              "original_enrollment":d["original_enrollment"],"cmd":cmd})
    p=work/"workspace"
    for n,s in d["files"].items():
        path=p/n;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(s)
    s=p/"dep/src/hidden.rs";s.write_text(d["A"])
    need(call(["cargo","+ohm","generate-lockfile","--offline"],env,p).returncode==0,"unable to lock tiny workspace")
    (out/"Cargo.lock").write_bytes((p/"Cargo.lock").read_bytes())
    store=out/"bodies";store.mkdir()
    for phase in PHASES:
        state=phase[-1]
        text=d[state] + ('const _: u8 = "wrong";\n' if "invalid" in phase else '')
        if s.read_text()!=text:s.write_text(text)
        if phase.startswith("empty-"):
            for n in ("target","build"):(work/n).rename(work/(n+"-before-"+phase))
        loc=out/phase;loc.mkdir()
        v=call(cmd,env,p)
        blob(loc/"stdout.gz",v.stdout);blob(loc/"stderr.gz",v.stderr)
        for f in p.glob("rustc-ice-*.txt"):shutil.move(f,loc/f.name)
        raw=[json.loads(l) for l in v.stdout.splitlines()]
        need(raw[-1]=={"reason":"build-finished","success":v.returncode==0},"incomplete Cargo")
        es=[e for e in raw if e["reason"]=="compiler-artifact"]
        row={"code":v.returncode,"source":sha(s),"typed":[[e["target"]["name"],e["fresh"]] for e in es]}
        if "invalid" not in phase:
            leaf,=[Path(n) for e in es if e["target"]["name"]=="dylib_leaf" for n in e["filenames"] if n.endswith(".rlib")]
            meta=leaf.with_suffix(".rmeta");data=meta.read_bytes()
            fingerprint=call(["rustc","+ohm","-Zls=public_hash",leaf],env,p)
            need(fingerprint.returncode==0 and re.fullmatch(rb"Public hash: [0-9a-f]{32}\s*",fingerprint.stdout),"wrong public hash")
            row["public"]=fingerprint.stdout.decode().strip().split()[-1]
            row["rmeta"]=sha(meta)
            tag=int.from_bytes(data[8:16],"little");prefix=b'\x00\x18x86_64-unknown-linux-gnu\xc1'
            need(data[tag:tag+len(prefix)]==prefix,"different metadata schema")
            row["physical_private_public"]=data[tag+len(prefix):tag+len(prefix)+32].hex()
            dest=store/(row["rmeta"]+".rmeta.gz")
            if not dest.exists():blob(dest,data)
        if v.returncode==0:
            lib,=[Path(n) for e in es if e["target"]["name"]=="dylib_owner" and e["target"]["crate_types"]==["dylib"]
                 for n in e["filenames"] if n.endswith(".so")]
            if case == "pure-rust-dylib-client":
                exe, = [Path(e["executable"]) for e in es if e.get("executable") and e["target"]["name"]=="dylib_client"]
                needed=subprocess.check_output(["readelf","-d",exe],text=True)
                names=re.findall(r"Shared library: \[(.*?)\]",needed)
                need(lib.name in names and sum(n.startswith("libstd-") for n in names)==1,"missing actual Rust dynamic dependencies")
                runtime_env=env|{"LD_DEBUG":"libs","LD_LIBRARY_PATH":":".join(map(str,[lib.parent,sdk/"lib/rustlib"/HOST/"lib",sdk/"lib"]))}
                inv=call([exe],runtime_env,p)
                paths=[Path(n.decode()) for n in re.findall(rb"calling init:\s*(\S+)",inv.stderr) if Path(n.decode()).name==lib.name]
                need(len(paths)==1 and paths[0].samefile(lib),("different dynamic provider",paths,lib))
                row.update(exe=sha(exe),needed=names,loaded=str(paths[0]),owner=str(lib),physical=[lib.stat().st_dev,lib.stat().st_ino])
                blob(loc/"loader.gz", inv.stderr)
                stored=store/(row["exe"]+".exe.gz")
                if not stored.exists():blob(stored,exe.read_bytes())
                rv,=re.findall(rb"^actual Rust client = (\d+)\n$",inv.stdout)
            else:
                inv=call([sys.executable,"-IB","-c",d["reader"],lib],env|{"LD_LIBRARY_PATH":str(sdk/"lib/rustlib"/HOST/"lib")},p)
                rv=inv.stdout
            need(inv.returncode==0,inv.stderr)
            (loc/"runtime.txt").write_bytes(inv.stdout)
            row["value"]=int(rv);row["so"]=sha(lib)
            row["export"],row["sections"]=symbols(lib,case,state)
            dest=store/(row["so"]+".so.gz")
            if not dest.exists():blob(dest,lib.read_bytes())
        save(loc/"visit.json",row)
        print(case,phase,v.returncode,row.get("value"),flush=True)


def read(out,case,role,sdk=None):
    d=specification(case)
    query,a,b=CASES[case]
    results={};public=set();used=set();private={};replayed={}
    pure=case=="pure-rust-dylib-client"
    with tempfile.TemporaryDirectory() as tmp:
        for phase in PHASES:
            loc=out/phase;r=json.loads((loc/"visit.json").read_bytes());state=phase[-1]
            ice=role=="parent" and phase in ("edit-B","unchanged-B","return-B")
            invalid="invalid" in phase
            code=101 if ice or invalid else 0
            stdout=[json.loads(l) for l in gzip.decompress((loc/"stdout.gz").read_bytes()).splitlines()]
            err=gzip.decompress((loc/"stderr.gz").read_bytes()).decode()
            source=d[state] + ('const _: u8 = "wrong";\n' if invalid else '')
            need(r["source"]==hashlib.sha256(source.encode()).hexdigest() and r["code"]==code and
                 stdout[-1]=={"reason":"build-finished","success":code==0}, (case,phase,"unexpected source/Cargo result",r))
            actual=[[e["target"]["name"],e["fresh"]] for e in stdout if e["reason"]=="compiler-artifact"]
            need(r["typed"]==actual,"wrong current typed events")
            if invalid:
                coded=[e["message"] for e in stdout if e["reason"]=="compiler-message" and
                       e["message"]["level"]=="error" and e["message"]["code"]]
                need(len(coded)==1 and coded[0]["code"]["code"]=="E0308"
                     and any(s["file_name"]=="dep/src/hidden.rs" and s["is_primary"] for s in coded[0]["spans"]) and
                     "unstable fingerprints" not in err and "so" not in r,"different invalid-source result")
            else:
                need(r["public"]==bytes.fromhex(r["physical_private_public"][32:])[::-1].hex(),
                     ("public fingerprint representation",r))
                raw=gzip.decompress((out/"bodies"/(r["rmeta"]+".rmeta.gz")).read_bytes())
                need(hashlib.sha256(raw).hexdigest()==r["rmeta"],"bad rmeta")
                base=int.from_bytes(raw[8:16],"little")
                prefix=b'\x00\x18x86_64-unknown-linux-gnu\xc1'
                off=base+len(prefix)
                need(raw[base:off]==prefix and raw[off:off+32].hex()==r["physical_private_public"],"wrong physical identity")
                public.add(r["public"]);private[state]=r["physical_private_public"][:32]
                used.add(r["rmeta"]+".rmeta.gz")
            if ice:
                need("Found unstable fingerprints for "+query+"(" in err and "#0 ["+query+"]" in err
                     and "dylib_leaf" in err and "so" not in r,("different native query",case,phase))
            if code==0:
                need([n for n,_ in actual]==(["dylib_leaf","dylib_owner","dylib_client"] if pure else ["dylib_leaf","dylib_owner"]) and "internal compiler error" not in err,"incorrect native roster")
                if phase in ("cold-A","empty-A","empty-B"):need(all(not f for _,f in actual),"not empty")
                if phase.startswith("unchanged-"):need(all(f for _,f in actual),"incorrect unchanged roster")
                so=gzip.decompress((out/"bodies"/(r["so"]+".so.gz")).read_bytes())
                need(hashlib.sha256(so).hexdigest()==r["so"] and so[:4]==b"\x7fELF","wrong shared object")
                f=Path(tmp)/("lib"+r["so"]+".so")
                if not f.exists():f.write_bytes(so)
                syms,sects=symbols(f,case,state)
                expected=a if state=="A" else b
                expected_stdout=(("actual Rust client = " if pure else "")+str(expected)+"\n").encode()
                need(r["export"]==syms and r["sections"]==sects and
                     (loc/"runtime.txt").read_bytes()==expected_stdout and r["value"]==expected,"wrong shared library behavior")
                used.add(r["so"]+".so.gz")
                held_key=(r["so"],r.get("exe"))
                if pure:
                    stamp = re.findall(rb"calling init:\s*(\S+)",gzip.decompress((loc/"loader.gz").read_bytes()))
                    need(r["loaded"].encode() in stamp and Path(r["loaded"]).name==Path(r["owner"]).name=="libdylib_owner.so"
                         and r["physical"][1]>0 and "libdylib_owner.so" in r["needed"],"unattested Rust dynamic load")
                    exe=gzip.decompress((out/"bodies"/(r["exe"]+".exe.gz")).read_bytes())
                    need(hashlib.sha256(exe).hexdigest()==r["exe"],"wrong actual executable")
                    used.add(r["exe"]+".exe.gz")
                if sdk and held_key not in replayed:
                    rd=Path(tmp)/("exec-"+str(len(replayed)));rd.mkdir()
                    dl=rd/"libdylib_owner.so";dl.write_bytes(so)
                    ld_env={"PATH":"/usr/bin:/bin","LD_LIBRARY_PATH":":".join(map(str,[rd,sdk/"lib/rustlib"/HOST/"lib",sdk/"lib"])),"LD_DEBUG":"libs"}
                    if pure:
                        client=rd/"client";client.write_bytes(exe);client.chmod(0o700);argv=[client]
                    else:
                        argv=[sys.executable,"-IB","-c",d["reader"],dl]
                    real=subprocess.run(argv,cwd=rd,env=ld_env,capture_output=True,timeout=15)
                    seen=[Path(n.decode()) for n in re.findall(rb"calling init:\s*(\S+)",real.stderr) if Path(n.decode()).name==dl.name]
                    need(real.returncode==0 and real.stdout==expected_stdout and len(seen)==1 and seen[0].samefile(dl),
                         ("isolated native loader replay failed",case,phase,real.returncode,real.stdout))
                    replayed[held_key]=real.stdout.decode().strip()
            results[phase]={"code":code,"so":r.get("so"),"exe":r.get("exe"),"value":r.get("value"),"public":r.get("public")}
    need(used=={p.name for p in (out/"bodies").iterdir()} and len(public)==1 and private["A"]!=private["B"],
         ("changed Rust-visible contract or missing artifacts",case,public,private))
    for phase,row in results.items():
        if row["code"]==0:need((row["so"],row["exe"])==(results["empty-"+phase[-1]]["so"],results["empty-"+phase[-1]]["exe"]),("warm vs empty dynamic image",case,phase))
    need(results["empty-A"]["so"] != results["empty-B"]["so"],"different sources did not change native images")
    return results


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=("run","read"));p.add_argument("out",type=Path)
    p.add_argument("role",choices=("parent","candidate"));p.add_argument("--work",type=Path);p.add_argument("--sdk",type=Path);p.add_argument("--revision");p.add_argument("--case",action="append",choices=CASES)
    opt=p.parse_args();out=opt.out.resolve()
    if opt.mode=="run":
        for c in opt.case or CASES:run(out/c,opt.work.resolve()/c,c,opt.sdk.resolve(),opt.revision)
    else:
        result={c:read(out/c,c,opt.role,opt.sdk.resolve() if opt.sdk else None) for c in opt.case or CASES}
        save(out/'verified.json',result);print("verified ordinary dylibs",opt.role,len(result),sum(map(len,result.values())))
