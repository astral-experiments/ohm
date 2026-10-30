"""Physically qualify the independent #276 and #277 registry markers in the pre-ObjC Rust arm."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
sys.path.insert(0,str(Path(__file__).resolve().parent))
from cgu_inputs import agrees,witness
from execs import ExecTrace
from measure import capture,fresh,native_rows,retire,select
from provider_edges import mach
from study import PARENT,ZMIJ,ZMIJ_LIB,check_host,compress_bytes,env_for,load,need,run,save,sha
from versioned import V1,V2,HARD
from versioned_select import CARGOS,choose,current
from zlib_study import ZLIB,ZLIB_LIB,ACLE

PACKAGES={"zmij":("zmij","1.0.10",ZMIJ,ZMIJ_LIB,[]),
          "zlib_rs":("zlib-rs","0.5.5",ZLIB,ZLIB_LIB,["rust-allocator","std"])}
def run_all(root):
    check_host(root,8);sdk=select(root,"P");rec=root/"receipts/versioned/registry";rec.mkdir(parents=True)
    source=root/"versioned-registry-source";work=root/"versioned-registry-work";source.mkdir();work.mkdir()
    (source/"src").mkdir()
    program='fn main(){println!("{} {:08x}",zmij::Buffer::new().format(std::hint::black_box(1.234f64)),zlib_rs::crc32::crc32(0,std::hint::black_box(b"123456789")));}\n'
    manifest='[package]\nname="qa_registry_reader"\nversion="0.0.1"\nedition="2021"\n[workspace]\nresolver="2"\n[dependencies]\nzmij="=1.0.10"\nzlib-rs={version="=0.5.5",default-features=false,features=["std"]}\n'
    (source/"src/main.rs").write_text(program);(source/"Cargo.toml").write_text(manifest)
    trace=ExecTrace();trace.ready();all_rows={}
    try:
        for name in ("signed","classic","aware"):
            binding=choose(root,name);fresh(work,root/"seed");env=env_for(work,sdk)
            if not (source/"Cargo.lock").exists():run(["cargo","+ohm","generate-lockfile","--offline"],cwd=source,env=env)
            lock=tomllib.loads((source/"Cargo.lock").read_text())["package"]
            for crate,(pkg,v,h,_,_) in PACKAGES.items():
                x,=[p for p in lock if p["name"]==pkg];assert x["version"]==v and x["checksum"]==h
                held,=(work/"cargo-home/registry/cache").glob("*/"+pkg+"-"+v+".crate");need(sha(held)==h,"wrong registry archive")
            held={};rows={}
            for phase in ("cold","first-repeat","second-repeat","empty"):
                if phase=="empty":retire(work);fresh(work,root/"seed")
                out=rec/name/phase
                cmd=["cargo","+ohm","build","--locked","--offline","-j4","--message-format=json"]
                code,std,err,events,stats=capture(cmd,source,env,out,trace);native=native_rows(events,sdk)
                need(code==0 and native["scope"]=="kernel-exec" and native["cargo"]==1 and all(e["stock"] for e in native["linkers"]),"non-native registry test")
                typed=[json.loads(l) for l in std.splitlines()];assert typed[-1]=={"reason":"build-finished","success":True}
                units=[r for r in typed if r["reason"]=="compiler-artifact"]
                crate_facts={}
                for crate,(pkg,ver,h,lib,features) in PACKAGES.items():
                    row,=[r for r in units if r["target"]["name"]==crate and r["target"]["kind"]==["lib"]]
                    need(row["package_id"].endswith("#"+pkg+"@"+ver) and sorted(row["features"])==features,"changed actual registry unit")
                    file=Path(row["target"]["src_path"]);need(sha(file)==lib and (crate!="zlib_rs" or sha(file.parent/"crc32/acle.rs")==ACLE),"mutated registry source")
                    archive,=[Path(p) for p in row["filenames"] if p.endswith(".rlib")]
                    basename=archive.stem.removeprefix("lib")+".d"
                    deps={ (p.stat().st_dev,p.stat().st_ino):p for t in ("target","shared") for p in (work/t).rglob(basename)}
                    dep,=deps.values();original=dep.read_bytes();lines=original.decode().splitlines()
                    need(V2+":" in lines and V1+":" not in lines and HARD+":" not in lines,"unexpected registry producer marker")
                    full=native["full"].count(crate);need(full==int(not row["fresh"]),"physical registry compiler did not match Cargo")
                    # Record all three bindings even if a native receiver satisfies the marker differently.
                    compress_bytes(out/(crate+".dep.gz"),original)
                    crate_facts[crate]={"package":row,"source":str(file),"source_sha":sha(file),"archive":sha(archive),
                                       "dep_sha":sha(dep),"physical_full":full,"marker":V2}
                reader,=[r for r in units if r["target"]["name"]=="qa_registry_reader" and r["executable"]]
                exe=Path(reader["executable"]);data=exe.read_bytes();image=mach(data)
                output=subprocess.run([exe],cwd=source,env=env,capture_output=True,timeout=20)
                need(output.returncode==0 and output.stdout==b"1.234 cbf43926\n" and not output.stderr,"wrong real float or CRC behavior")
                compress_bytes(out/"program.macho.gz",data)
                outputs=[(l["argv"][l["argv"].index("-o")+1],l["argv"]) for l in native["linkers"] if "-o" in l["argv"]]
                relevant=[(p,a) for p,a in outputs if Path(p).name=="qa_registry_reader" or Path(p).name.startswith("qa_registry_reader-")]
                if relevant:
                    (p,a),=relevant;proof=witness(root,out,data,p,linker=a);held[image["raw"]]=proof
                else:
                    need(phase.endswith("repeat") and image["raw"] in held,"returned registry program lacks an earlier actual link")
                    proof=held[image["raw"]]
                row={"cargo":binding,"rust":PARENT,"native":native,"crates":crate_facts,"program":image,
                     "observation":output.stdout.decode(),"cgu":proof,"streams":stats["streams"]}
                save(out/"verified.json",row);rows[phase]=row
            for a in rows.values():
                need(agrees(a["cgu"],rows["empty"]["cgu"]),"empty registry reader gives a different program")
            counts={p:{k:f["physical_full"] for k,f in r["crates"].items()} for p,r in rows.items()}
            all_rows[name]={"counts":counts,"program":"1.234 cbf43926","role":PARENT,"binding":binding}
            save(rec/name/"terminal.json",all_rows[name]);retire(work)
    finally:trace.close()
    save(rec/"sources.json",{"manifest":manifest,"program":program,"lock":(source/"Cargo.lock").read_text()})
    save(rec/"terminal.json",all_rows)
    for which in ("signed","classic","aware"):
        for p,cc in all_rows[which]["counts"].items():
            expected=1 if p in ("cold","empty") or which!="aware" else 0
            need(set(cc.values())=={expected},"physical #276/#277 registry fallback differed: "+str((which,p,cc)))
    choose(root,"aware")
if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("root",type=Path);args=ap.parse_args();run_all(args.root.resolve())
