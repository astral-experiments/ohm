"""Compare the complete native references from the failed pilot without reading its counters."""
import collections
import gzip
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile

RUN = 41420224471
HEAD = "03f3a471a4726429278b13e670be339f78ffc5b5"
ZIP = (13129937931, 153866895, "8ee4f014f65c36530b407f3830eedc76c8de3871957c276dff76b6fb593257f5")
EXPECTED = {
    "A": {"P": "d17d9e3d10c8e001ef36a64ac9a4ab5f8145bc248198c4da828cf0fa59e34312",
          "C": "a58c557726bdb7586333b74993172c7d2062bb6748907151e7b352e28df4e0de"},
    "B": {"P": "6c4a3c84795695fee4c48a5cdaccfa94b5cd037d3a63252b776c694f271de76d",
          "C": "91a5bccd7fc01cbee01fe9ce94561ab7f0557efd7acd12d6036cef25dad86b55"},
}
ALLOWED = {".debug_str", ".debug_info", ".debug_macro", ".note.gnu.build-id"}
STRP = re.compile(rb"^\s*<([0-9a-f]+)>\s+DW_AT_\w+\s*:\s+\(strp\) \(offset: (0x[0-9a-f]+|0)\): ")

def need(ok, why):
    if not ok:
        raise ValueError(why)

def hexdigest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def struct_sections(data):
    need(data[:7] == b"\x7fELF\x02\x01\x01", "unrecognized reference ELF")
    h = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    off, size, count, index = h[5], *h[-3:]
    need(size == 64 and 0 < index < count and off + size * count <= len(data), "invalid section table")
    rows = [struct.unpack_from("<IIQQQQIIQQ", data, off+i*size) for i in range(count)]
    start, total = rows[index][4:6]
    strings = data[start:start+total]
    parts = {}
    for row in rows:
        name = strings[row[0]:].split(b"\0", 1)[0].decode()
        if name in ALLOWED:
            need(name not in parts and row[1] != 8 and 0 < row[4] < row[4]+row[5] <= len(data), "invalid debug section")
            parts[name] = (row[4], row[4]+row[5])
    need(parts.keys() == ALLOWED, "missing expected debug sections")
    return parts

def resolved_info(left, pinfo, cinfo, pstrings, cstrings, old, new):
    """Verify all changed physical bytes are actual DW_FORM_strp fields for equivalent strings."""
    rewritten = bytearray(pinfo)
    counts = dict(attributes=0, changed_offsets=0, directory_uses=0)
    argv = ["readelf", "--wide", "--debug-dump=info", "--debug-dump=no-follow-links", left]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, "LC_ALL":"C", "DEBUGINFOD_URLS":""})
    with proc:
        for line in proc.stdout:
            match = STRP.match(line)
            if not match:
                continue
            at, shown = int(match[1],16), int(match[2],0)
            before, = struct.unpack_from("<I", pinfo, at)
            after, = struct.unpack_from("<I", cinfo, at)
            need(before==shown and before<len(pstrings) and after<len(cstrings), "unexpected DWARF32 string reference")
            ptext=pstrings[before:pstrings.index(0,before)]
            ctext=cstrings[after:cstrings.index(0,after)]
            need(ptext==ctext or (ptext,ctext)==(old,new), ("different resolved DWARF attribute",at,ptext[:260],ctext[:260]))
            counts["attributes"]+=1
            counts["changed_offsets"]+=int(before!=after)
            counts["directory_uses"]+=int((ptext,ctext)==(old,new))
            struct.pack_into("<I",rewritten,at,after)
        errors=proc.stderr.read()
        need(proc.wait()==0 and not errors,("failed DWARF info reader",errors[:1000]))
    need(counts["attributes"]>1000 and counts["changed_offsets"]>0 and counts["directory_uses"]>0,"incomplete DWARF coverage")
    need(rewritten==cinfo,"non-string-reference DWARF info byte changed")
    counts["rewritten_sha256"]=hashlib.sha256(rewritten).hexdigest()
    return counts

def macro_dump(file, original):
    argv = ["readelf", "--wide", "--debug-dump=macro", "--debug-dump=no-follow-links", file]
    digest = hashlib.sha256()
    line_count = 0
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "LC_ALL":"C","DEBUGINFOD_URLS":""}) as p:
        for line in p.stdout:
            digest.update(line.replace(original, b"<jemalloc-build-directory>"))
            line_count += 1
        err=p.stderr.read()
        need(p.wait()==0 and not err,("failed DWARF macro reader",err[:1000]))
    need(line_count>1000,"incomplete macro records")
    return dict(lines=line_count,sha256=digest.hexdigest())

