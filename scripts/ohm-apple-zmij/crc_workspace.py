"""Count which of the previous 60 Ruff test executables still relink with register-only CRC."""
import argparse
import gzip
import json
from pathlib import Path
import zipfile

from dyld import check as check_dyld
from measure import select
from study import CHILD, PARENT, digest, load, need, save, sha
from ty_compare import run_pair_workspace
from ty_links import A, B, CensusTrace, enrolled
from prepare import prepare_ruff

PRIOR="2e1ea0d11155bc8c76fe3837b4fb0b3083825450d903d40bcc15d9b1cac9caf5"
ENDPOINTS=("edit","repeat-1","repeat-2")


def previous(archive):
    need(sha(archive)==PRIOR,"wrong prior workspace artifact")
    result={}
    with zipfile.ZipFile(archive) as z:
        need(z.testzip() is None,"damaged workspace evidence")
        for phase in ENDPOINTS:
            prefix=f"C/visit/{phase}/"
            row=json.loads(z.read(prefix+"verified.json"))
            streams={key:gzip.decompress(z.read(prefix+name+".gz")) for key,name in
                     (("native_events","exec.json"),("stdout","stdout"),("stderr","stderr"))}
            need({k:digest(v) for k,v in streams.items()}==row["streams"],"prior raw NUL-independent stream mismatch")
            msgs=list(map(json.loads,streams["stdout"].splitlines()))
            need(msgs[-1]=={"reason":"build-finished","success":True} and row["exit"]==0,"wrong prior verdict")
            tests={m["executable"] for m in msgs if m.get("executable") and m["profile"]["test"]}
            execs=json.loads(streams["native_events"])
            crates=[m["argv"][m["argv"].index("--crate-name")+1] for m in execs
                    if m["path"].endswith("/bin/rustc") and "--crate-name" in m["argv"] and
                    m["argv"][m["argv"].index("--crate-name")+1]!="___"]
            linked=[arg for m in execs if m["path"].endswith("/XcodeDefault.xctoolchain/usr/bin/ld")
                    for flag,arg in zip(m["argv"],m["argv"][1:]) if flag=="-o"]
            hits=sorted(row["binary_roster"][path]["unit"] for path in tests.intersection(linked))
            need(len(tests)==83 and len(hits)==60 and len(linked)==66 and len(crates)==(74 if phase=="edit" else 72)
                 and crates.count("zlib_rs")==2,"prior ground truth changed")
            result[phase]={"rustc":sorted(crates),"all_ld":len(linked),"linked_tests":hits}
    return result


def census(root):
    receipt=load(root/"receipts/enrolled-workspace.json")
    need(receipt["compiler"]==[PARENT,CHILD] and receipt["ruff"]==[A,B] and receipt["prior_sha256"]==PRIOR,
         "different source enrollment")
    top=root/"receipts/ty-comparison/workspace"
    for role in "PC":
        check_dyld(root,role,select(root,role),root/"receipts"/"workspace-dyld"/role)
    trace=CensusTrace()
    try:
        trace.ready()
        run_pair_workspace(root,trace)
    finally:
        trace.close()
    arms=load(top/"paired-physical.json")
    outcome={}
    for phase in ENDPOINTS:
        p,c=(arms[role][phase] for role in "PC")
        prior=receipt["prior"][phase]
        need(sorted(p["physical_rustcs"])==prior["rustc"] and p["all_linkers"]==prior["all_ld"]
             and sorted(p["linked_tests"])==prior["linked_tests"],"parent differs from independent prior workspace")
        ids=lambda row:{(pkg,name,tuple(kind)) for pkg,name,kind in row["linked_tests"]}
        outcome[phase]={"tests_total":p["test_count"],"rustcs":[len(v["physical_rustcs"]) for v in (p,c)],
                        "zlib_rustcs":[v["physical_rustcs"].count("zlib_rs") for v in (p,c)],
                        "all_links":[v["all_linkers"] for v in (p,c)],"test_links":[len(ids(v)) for v in (p,c)],
                        "saved":sorted(ids(p)-ids(c)),"added":sorted(ids(c)-ids(p))}
    save(root/"receipts/crc-workspace-result.json",outcome)
    print(json.dumps(outcome,sort_keys=True),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("seed","run"));parser.add_argument("root",type=Path)
    args=parser.parse_args();root=args.root.resolve(strict=True)
    if args.mode=="seed":
        data=previous(root/"prior-workspace.zip")
        save(root/"receipts/enrolled-workspace.json",{"ruff":[A,B],"compiler":[PARENT,CHILD],"prior":data,"prior_sha256":PRIOR})
        prepare_ruff(root,A,B,enrolled)
    else:
        census(root)
