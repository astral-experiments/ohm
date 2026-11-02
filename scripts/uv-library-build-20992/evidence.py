"""Retain native rlib originals losslessly and compare the exact registered source/cache oracles."""
from pathlib import Path
import gzip
import json
import os
import struct
import subprocess
import tempfile
import archive_wire as wire
import native
import verified_meta as meta

def packed(path):return gzip.decompress(path.read_bytes())
def keep(where,raw,base=None):
    h=wire.ident(raw);archive=native.ROOT/"blobs";archive.mkdir(exist_ok=True)
    rel=lambda p:str(p.relative_to(native.ROOT))
    if base is None or len(base[0])!=len(raw):
        out=archive/(h+".gz")
        if not out.exists():out.write_bytes(gzip.compress(raw,compresslevel=1,mtime=0))
        assert packed(out)==raw;return dict(sha256=h,bytes=len(raw),full=rel(out))
    first,witness=base
    if first==raw:return witness
    assert witness.get("full") and wire.ident(first)==witness["sha256"]
    patches=bytearray()
    for off in range(0,len(raw),1024):
        field=raw[off:off+1024]
        if field!=first[off:off+1024]:
            patches.extend(struct.pack("<IH",off,len(field)));patches.extend(field)
    out=archive/(witness["sha256"]+"-"+h+".blocks.gz")
    if not out.exists():out.write_bytes(gzip.compress(patches,compresslevel=1,mtime=0))
    item=dict(sha256=h,bytes=len(raw),base=witness,blocks=rel(out));assert unpack(item)==raw
    return item
def unpack(item):
    if "full"in item:data=packed(native.ROOT/item["full"])
    else:
        data=bytearray(unpack(item["base"]));p=packed(native.ROOT/item["blocks"]);pos=0;last=0
        while pos<len(p):
            offset,n=struct.unpack_from("<IH",p,pos);pos+=6;assert offset>=last and n in range(1,1025) and offset+n<=len(data) and pos+n<=len(p);data[offset:offset+n]=p[pos:pos+n];last=offset+n;pos+=n
        data=bytes(data)
    assert len(data)==item["bytes"] and wire.ident(data)==item["sha256"];return data
def capture(where,anchor=None):
    products=native.inventory();keys=native.selected(products);archives={}
    for n in ("uv_cli","uv_python"):
        raw=(native.TARGET/keys[n]).read_bytes();base=None
        if anchor:
            b=anchor["archives"][n];base=(unpack(b),b)
        archives[n]=keep(where,raw,base)
    receipt=dict(products=products,selected=keys,archives=archives)
    native.save(where/"native-products.json",receipt);return receipt
def compare(left,right,state,independent=False):
    assert left["selected"]==right["selected"] and left["products"].keys()==right["products"].keys()
    source=left["selected"];allowed={"uv_python"} if state=="A" else {"uv_python","uv_cli","uv_cli_alias"}
    changed=sorted(k for k in left["products"]if left["products"][k]!=right["products"][k])
    if not independent:assert set(changed)<={source[n]for n in allowed},changed
    else:
        assert all(left["products"][k]==right["products"][k] for k in left["products"] if k.endswith((".public-hash",".public-api-hash")))
    reports={}
    for n in ("uv_python","uv_cli"):
        a,b=unpack(left["archives"][n]),unpack(right["archives"][n]);crate=Path(source[n]).name[3:-5];required=wire.compare(a,a,crate)["object_files"]
        try:reports[n]=dict(full_natural_wire=wire.compare(a,b,crate,required))
        except ValueError:
            if not independent:raise
            o,ad,_=meta.metadata_member(a);p,bd,_=meta.metadata_member(b);assert o==p and len(ad)==len(bd)and ad!=bd
            proof=meta.semantic(ad,bd,n);base=bytearray(a);base[o:o+len(ad)]=bd
            reports[n]=dict(typed_metadata=proof,complete_archive=wire.compare(bytes(base),b,crate,required))
    return {"source_state":state,"across_independent_cold_seeds":independent,"all_products":len(left["products"]),"different":changed,"archives":reports}
def hostile(anchor):
    records={}
    for name,entry in anchor["archives"].items():
        raw=unpack(entry);crate=Path(anchor["selected"][name]).name[3:-5];rows=wire.archive(raw);by={n:(pos,data)for n,pos,data,_,_ in rows}
        ob=next(r for r in rows if r[0].endswith(".rcgu.o"));assert type(ob[4])is int
        lk,=(k for k in by if k.endswith(".rmeta-link"));ofs,data=by[lk]
        npos=data.index(ob[0].encode())
        positions={"native-object":ob[1]+19,"symbol-table":rows[0][1]+len(rows[0][2])-9,"metadata":by["lib.rmeta"][0]+80,"link-reference":ofs+npos+3,"archive-order":ob[1]-30,"name-table":ob[4]+3}
        for label,offset in positions.items():
            altered=bytearray(raw);altered[offset]^=1
            try:wire.compare(raw,bytes(altered),crate)
            except (ValueError,AssertionError,IndexError,KeyError) as error:records[name+"/"+label]=[offset,type(error).__name__]
            else:raise ValueError("accepted damaged "+name+"/"+label)
    return records


