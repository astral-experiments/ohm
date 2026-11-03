"""Independent ordinary phase and physical PMU calibration checks."""
from collections import Counter
import hashlib
import json
import re
from statistics import median


def require(test, message):
    if not test:
        raise ValueError(message)


def serial_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def ordinary(z, stages):
    result={}
    for phase, s in stages.items():
        a=s["counts"].copy()
        nonce={}
        for item in s["counts"]:
            m=re.fullmatch(r"autocfg_([a-f0-9]{16})_([01])",item)
            if m:
                require(phase in ("old","clean") and a.pop(item)==1,"extra/foreign cold configuration probe")
                nonce.setdefault(m[1],[]).append(m[2])
        shape=sorted(sorted(suffixes) for suffixes in nonce.values())
        require(shape==([["0"],["0","1"]] if phase in ("old","clean") else []),"cold configuration probe multiplicities")
        got=json.loads(z.read("release23/"+phase+"/rustcs.json"))
        require(Counter(row["crate"] for row in got)==s["counts"],"physical compiler roster vs summary")
        outcome=json.loads(z.read("release23/"+phase+"/command.json"))
        require(outcome["exit"]==(101 if phase=="invalid" else 0),"native exit")
        result[phase]={"counts_sha":serial_hash(a),"literal_rustcs":len(got),"autocfg_probe_suffixes":shape,"diagnostics":s["diagnostics"]}
        if "inventory" in s:
            result[phase].update(typed_inventory_sha256=serial_hash(s["inventory"]),typed_units=len(s["inventory"]),
                                 output_names_sha256=serial_hash(sorted(s["workspace_rmeta"])),output_names=len(s["workspace_rmeta"]))
    bad=[json.loads(line) for line in z.read("release23/invalid/stdout").splitlines()]
    errors=[row["message"] for row in bad if row["reason"]=="compiler-message" and row["message"]["level"]=="error"]
    require(len(errors)==1 and errors[0]["code"]["code"]=="E0308" and any(span["file_name"].endswith("ruff_annotate_snippets/src/snippet.rs")
        and any('const _: () = "OHM_VISIBILITY_E0308";'==line["text"].strip() for line in span["text"]) for span in errors[0]["spans"]), "native source error")
    return result


def calibrations(z):
    prefix="calibration/"
    admitted=json.loads(z.read(prefix+"admitted.json"))
    # Terminal calibration must be reproducible directly from 28 CPU/clone/exec probes and eight separate fork trees.
    for i,(mode,copies) in enumerate((("0",1),("1",1),("2",1),("2",2),("exec",1),("thread",1),("thread",2))):
        samples=[]
        for j in range(4):
            r=json.loads(z.read(prefix+f"whole-{i}-{j}.json"))
            require(r["code"]==r["event_errno"]==0 and r["enabled"]==r["running"]>0 and r["instructions"]>0,"calibration sample")
            samples.append(r["instructions"])
        delta=median(samples[1::2])-median(samples[::2]);expect=2*copies*80_000_000
        require(abs(delta/expect-1)<.02 and admitted["whole28"][f"{i}-{mode}"]==[samples,delta,expect],"whole reference loop")
    for mode in ("plain","tree"):
        sequence=[]
        for j in range(4):
            pre=prefix+f"nested-{mode}-{j}/"
            ss=[list(map(int,line.split())) for line in z.read(pre+"samples.tsv").splitlines()]
            require(all(err==0 and size==24 and ir>0 and enabled==running>0 for _,_,_,err,size,ir,enabled,running in ss),"sample subtree calibration")
            counts={n:inst for n,_,_,_,_,inst,_,_ in ss};vals={"whole":counts[0]}
            for n,_,k,_,_,inst,_,_ in ss:
                if k:
                    argv=z.read(pre+f"args-{n:04d}").split(b"\0")[:-1]
                    identifier=argv[2].decode();role={1:"rustc",2:"cc",4:"wild"}[k]
                    vals[identifier+"/"+role+"_tree"]=inst
            if mode=="tree":
                for crate in ("alpha","beta"):
                    vals[crate+"/rustc-minus-cc"]=vals[crate+"/rustc_tree"]-vals[crate+"/cc_tree"]
                    vals[crate+"/cc-minus-wild"]=vals[crate+"/cc_tree"]-vals[crate+"/wild_tree"]
                vals["outside"]=vals["whole"]-vals["alpha/rustc_tree"]-vals["beta/rustc_tree"]
            sequence.append(vals)
        for name,record in admitted["nested"][mode].items():
            samples=[v[name] for v in sequence]
            expected=record["ideal"]
            diff=[samples[i]-median(samples[::2]) for i in (1,3)]
            require(samples==record["values"] and diff==record["delta"] and all(abs(a/b-1)<.02 for a,b in zip(diff,expected)),"calibrated "+name)
    return {"whole_loop_probes":28,"independent_fork_tree_probes":8,"admitted_sha256":hashlib.sha256(z.read(prefix+"admitted.json")).hexdigest()}
