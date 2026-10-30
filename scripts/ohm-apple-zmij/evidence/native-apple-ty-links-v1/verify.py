"""Replay every Cargo and kernel execution stream offline and compare the actual test binaries."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from project import PLANS
from read_links import command, file_hash


class Trace:
    def __init__(self, path):
        self.data = {}
        with tarfile.open(path,"r|xz") as tf:
            for m in tf:
                assert m.isfile() and m.name not in self.data
                self.data[m.name] = tf.extractfile(m).read()

    def read(self, key):
        return self.data[key]


def read(kind):
    stream = Trace(HERE/(kind+".tar.xz"))
    manifest = json.loads(stream.read("MANIFEST.json"))
    assert manifest["kind"]==kind and tuple(manifest[x] for x in ("run","artifact","original_zip_sha256"))==PLANS[kind]
    assert dict(manifest["files"])=={k:hashlib.sha256(b).hexdigest() for k,b in stream.data.items() if k!="MANIFEST.json"}
    prefixes = manifest["command_dirs"]
    assert len(prefixes)==len(set(prefixes))
    rows = {}
    for prefix in prefixes:
        row = json.loads(stream.read(prefix+"verified.json"))
        rows[prefix.rstrip("/")] = command(stream,prefix,row,decoded=True)
    return rows, stream


def identity(row):
    return {k:(v["bytes"],v["sha256"]) for k,v in row["test_executables"].items()}


def focused(rows, base, role):
    refs = {state:rows[base+"/empty-"+state+"/clean"] for state in ("old","new")}
    assert refs["old"]["e2e"]["tests"]==194 and refs["new"]["e2e"]["tests"]==195
    assert identity(refs["old"])!=identity(refs["new"])
    for phase in ("cold","edit","repeat-1","repeat-2","invalid","repair"):
        row = rows[base+"/visit/"+phase]
        if phase=="invalid":
            assert row["state"]=="bad" and row["all_linkers"]==0 and row["e2e"] is None
            continue
        ref = refs[row["state"]]
        assert identity(row)==identity(ref) and row["e2e"]["text"]==ref["e2e"]["text"]
        if phase in ("edit","repair"):
            assert row["e2e"]["links"]==row["all_linkers"]==1 and row["full"].count("e2e")==row["full"].count("ty_server")==1
        if phase.startswith("repeat"):
            assert row["full"]==([] if role=="C" else ["e2e","zmij"])
            assert row["all_linkers"]==row["e2e"]["links"]==int(role!="C") and row["link_only"]==[]
    return refs


def linked(row):
    return {k for k,info in row["test_executables"].items() if info["physical_links"]}


def workspace(signed, paired):
    cold = signed["cold"]
    assert len(cold["test_executables"])==83
    for pre in ("repeat-1","repeat-2"):
        row=signed[pre]
        assert identity(row)==identity(cold) and len(row["full"])==106 and row["all_linkers"]==99 and len(linked(row))==81
    assert linked(signed["repeat-1"])==linked(signed["repeat-2"])
    refs = {r:paired[r+"/empty-new/clean"] for r in ("P","C")}
    assert set(refs["P"]["test_executables"])==set(refs["C"]["test_executables"])==set(cold["test_executables"])
    for role,ref in refs.items():
        for phase in ("edit","repeat-1","repeat-2"):
            v=paired[role+"/visit/"+phase]
            assert identity(v)==identity(ref) and v["e2e"]["tests"]==195 and v["e2e"]["links"]==1
            if phase=="edit":
                assert v["e2e"]["links"]==1 and v["full"].count("ty_server")>=1
    reference_sets = tuple(linked(paired[r+"/visit/edit"]) for r in ("P","C"))
    for phase in ("edit","repeat-1","repeat-2"):
        p,c=[paired[r+"/visit/"+phase] for r in ("P","C")]
        before,after=linked(p),linked(c)
        assert (before,after)==reference_sets and len(before)==81 and len(after)==60
        assert after<=before and len(before-after)==21
        assert (p["all_linkers"],c["all_linkers"])==(99,66) and p["link_only"]==c["link_only"]==[]
        assert (len(p["full"]),len(c["full"]))==((108,74) if phase=="edit" else (106,72))
        assert p["full"].count("ron")==c["full"].count("ron")==1
        assert (p["full"].count("zmij"),c["full"].count("zmij"))==(1,0)
        print(phase, "test executables linked:",len(before),"->",len(after),"/ 83",
              "all rustc:",len(p["full"]),"->",len(c["full"]),"all linkers:",p["all_linkers"],"->",c["all_linkers"])


def native_refs(original, stored):
    from macho_paths import compare
    assert file_hash(original)==PLANS["paired-focus"][2]
    with zipfile.ZipFile(original) as z:
        for state in ("old","new"):
            arms = {}
            for role in ("P","C"):
                key="ty-comparison/"+role+"/focus/empty-"+state+"/clean/verified.json"
                row=json.loads(z.read(key))
                path, = row["binary_roster"]
                ref=row["e2e"]["raw"]
                binary=gzip.decompress(z.read("clean-ty-executables/"+ref+".macho.gz"))
                assert hashlib.sha256(binary).hexdigest()==ref
                argv, = [v["argv"] for v in row["native"]["linkers"] if [b for a,b in zip(v["argv"],v["argv"][1:]) if a=="-o"]==[path]]
                arms[role]=binary,path,argv
            assert compare(arms)==json.loads(stored.read("ty-comparison/clean-equivalence-"+state+".json"))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--native-binaries",type=Path,help="Recheck all four complete clean Mach-O files from the original paired-focus ZIP")
    args=p.parse_args()
    s,_=read("signed-focus")
    focused(s,"ty-focus","S")
    pair,portable=read("paired-focus")
    for r in ("P","C"):
        refs=focused(pair,"ty-comparison/"+r+"/focus",r)
        for state,ref in refs.items():
            eq=json.loads(portable.read("ty-comparison/clean-equivalence-"+state+".json"))
            assert eq[r]["raw"]==ref["e2e"]["sha256"] and eq[r]["code_pages"]>0 and eq[r]["paths"]
    signed,_=read("signed-workspace")
    paired,_=read("paired-workspace")
    workspace(signed,paired)
    if args.native_binaries:
        native_refs(args.native_binaries,portable)
    print("Focused compilation, physical linker outputs, changed test inventory and real verdicts verified.")
