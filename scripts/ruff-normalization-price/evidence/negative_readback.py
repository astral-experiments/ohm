"""Mutate actual acquisition bytes in memory, without changing the original archive."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("tools",type=Path)
    parser.add_argument("original",type=Path)
    parser.add_argument("out",type=Path)
    arg=parser.parse_args()
    sys.path.insert(0,str(arg.tools.resolve()))
    from records import file_hash, from_counter, load, overflow, physical
    plan=load(arg.tools/"registration.json")
    refused={}
    def veto(tag,fn):
        try:fn()
        except (AssertionError,ValueError,IndexError) as e:refused[tag]=type(e).__name__
        else:raise ValueError("unexpected admission: "+tag)
    with zipfile.ZipFile(arg.original) as z:
        for role in ("C5","C7"):
            prefix=role+"/check/observed-edit/"
            installed=json.loads(z.read("installed-"+role+".json"))
            def original(n):return z.read(prefix+"tasks/"+n)
            baseline=physical(original,installed,"0.1.25",True)
            owner,=[r for r in baseline["all"] if r["name"]=="unicode_normalization"]
            argv_path=f'{owner["image"]:05}.nul'
            def alternative(name,old,new):
                def read(p):
                    data=original(p)
                    if p==name:
                        assert old in data
                        data=data.replace(old,new,1)
                    return data
                return read
            veto(role+"-wrong-registry-version",lambda:physical(alternative(argv_path,b"/unicode-normalization-0.1.25/src/lib.rs",b"/unicode-normalization-0.1.24/src/lib.rs"),installed,"0.1.25",True))
            veto(role+"-wrong-owner-pid",lambda:physical(alternative(argv_path,str(owner["pid"]).encode()+b"\0",b"999999999\0"),installed,"0.1.25",True))
            raw=json.loads(z.read(role+"/check/ordinary-edit/hardware.json"))
            assert from_counter(raw)>0
            veto(role+"-multiplexed-whole",lambda:from_counter(dict(raw,running=raw["enabled"]-1)))
            invalid=[json.loads(row)for row in z.read(role+"/build/invalid/cargo.jsonl").splitlines()]
            overflow(invalid,plan["invalid"])
            for e in invalid:
                if e.get("reason")=="compiler-message" and e["message"]["level"]=="error":
                    for p in e["message"]["spans"]:
                        if p["is_primary"]:p["byte_end"]+=1
            veto(role+"-wrong-primary-span",lambda:overflow(invalid,plan["invalid"]))
        row=json.loads(z.read("binding.json"))
    arg.out.write_text(json.dumps({"archive_sha256":file_hash(arg.original),"source":row["head"],"rejected":refused},indent=2)+"\n")
    print("Rejected",len(refused),"mutations of original records")
if __name__=="__main__":main()
