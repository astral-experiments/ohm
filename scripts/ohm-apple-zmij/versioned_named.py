"""Compile a real tracked-path proc macro and independently decode both on-disk forms for each receiver."""
from pathlib import Path
import errno
import gzip
import hashlib
import json
import os
import shutil
import subprocess

import provider_edges as edges
from execs import ExecTrace
from measure import capture, native_rows, select
from study import compress_bytes, env_for, load, need, physical, run, save, sha
from versioned_depfiles import read_files
from versioned_select import CARGOS, choose, current
from versioned import CAGES,V1,V2

def write(cwd,name,text):
    p=cwd/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(text)

def case(root,trace,name,mode):
    cwd=root/"native-collision-source";work=root/"native-collision-work";cwd.mkdir();work.mkdir()
    for directory in ("target", "shared", "cargo-home"):
        (work / directory).mkdir()
    top=root/"receipts/versioned/named"/name/mode;top.mkdir(parents=True)
    write(cwd,"Cargo.toml",'[package]\nname="qa_collision_reader"\nversion="0.0.1"\nedition="2021"\n[dependencies]\nqa_collision={path="qa_collision"}\n[workspace]\nresolver="2"\n')
    write(cwd,"qa_collision/Cargo.toml",'[package]\nname="qa_collision"\nversion="0.0.1"\nedition="2021"\n[dependencies]\nwatch_marker={path="../watch_marker"}\n')
    write(cwd,"watch_marker/Cargo.toml",'[package]\nname="watch_marker"\nversion="0.0.1"\nedition="2021"\n[lib]\nproc-macro=true\n')
    write(cwd,"watch_marker/src/lib.rs",Path(__file__).with_name("versioned_collision.rs").read_text())
    write(cwd,"qa_collision/src/lib.rs",edges.BARRIER+f'\npub fn value()->i32 {{barrier(watch_marker::observed!({mode}) as i32)}}\n')
    write(cwd,"src/main.rs",'fn main(){println!("{}",qa_collision::value());}\n')
    for s in (V1,V2):
        try:os.stat(s)
        except OSError as e:need(e.errno==errno.ENOTDIR,"sentinel has unexpected filesystem state")
        else:raise RuntimeError("literal sentinel unexpectedly exists")
    names={"none":[],"v1":[V1],"v2":[V2],"both":[V1,V2]}[mode]
    sdk=select(root,"C");env=env_for(work,sdk);env["RUSTC_BOOTSTRAP"]="watch_marker"
    run(["cargo","+ohm","generate-lockfile","--offline"],cwd=cwd,env=env)
    save(top/"source.json",{str(p.relative_to(cwd)):p.read_text() for p in sorted(cwd.rglob("*")) if p.is_file()})
    results={};owned={}
    def visit(phase):
        out=top/phase;cmd=["cargo","+ohm","build","--locked","--offline","-j4","--message-format=json"]
        code,std,err,events,stats=capture(cmd,cwd,env,out,trace);facts=native_rows(events,sdk)
        need(code==0 and facts["scope"]=="kernel-exec" and facts["cargo"]==1 and all(e["stock"] for e in facts["linkers"]),
             "surprise compiler/linker or Cargo failure")
        units=[json.loads(l) for l in std.splitlines()];need(units[-1]=={"reason":"build-finished","success":True},"unfinished Cargo")
        exe,=[Path(x["executable"]) for x in units if x["reason"]=="compiler-artifact" and x["target"]["name"]=="qa_collision_reader"]
        exe_result=subprocess.run([str(exe)],cwd=cwd,env=env,capture_output=True,timeout=20)
        need(exe_result.returncode==0 and exe_result.stdout==b"17\n" and exe_result.stderr==b"","wrong literal-path reader behavior")
        data=exe.read_bytes();image=edges.mach(data);compress_bytes(out/"program.macho.gz",data)
        typed,=[x for x in units if x.get("reason")=="compiler-artifact" and x["target"]["name"]=="qa_collision"]
        raw=read_files(out,[work/"target",work/"shared"],"qa_collision")
        ds=[v for v in raw.values() if v["kind"]=="depfile"];disk=[v for v in raw.values() if v["kind"]=="encoded"]
        need(ds and disk and current(root)["name"]==name, "missing compared dep-info or Cargo selection")
        need(all(sorted(f["ordinary"])==sorted(names) and sorted(f["first"])==sorted(names+[V2]) and
                 sorted(f["fake"])==sorted(names+[V2]) for f in ds),"actual tracked path became indistinguishable from the synthetic rule")
        expect_lnk=name=="aware" and not names
        need(all(f["has_LNK1"]==expect_lnk and f["marker_v2"] for f in disk),"receiver did not authenticate exactly one synthetic marker")
        if expect_lnk:need(all(f["linked_marker"]==V2 for f in disk),"authority points at a different dependency")
        full=facts["full"].count("qa_collision")
        need(full==int(not typed["fresh"]) and full==int(phase!="repeat" or not expect_lnk),
             "wrong physical library freshness for a real vs generated path")
        from cgu_inputs import witness
        candidates=[]
        for l in facts["linkers"]:
            if "-o" in l["argv"]:
                output=l["argv"][l["argv"].index("-o")+1]
                stem=Path(output).name
                if stem=="qa_collision_reader" or (stem.startswith("qa_collision_reader-") and not stem.endswith(".dylib")):
                    candidates.append((output,l["argv"]))
        if candidates:
            (output,argv),=candidates
            proof=witness(root,out,data,output,linker=argv);owned[image["raw"]]=proof
        else:
            need(phase=="repeat" and image["raw"] in owned,"unproven relayed collision image")
            proof=owned[image["raw"]]
        result={"selected":current(root),"native":facts,"cgu":proof,"program":image,"exit":exe_result.returncode,"stdout":exe_result.stdout.decode(),
                "files":raw,"fresh":typed["fresh"],"interval":stats,"ordinary":names}
        save(out/"verified.json",result)
        return result
    for phase in ("cold","repeat","empty"):
        results[phase]=edges.with_empty(work,lambda:visit(phase)) if phase=="empty" else visit(phase)
    from cgu_inputs import agrees
    need(all(v["program"]["text"]==results["empty"]["program"]["text"] and agrees(v["cgu"],results["empty"]["cgu"])
             for v in results.values()),"different clean native product in literal-path reader")
    save(top/"terminal.json",{k:sha(top/k/"verified.json") for k in results})
    shutil.rmtree(cwd);shutil.rmtree(work)
    return sha(top/"terminal.json")

def run_named(root):
    # Confirm the independent digest reader against a fixed public BLAKE3 test vector.
    path=shutil.which("b3sum");need(path is not None,"b3sum not provisioned")
    need(subprocess.check_output([path],input=b"").decode().split()[0]=="af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262","invalid BLAKE3 reader")
    top=root/"receipts/versioned/named";save(top/"b3sum.json",physical(Path(path)))
    tr=ExecTrace();tr.ready();rows={}
    try:
        for n in ("signed","classic","aware"):
            choose(root,n);rows[n]={m:case(root,tr,n,m) for m in CAGES}
    finally:tr.close()
    save(top/"terminal.json",rows)
