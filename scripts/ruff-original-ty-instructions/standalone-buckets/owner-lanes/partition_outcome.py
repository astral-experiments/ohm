"""Join the actual predeclared source-owned lanes to two emitted native archives and their query records."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"residual/eligibility"))
import partitions
import selector

def need(condition,message):
    if not condition:raise ValueError(message)

class Archive:
    def __init__(self,path):
        self.file=zipfile.ZipFile(path);names=self.file.namelist()
        need(len(names)==len(set(names)) and all(not n.startswith("/") and ".."not in Path(n).parts for n in names),"unknown archive path")
    def js(self,name):return json.loads(self.file.read(name))
    def raw(self,meta,limit=110*2**20):
        name="native/"+meta["sha256"]+".zst"
        need(0<meta["bytes"]<limit and self.file.getinfo(name).file_size<limit,"oversized query or native object")
        data=subprocess.check_output(["zstd","-qdc"],input=self.file.read(name))
        need(len(data)==meta["bytes"] and hashlib.sha256(data).hexdigest()==meta["sha256"],"different native original")
        return data

def table(z,role,phase):
    info=z.js(role+"/"+phase+"/native.json")["ty_project"]
    meta=info["raw"]["query-cache.bin"];raw=z.raw(meta)
    need(raw[:4]==b"RSIC" and int.from_bytes(raw[4:6],"little")=={"P":24450,"C":48276}[role] and raw[-13:]==b"rust-end-file","unknown compiler file format")
    return partitions.table(raw,info,None,expected_count=len(info["objects"]))

def counts(table,names):
    rows=[table["rows"][n]for n in names]
    return {"units":len(rows),"mir":sum(r["size"]for r in rows),"memberships":sum(r["items"]for r in rows)}

def summarize(path,case):
    z=Archive(path);terminal=z.js("result.json");reg=z.js("registration.json")
    need(terminal["case"]==reg["case"]==case,"wrong source corpus")
    parsed={role:{phase:table(z,role,phase)for phase in ("old","edit")}for role in "PC"}
    result={}
    for phase in ("old","edit"):
        p,c=(parsed[k][phase]for k in "PC")
        chosen=selector.select(p);roots=chosen["selected"];capacity=min(8,chosen["per_root_lanes"])
        wanted={root:[selector.mangle(root+"-ohm-owner-"+str(i)) for i in range(capacity)]for root in roots}
        pnames,cnames=set(p["rows"]),set(c["rows"])
        removed=sorted(pnames-cnames);added=sorted(cnames-pnames)
        active={root:[n for n in lane if n in cnames]for root,lane in wanted.items()}
        if case=="29697":
            need(p["table_count"]==245 and c["table_count"]==251 and set(removed)==set(roots)
                 and all(len(s)==4 for s in active.values()) and set(added)=={n for s in active.values()for n in s},
                 ("frozen discovery root or lane population changed",phase,removed,added,wanted))
        sides={}
        for role,t,names in (("P",p,pnames),("C",c,cnames)):
            rr=z.js(role+"/edit-retention.json")["ty_project"];regen={n[:-2] for reason,row in rr.items()if reason in ("added","regenerated_equal","regenerated_changed")for n in row["names"]}
            sides[role]={"all":counts(t,names),"roots":{root:counts(t,([root]if role=="P" else active[root]))for root in roots},
                         "ordinary_edit_work":counts(t,names&regen) if phase=="edit"else None}
        result[phase]={"stock_choice":chosen,"removed":removed,"added":added,"present_lanes":active,"compilers":sides}
    result["physical"]={role:{**{k:v[k]for k in ("primary","cold","cold_new","noop","cgu_count","storage")},"edited_storage":z.js(role+"/edit-footprint.json"),
                              "native":{t:v["native"][t]["stdout"]for t in v["native"]}} for role,v in terminal["roles"].items()}
    result["primary_reduction"]=terminal["whole_reduction"]
    return result
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--case",choices=["29697","29604"],required=True);p.add_argument("archive",type=Path);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();a.output.write_text(json.dumps(summarize(a.archive,a.case),indent=2,sort_keys=True)+"\n")