def compare(left, right, old, new):
    need(len(old)==len(new) and old!=new, "expected distinct equal-width Cargo directories")
    with left.open("rb") as lf, right.open("rb") as rf, mmap.mmap(lf.fileno(), 0, access=mmap.ACCESS_READ) as a, mmap.mmap(rf.fileno(),0,access=mmap.ACCESS_READ) as b:
        parts = struct_sections(a)
        need(len(a)==len(b) and parts==struct_sections(b), "different complete ELF layout")
        prev=0
        for start, stop in sorted(parts.values()):
            need(prev<=start and a[prev:start]==b[prev:start], "unexpected bytes outside permitted native debug sections")
            prev=stop
        need(a[prev:]==b[prev:], "unexpected trailing ELF bytes")
        lo,hi=parts[".debug_str"]
        ps,cs=a[lo:hi],b[lo:hi]
        ac=collections.Counter(ps.split(b"\0"));bc=collections.Counter(cs.split(b"\0"))
        need(ac-bc=={old:1} and bc-ac=={new:1}, "debug string table differs beyond the recorded jemalloc directory")
        lo,hi=parts[".note.gnu.build-id"]
        need(a[lo:lo+16]==b[lo:lo+16]==struct.pack("<III4s",4,32,3,b"GNU\0") and hi-lo==48, "invalid GNU build ID")
        lo,hi=parts[".debug_info"]
        info=resolved_info(left,a[lo:hi],b[lo:hi],ps,cs,old,new)
    macro=macro_dump(left,old)
    need(macro==macro_dump(right,new),"different resolved DWARF macro records")
    return dict(debug=dict(info=info,macro=macro),ranges=parts,old=old.decode(),new=new.decode(),strings=sum(ac.values()))

def body(z, value):
    return json.loads(gzip.decompress(z.read(value)))

def main():
    root=Path(os.environ["RUNNER_TEMP"])/"upstream-mono-study"
    root.mkdir(exist_ok=True)
    out=root/"logs";out.mkdir(exist_ok=True)
    endpoint="repos/astral-experiments/ohm/actions/artifacts/"+str(ZIP[0])
    a=json.loads(subprocess.check_output(["gh","api",endpoint]))
    need(a["workflow_run"]["id"]==RUN and a["workflow_run"]["head_sha"]==HEAD and a["name"]=="ruff-upstream-mono-pilot"
         and not a["expired"] and a["size_in_bytes"]==ZIP[1] and a["digest"]=="sha256:"+ZIP[2], "wrong original archive")
    raw=root/"failed-pilot.zip"
    with raw.open("xb") as f: subprocess.run(["gh","api",endpoint+"/zip"],stdout=f,check=True)
    need(raw.stat().st_size==ZIP[1] and hexdigest(raw)==ZIP[2], "unverified archive bytes")
    result={}
    with zipfile.ZipFile(raw) as z:
        for revision in "AB":
            refs={};paths={};descs={}
            for role in "PC":
                base=("clean-A-"+role if revision=="A" else "0-"+role+"/B")
                d=body(z,base+"/native.json.gz");descs[role]=d
                art=d["cli"]["whole"];need(art==EXPECTED[revision][role],"unregistered pilot ELF")
                msgs=[json.loads(l) for l in gzip.decompress(z.read(base+"/cargo.stdout.gz")).splitlines()]
                r,=[m for m in msgs if m.get("reason")=="build-script-executed" and "#tikv-jemalloc-sys@" in m["package_id"]]
                paths[role]=os.fsencode(str(Path(r["out_dir"])/"build"))
                f=root/(revision+"-"+role+"-ruff")
                with z.open("reference-bodies/"+art+".zst") as source, f.open("xb") as dest:
                    subprocess.run(["zstd","-dc"],input=source.read(),stdout=dest,check=True)
                need(hexdigest(f)==art and f.stat().st_size==d["cli"]["size"],"different physical ELF")
                refs[role]=f
            p,c=descs["P"],descs["C"]
            need({k:v for k,v in p.items() if k!="cli"}=={k:v for k,v in c.items() if k!="cli"},"typed reader or CLI behavior differs")
            result[revision]=compare(refs["P"],refs["C"],paths["P"],paths["C"])
            (out/"native-progress.json").write_text(json.dumps(result,indent=2)+"\n")
    packet=dict(head=os.environ["REVIEWED_HEAD"],original=HEAD,source_id=RUN,archive=ZIP,refs=EXPECTED,results=result,
                reader=subprocess.check_output(["readelf","--version"],text=True).splitlines()[0])
    (out/"accepted-native.json").write_text(json.dumps(packet,sort_keys=True,indent=2)+"\n")

if __name__=="__main__":
    main()
