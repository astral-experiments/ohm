"""Challenge the name/ELF/symbol association using the real previously refused parent artifact."""
import argparse
import collections
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from member_names import digest, native_identity, read_names, require

ORIGINAL = "6e457c485f048d27db1011d76534b7657d4aea29aba82ed6bd47346f4fa4e697"


def original(path, dest):
    with path.open("rb") as source:
        require(hashlib.file_digest(source, "sha256").hexdigest() == ORIGINAL, "wrong original")
    with zipfile.ZipFile(path) as source:
        info = json.loads(source.read("P/edit/native.json"))["outputs"]["ty_ide"]["rlib"]
        with dest.open("xb") as out, subprocess.Popen(["zstd", "-qdc"], stdin=subprocess.PIPE, stdout=out) as unpack:
            with unpack.stdin, source.open("native/"+info["sha256"]+".zst") as arm:
                shutil.copyfileobj(arm, unpack.stdin)
            require(unpack.wait() == 0, "invalid compressed archive")
    raw = dest.read_bytes()
    require(len(raw)==info["bytes"] and digest(raw)==info["sha256"], "changed original rlib")
    return raw


def controls(source, work):
    with tempfile.TemporaryDirectory(dir=work) as td:
        rlib = Path(td)/"source.rlib"
        raw = original(source, rlib)
        report = read_names(rlib, "ty_ide")
        fields = {}
        offsets = {}
        pos = 8
        while pos < len(raw):
            header = raw[pos:pos+60]
            field = header[:16].strip()
            n = int(header[48:58])
            start = pos + 60
            if field in (b"/",b"//",b"lib.rmeta-link/"):
                fields[field]=(start,n)
            elif field.startswith(b"/"):
                tab, bound = fields[b"//"]
                begin = tab + int(field[1:])
                end = raw.index(b"/\n",begin,tab+bound)
                offsets[raw[begin:end].decode()] = (pos,start,n)
            pos=start+n+(n%2)
        by_width = collections.defaultdict(list)
        for row in report["members"]:
            by_width[row[4]].append(row)
        pair = next((a,b) for group in by_width.values() for a in group for b in group if a[3]!=b[3])
        a,b=pair
        _,x,size = offsets[a[0]]
        _,y,other_size = offsets[b[0]]
        require(size==other_size, "equal-sized swap")
        bad=Path(td)/"mutated.rlib"
        changed = bytearray(raw)
        changed[x:x+size],changed[y:y+size] = raw[y:y+size],raw[x:x+size]
        bad.write_bytes(changed)
        swapped=read_names(bad,"ty_ide")
        require(sorted(m[3:] for m in swapped["members"])==sorted(m[3:] for m in report["members"]), "body multiset changed under swap")
        require(native_identity(swapped)!=native_identity(report), "swapped members falsely accepted")
        changed=bytearray(raw)
        s,_=fields[b"/"]
        first=int.from_bytes(raw[s+4:s+8],"big")
        replacement=next(v[0]for v in offsets.values()if v[0]!=first)
        changed[s+4:s+8]=replacement.to_bytes(4,"big")
        bad.write_bytes(changed)
        retargeted=read_names(bad,"ty_ide")
        require(retargeted["members"]==report["members"] and retargeted["symbol_map"]!=report["symbol_map"], "symbol retarget falsely accepted")
        changed=bytearray(raw)
        s,n=fields[b"//"]
        x=raw.index(a[0].encode()+b"/\n",s,s+n)
        changed[x:x+len(a[0])] = b[0].encode()
        bad.write_bytes(changed)
        try:
            read_names(bad,"ty_ide")
        except ValueError as error:
            require(str(error)=="ambiguous canonical CGU", "wrong duplicate rejection")
        else:
            raise ValueError("duplicate canonical member accepted")
        changed=bytearray(raw)
        s,n=fields[b"lib.rmeta-link/"]
        x=raw.index(a[0].encode(),s,s+n)
        changed[x:x+len(a[0])]=b[0].encode()
        bad.write_bytes(changed)
        try:
            read_names(bad,"ty_ide")
        except ValueError as error:
            require(str(error)=="unbound link-wrapper member", "wrong late metadata rejection")
        else:
            raise ValueError("retargeted link metadata accepted")
        return {"source_archive":ORIGINAL, "parent_rlib":digest(raw), "swapped_names":[a[0],b[0]],
                "native_bodies":len(report["members"]), "symbol_rows":report["symbols"],
                "body_swap_failed_named_equality":True, "ranlib_retarget_changed_symbol_digest":True,
                "duplicate_member_refused":True, "unbound_link_wrapper_refused":True}


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("original",type=Path)
    ap.add_argument("--work",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=controls(args.original,args.work)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
