"""Transport the fixed physical source capsule and its separate executing-pass admission."""
import json
import os
from pathlib import Path
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
STAGE=HERE.parent/"ruff-ldv-physical-stage"
sys.path.append(str(STAGE))
from retained import (ARCHIVE,BUILD,BUILD_QA,BRANCH,CONFIRM,REPO,acquire,artifact,capsule,factory,fetch,need,
                      run_identity,save,sha,unzip_member)

LLVM="lib/libLLVM.so.23.1-rust-1.99.0-beta"
LLVM_SHA="43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51"
SCRIPT="lib/libLLVM-23-rust-1.99.0-beta.so"


def llvm_name(parked,names):
    selected={n for n in names if n.startswith("lib/libLLVM")}
    need(selected=={LLVM,SCRIPT} and names[LLVM][0]==LLVM_SHA and
         (parked/SCRIPT).read_bytes()==("INPUT("+Path(LLVM).name+")\n").encode() and
         names[SCRIPT][0]==sha(parked/SCRIPT),"wrong real shared LLVM or linker script")
    return LLVM


def live_input(live,info):
    key=info["sha256"]
    expect=[os.makedev(*info["device"]),info["inode"]]
    need(live["file_sha"]==key and live["fd_inode"]==expect,"different opened library")
    if info["build_id"] is None:
        need(live["mapped_build_id"] is None,"invented live build ID")
    else:
        need(live["mapped_build_id"][1]==info["build_id"]["hex"],"different live build ID")
    actual=live["segments"]
    original=info["exec_loads"]
    need(0<len(actual)==len(original) and sorted((s["segment"] for s in actual),key=lambda x:x["offset"])==
         sorted(original,key=lambda x:x["offset"]),"did not verify every original executable load")
    bias=set()
    for row in actual:
        seg=row["segment"]
        need(row["prot"]&4 and not row["prot"]&2 and row["actual_rx_sha256"]==seg["sha256"]
             and row["file_sha"]==key and row["fd_inode"]==expect and row["address"]>=seg["vaddr"]
             and row["returned_address"]<=row["address"] and row["address"]+seg["size"]<=row["returned_address"]+row["length"],
             "different actual executing bytes or mmap identity")
        bias.add(row["address"]-seg["vaddr"])
    need(len(bias)==1,"inconsistent library load bias")
    return bias.pop()

def check_physical(logs):
    contacts=json.loads((logs/"physical-contact.json").read_bytes())
    need(set(contacts)=={"P-line","P-full","C-line","C-full"},"incomplete actual source-built GDB contact")
    spec={}
    for key,row in contacts.items():
        role,level=key.split("-")
        inp=json.loads((logs/("physical-"+key)/"input.json").read_bytes())
        observed=json.loads((logs/("physical-"+key)/"observed.json").read_bytes())
        need(sha(logs/("physical-"+key)/"observed.json")==row["trace"] and observed["exit"]==0 and
             row["hits"]==observed["hits"] and all(row["hits"][k]>0 for k in ("factory","manager","coalescer")) and
             ((row["hits"].get("ldv",0)>0)==(key=="C-line")),"wrong executing physical pass")
        obj=logs/("physical-"+key)/"probe.o"
        need(sha(obj)==row["object"] and obj.stat().st_size==row["bytes"] and obj.read_bytes().startswith(b"\x7fELF"),
             "different complete physical codegen output")
        fields = {k: inp[k]["sha256"] for k in ("frontend","driver","llvm")}
        need(fields==spec.setdefault(role,fields),"role changed between positive and negative")
        for k in ("driver","llvm"):
            live=observed["loader_fds"][k]
            base=live_input(live,inp[k])
            if k=="driver":
                need(observed["loaded_bias"]==base and all(
                    [v["name"],base+v["value"],v["value"]]==observed["addresses"][n]
                    for n,v in inp["symbols"].items()),"unbound machine function address")
    need(all(contacts["P-"+k]["object"]==contacts["C-"+k]["object"] for k in ("line","full")) and
         spec["P"]["driver"]!=spec["C"]["driver"] and spec["P"]["llvm"]==spec["C"]["llvm"],"source-built physical control differs")
    return spec


def install(root):
    fixed=json.loads((HERE/"worker.json").read_bytes())["contact"]
    run_identity(fixed["run"],fixed["qa"])
    factory(root,"parked")
    logs=root/"source-receipts"
    (root/"logs").rename(logs)
    rows=fetch(f"runs/{fixed['run']}/artifacts?per_page=100")["artifacts"]
    row=artifact(rows,"ldv-preexisting-source-contact")
    need([row["id"],row["digest"],row["size_in_bytes"]]==fixed["artifact"],"different source contact artifact")
    archive=root/"actual-contact.zip"
    proof=acquire(row,archive,4<<20)
    with zipfile.ZipFile(archive) as z:
        need(len(z.namelist())==len(set(z.namelist())) and z.testzip() is None,"invalid actual contact originals")
        need(json.loads(z.read("original-source.json"))==json.loads((logs/"original-source.json").read_bytes()),
             "contact observer used a different physical factory")
        for key in ("P-line","P-full","C-line","C-full"):
            prefix="physical-"+key
            (logs/prefix).mkdir()
            for n in ("input.json","observed.json","probe.o"):
                unzip_member(z,prefix+"/"+n,logs/prefix/n,1<<20)
        unzip_member(z,"physical-contact.json",logs/"physical-contact.json",1<<20)
    physical=check_physical(logs)
    manifests=capsule.admit(root/"capsule")
    for r,role in (("P","normal"),("C","defer")):
        m=manifests[r]; llvm=llvm_name(root/"parked"/role,m)
        driver,=[n for n in m if n.startswith("lib/librustc_driver-")]
        need([m[n][0] for n in ("bin/rustc",driver,llvm)]==
             [physical[r][k] for k in ("frontend","driver","llvm")],"wrong source-built SDK or LLVM")
    save(root/"source-qualification.json",{"build":BUILD,"build_qa":BUILD_QA,"source":capsule.REG["roles"],
         "physical":physical,"contact":fixed,"proof":proof,"tar_sha":ARCHIVE,"qualified":sha(root/"capsule/qualified.json"),
         "receipt_hashes":{str(p.relative_to(logs)):sha(p) for p in logs.rglob("*") if p.is_file()},"confirmation":CONFIRM})


if __name__=="__main__":
    root=Path(sys.argv[1])
    install(root)
    if len(sys.argv)==3:
        need(sys.argv[2]=="--matched-rustdoc","unknown source enrollment")
        import doc_support
        doc_support.install(root)
    else:
        need(len(sys.argv)==2,"unexpected source enrollment arguments")
