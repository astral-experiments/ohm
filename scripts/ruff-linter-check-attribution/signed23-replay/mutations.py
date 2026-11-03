"""Require raw-ledger corruption test cases to be rejected independently of transport SHA."""
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import reopen

class Override:
    def __init__(self, data, name, replacement):
        self.data, self.name, self.replacement = data, name, replacement
    def read(self, name):
        return self.replacement if name==self.name else self.data.read(name)

def cases(z):
    ids=json.loads(z.read("owner-inputs.json"))
    p="events-edited"
    base=reopen.native(z,p,ids)
    first,second=sorted(base["physical"].values(),key=lambda d:d["serial"])[:2]
    sample=z.read(p+"/samples.tsv").decode().splitlines()
    at=next(i for i,v in enumerate(sample) if int(v.split()[0])==first["serial"])
    r=sample[at].split("\t")
    r[-1]=str(int(r[-2])-1)
    masked=sample[:];masked[at]="\t".join(r)
    table=z.read(p+"/tasks.tsv").decode().splitlines()
    at=next(i for i,v in enumerate(table) if v.startswith("spawn\t") and int(v.split()[2])==second["pid"])
    row=table[at].split("\t");row[1]=str(first["pid"])
    nested=table[:];nested[at]="\t".join(row)
    arg=p+f"/args-{first['serial']:04d}"
    attrs=bytearray(z.read(p+"/subtree-attr.bin"));attrs[40]^=32
    half=sample[:];half.pop(next(i for i,v in enumerate(half) if int(v.split()[0])==second["serial"]))
    trials=[
        ("multiplexed counter",p+"/samples.tsv",("\n".join(masked)+"\n").encode()),
        ("absent compiler counter",p+"/samples.tsv",("\n".join(half)+"\n").encode()),
        ("nested measured owners",p+"/tasks.tsv",("\n".join(nested)+"\n").encode()),
        ("kernel-mode instructions",p+"/subtree-attr.bin",attrs),
        ("changed true compiler flag",arg,z.read(arg)+b"--cfg\0unregistered\0"),
        ("wrong typed Cargo completion","release23/edited/stdout",z.read("release23/edited/stdout").replace(b'"success":true',b'"success":false')),
    ]
    for label,name,body in trials:
        try:
            reopen.native(Override(z,name,body),p,ids)
        except (ValueError,AssertionError,KeyError):
            continue
        raise AssertionError("accepted corrupt evidence: "+label)
    return [label for label,_,_ in trials]

if __name__=="__main__":
    with zipfile.ZipFile(sys.argv[1]) as z:
        for label in cases(z):
            print("rejected",label)
