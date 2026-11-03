"""Reopen the complete physical Cargo and native controls from one immutable worker ZIP."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent))
from member_names import read_names, native_identity
from public_states import inspect as inspect_metadata
from partition_outcome import Archive, need, summarize

def hash_file(path):
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()

def materialize(archive,ref,path):
    size=ref["bytes"];digest=ref["sha256"]
    need(0<size<=600*2**20 and len(digest)==64 and all(c in "0123456789abcdef"for c in digest),"oversized or unsigned native manifest")
    frame=path.with_suffix(".zst");name="native/"+digest+".zst";m=archive.file.getinfo(name)
    need(m.file_size<=size+2**20,"oversized compressed input")
    with archive.file.open(m)as z, frame.open("wb")as out:shutil.copyfileobj(z,out,2**20)
    def limit():resource.setrlimit(resource.RLIMIT_FSIZE,(size,size))
    with path.open("wb") as out:subprocess.run(["zstd","-qdc",frame],stdout=out,preexec_fn=limit,check=True)
    need(path.stat().st_size==size and hash_file(path)==digest,("different complete native input",digest))
    frame.unlink()

def observation(z,role):
    root=role+"/observed-edit/tasks/";tools=z.js(role+"/tools.json")
    rust=(tools["rustc"]["dev"],tools["rustc"]["ino"])
    owners={};by=Counter();execs=[];no_clock=Counter();monitor=None;whole=None
    for line in z.file.read(root+"epochs.tsv").splitlines():
        fields=line.split();tag=fields[0]
        if tag==b"M":
            need(monitor is None and not owners and len(fields)==3 and all(int(x)>0 for x in fields[1:]),"wrong monitor origin")
            monitor=int(fields[1])
        elif tag==b"W":
            need(whole is None and monitor is not None and len(fields)==5,"wrong final command journal")
            whole,enabled,active,status=map(int,fields[1:])
            need(whole>0 and enabled==active>0 and status==0,"incomplete observer")
        elif tag==b"I":
            index=int(fields[1]);parts=z.file.read(root+f"{index:05}.nul").split(b"\0")
            need(parts.pop()==b"" and parts[0]==fields[2] and index not in owners,"different task image")
            owner=Path(os.fsdecode(parts[3])).name;pair=tuple(map(int,parts[1:3]));args=parts[4:]
            if pair==rust and b"--crate-name" in args:owner="rustc:"+os.fsdecode(args[args.index(b"--crate-name")+1])
            need(owner not in ("wild","ld.bfd"),"unexpected native linker in a library-only edit")
            owners[index]=owner
            if fields[5]==b"exec" and owner.startswith("rustc:"):execs.append(owner)
        elif tag==b"C":
            index,_,_,n,e,r=map(int,fields[1:]);need(index in owners and n>=0 and e==r,"partial or multiplexed process")
            by[owners[index]]+=n
            if n and not e:no_clock[owners[index]]+=n
        else:raise ValueError(("unknown wait event",fields))
    receipt=z.js(role+"/observed-edit/result.json")["observed"]
    need(dict(by)==receipt["process_instructions"] and execs==receipt["real_execs"] and dict(no_clock)==receipt["positive_instructions_without_clock"],"different hardware attribution")
    need(by["rustc:ty_project"]>0 and not no_clock["rustc:ty_project"],"no qualified affected compiler")
    need(monitor is not None and whole is not None,"missing process boundaries")
    return {"commands":execs,"instructions":by,"observed_command":whole}

def main():
    p=argparse.ArgumentParser();p.add_argument("archive",type=Path);p.add_argument("--sha256",required=True);p.add_argument("--case",choices=["29697","29604"],required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--work",type=Path,required=True);a=p.parse_args()
    need(a.archive.is_file() and hash_file(a.archive)==a.sha256,"different original GitHub artifact")
    a.work.mkdir(exist_ok=True);need(shutil.disk_usage(a.work).free>15*2**30,"native reader disk reserve")
    z=Archive(a.archive);case=a.case;report={"archive":a.sha256,"case":case,"roles":{}}
    terminal=z.js("result.json");binding=json.loads((here/"binding.json").read_bytes())
    reg=z.js("registration.json");need(reg["binding"]==binding and reg["case"]==case and reg["order"]==("PC" if case=="29697"else"CP"),"incorrect source registration or role order")
    need(z.js("factory-consumed.json")["drivers"]==binding["driver"],"registered and consumed compilers differ")
    with tempfile.TemporaryDirectory(prefix="root-lanes-",dir=a.work) as d:
        t=Path(d);fixture=t/"fixture";fixture.mkdir()
        (fixture/"script.py").write_bytes(b'#!/usr/bin/env -S uv run --script\n# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\nprint("fixture")\n')
        lib=t/"actual.rlib";exe=t/"client"
        for role in reg["order"]:
            accounts={};native={};verdicts={};raw={}
            for phase in ("old","edit","unchanged","repair","independent-clean"):
                result=z.js(role+"/"+phase+"/result.json");counter=z.js(role+"/"+phase+"/hardware.json");acc=counter["instructions"]
                need(counter["status"]==0 and counter["running"]==counter["enabled"]>0 and acc==result["instructions"]>0,"partial whole Cargo counter")
                accounts[phase]=acc
                if phase=="unchanged":continue
                body=result["native"]["elf"]
                if phase in ("old","edit","independent-clean"):
                    n=z.js(role+"/"+phase+"/native.json");native[phase]={}
                    for crate in ("ty_project","ty_ide"):
                        original=n[crate];materialize(z,original["library"],lib)
                        read=json.loads(json.dumps(read_names(lib,crate)))
                        need(read==original["mapping"],("original .rlib and recorded archive index differ",crate,phase))
                        need({r[2]+".o":(r[3],r[4])for r in read["members"]}=={k:(r["sha256"],r["bytes"])for k,r in original["objects"].items()},"saved work products differ from the emitted library")
                        native[phase][crate]=read
                materialize(z,body,exe);exe.chmod(0o755)
                cmd=[exe,fixture] if case=="29697"else [exe]
                run=subprocess.run(cmd,cwd=t,env=os.environ|{"UV_OFFLINE":"1","NO_COLOR":"1"},capture_output=True,timeout=60)
                expected=(("scripts=1"if phase=="old"else"scripts=0")+"\nscripts=1\nvendored-paths=3\n") if case=="29697"else (("unrelated-preserved=false"if phase=="old"else"unrelated-preserved=true")+"\nvendored-path=stdlib/os.pyi\n")
                need(run.returncode==0 and run.stdout.decode()==result["native"]["stdout"]==expected and
                     z.file.read(role+"/"+phase+"/oracle/stdout")==run.stdout,("native client and real worker stdout differ",role,phase,run.stdout,run.stderr[-600:]))
                verdicts[phase]={"sha256":body["sha256"],"stdout":expected}
            need(verdicts["edit"]==verdicts["repair"]==verdicts["independent-clean"] and verdicts["old"]!=verdicts["edit"],"stale or unstable real native client")
            for k in ("ty_project","ty_ide"):
                need(native_identity(native["edit"][k])==native_identity(native["independent-clean"][k]),("clean original native archives differ",k))
            errors=list(map(json.loads,z.file.read(role+"/invalid/stdout.jsonl").splitlines()))
            need(any((r.get("message",{}).get("code")or{}).get("code")=="E0308" for r in errors if r["reason"]=="compiler-message") and errors[-1]=={"reason":"build-finished","success":False},"absent genuine Rust diagnostic")
            observed=observation(z,role);need(accounts["edit"]==terminal["roles"][role]["primary"] and observed["instructions"]["rustc:ty_project"]==terminal["roles"][role]["project"],"different complete/driver accounting")
            report["roles"][role]={"hardware":accounts,"observed":observed,"verdicts":verdicts}
    class Metadata:
        def read(self,name):
            if name.endswith("/native.json"):return json.dumps({"outputs":z.js(name)}).encode()
            return z.file.read(name)
    pub=inspect_metadata(Metadata());need(pub==z.js("public-states.json") and pub["equal_stable_identities_and_edit_key_sets"],"different metadata rows or control")
    report["metadata"]=pub;report["partitions"]=summarize(a.archive,case)
    a.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
if __name__=="__main__":main()
