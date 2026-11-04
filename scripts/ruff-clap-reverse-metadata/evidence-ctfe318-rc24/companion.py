"""Seal or replay the genuine Unicode edit, its full captured rmeta and the independent CTFE pointer controls."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "evidence-signed-allocation-identity/helpers"))
import extract_alloc as a
import reverse_graph as g

def sha(data):
    return hashlib.sha256(data).hexdigest()

def archive(root, output):
    with zipfile.ZipFile(output, "x") as z:
        def put(name, raw):
            if name in z.NameToInfo:
                assert z.read(name) == raw
                return
            info = zipfile.ZipInfo(name, (1980,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info,raw)
        put("enrolled.json",(root/"alias-holdout/enrolled.json").read_bytes())
        for role in ("signed","parent","ctfe318"):
            folder = root/"alias-metadata"/role
            put(role+"/metadata-verdict.json",(folder/"verdict.json").read_bytes())
            for phase in ("old","edit","warm","empty","empty-again"):
                stage=folder/phase
                for name in ("result.json","downstream-typed.txt","crate-info.txt"):
                    put(role+"/"+phase+"/"+name,(stage/name).read_bytes())
                meta,=stage.glob("*.rmeta")
                info=json.loads((stage/"result.json").read_bytes())
                raw=meta.read_bytes()
                assert len(raw)==info["stat"] and sha(raw)==info["metadata"]
                put("rmeta/"+info["metadata"],raw)
        put("reported-allocation-differences.json",(root/"alias-metadata/allocation-difference.json").read_bytes())
        native=root/"ctfe-alias-native/ctfe318"
        put("native/alias_reader.rs",(native/"alias_reader.rs").read_bytes())
        put("native/checked.json",(native/"checked.json").read_bytes())
        for phase in ("cold-old","edited","unchanged","empty-new"):
            stage=native/phase
            data=(stage/"verdict.json").read_bytes()
            info=json.loads(data)
            binary=(stage/"reader").read_bytes()
            assert sha(binary)==info["elf"] and binary[:4]==b"\x7fELF"
            put("native/"+phase+".json",data)
            put("elf/"+info["elf"],binary)
        put("pointer/fixture.py",(root/"public_pointer_ctfe_guard.py").read_bytes())
        put("pointer/result.json",(root/"public-pointer-ctfe-guard/ctfe318/result.json").read_bytes())

def allocations(raw,version):
    info={}
    a.ns["decode"](raw,g.symbols,g.tables,"unicode_names2",version,typed=info)
    count,index=info["interpret_alloc_index"]
    r=g.md.Reader(raw,g.symbols)
    r.pos=index
    offsets=[r.var() for _ in range(count)]
    assert 0<count<600 and sorted(set(offsets))==offsets and offsets[-1]<index
    assert b"".join(a.scope["encode"](off) for off in offsets)==raw[index:r.pos]
    total=0
    labels={"BS":0,"GS":0}
    for start,end in zip(offsets,offsets[1:]+[index]):
        record=raw[start:end]
        if record[0]==0:
            decoded=a.scope["unpack"](record)
            assert a.scope["pack"](decoded,range(count))==record
            total+=len(decoded[1])
            tag=a.literal(record)
            if tag in labels:
                labels[tag]+=1
    return {"count":count,"observed_provenance_edges":total,"matched_memory_labels":labels}

def inspect(packet, run):
    with packet.open("rb") as stream:
        assert hashlib.file_digest(stream,"sha256").hexdigest()=="e7636b69c9013d69ea7062aae0f8e0e3435b74cb14fa50e7950850d608cf53c1"
    with zipfile.ZipFile(packet) as z:
        read=lambda name:json.loads(z.read(name))
        enrolled=read("enrolled.json")
        assert [enrolled[k] for k in ("old","new")]==["26911caa2800758779965510d2f222b438abbb38","276832aa91f2086a6ec880884fcdd987991cddf2"]
        results={}
        for role in ("signed","parent","ctfe318"):
            phases={}
            for phase in ("old","edit","warm","empty","empty-again"):
                data=read(role+"/"+phase+"/result.json")
                raw=z.read("rmeta/"+data["metadata"])
                assert len(raw)==data["stat"] and sha(raw)==data["metadata"]
                assert data["revision"]==enrolled["old" if phase=="old" else "new"]
                assert sha(z.read(role+"/"+phase+"/downstream-typed.txt"))==data["downstream"]
                assert sha(z.read(role+"/"+phase+"/crate-info.txt"))==data["inspection"]
                version=data["compiler"].splitlines()[0]+" (Ohm metadata 3)"
                phases[phase]={"metadata":data["metadata"],"bytes":len(raw),"nonfresh_cargo_units":len(data["dirty"]),
                               "typed":data["downstream"],"allocation":allocations(raw,version)}
            edit,empty=phases["edit"],phases["empty"]
            assert [v["nonfresh_cargo_units"] for v in phases.values()]==[20,3,0,20,20]
            assert phases["warm"]==edit|{"nonfresh_cargo_units":0} and phases["empty-again"]==empty
            assert edit["typed"]==empty["typed"]
            if role=="ctfe318":
                assert edit["metadata"]==empty["metadata"] and edit["allocation"]==empty["allocation"]
            else:
                assert edit["bytes"]==empty["bytes"]+26 and edit["allocation"]["count"]==empty["allocation"]["count"]+2
                assert edit["allocation"]["matched_memory_labels"]=={"BS":2,"GS":2} and empty["allocation"]["matched_memory_labels"]=={"BS":1,"GS":1}
            results[role]=phases
        binaries={}
        for phase in ("cold-old","edited","unchanged","empty-new"):
            data=read("native/"+phase+".json")
            blob=z.read("elf/"+data["elf"])
            assert sha(blob)==data["elf"] and data["native"]==enrolled[("old" if phase=="cold-old" else "new")+"_stdout"]
            if run:
                with tempfile.TemporaryDirectory() as tmp:
                    p=Path(tmp)/"unicode-observer";p.write_bytes(blob);p.chmod(0o700)
                    assert subprocess.check_output([p],cwd=tmp,env={"LC_ALL":"C"},timeout=5)==data["native"].encode()
            binaries[phase]=data["elf"]
        assert binaries["edited"]==binaries["empty-new"]==binaries["unchanged"]!=binaries["cold-old"]
        q=read("pointer/result.json")
        assert "93bf5c0a94d75e39c45fc3009da2c239bb5976af" in q["rustc"]
        rows=q["records"]
        assert [v["label"] for v in rows]==["shared","distinct","offset","aligned","mutable","separate-promotions","invalid","repaired"]
        assert rows[6]["attempts"]==[{"codes":["E0308"],"status":101}]*2
        for row in rows[:6]+rows[7:]:
            for name in ("output","elf","public_hash"):
                assert row["edit"][name]==row["settled"][name]==row["empty"][name]
        assert len({row["edit"]["public_hash"] for row in rows[:5]})==5
        probe=z.read("pointer/fixture.py")
        assert b"const NAMED:" in probe and b"assert_eq!(PROMOTED_VALUE, None)" in probe
        return {"metadata":results,"native_programs":binaries,"compile_time_pointer_fixture_sha256":sha(probe),
                "pointer_outcomes":[v["edit"]["output"] for v in rows if "edit" in v]}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--from-root",type=Path,help="original capture directory, to produce a new packet")
    parser.add_argument("--packet",type=Path,default=here/"unicode-and-pointer.zip")
    parser.add_argument("--run-native",action="store_true",help="execute both verified small Linux x86_64 programs")
    opts=parser.parse_args()
    if opts.from_root:archive(opts.from_root,opts.packet)
    print(json.dumps(inspect(opts.packet,opts.run_native),indent=1,sort_keys=True))
