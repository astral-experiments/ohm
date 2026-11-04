"""Describe all physical section payload differences between the two source-built compiler roles."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zipfile


def body_hash(data):
    return hashlib.sha256(data).hexdigest()


def sections(data):
    assert data[:6] == b"\x7fELF\x02\x01"
    shoff, = struct.unpack_from("<Q", data, 40)
    entry, n, si = struct.unpack_from("<HHH",data,58)
    assert entry == 64 and 0 < si < n
    headers = [struct.unpack_from("<IIQQQQIIQQ",data,shoff+i*entry) for i in range(n)]
    strings = data[headers[si][4]:headers[si][4]+headers[si][5]]
    result = {}
    for name,typ,flags,addr,off,size,link,info,align,entsize in headers[1:]:
        name=strings[name:strings.index(0,name)].decode()
        assert name not in result
        raw=data[off:off+size] if typ!=8 else b""
        result[name]={"bytes":size,"sha256":body_hash(raw),"allocated":bool(flags&2),"exec":bool(flags&4)}
    return result


def main():
    directory=Path(sys.argv[1])
    summary=json.loads((directory/"verified.json").read_bytes())
    block=summary["blocks"][0]
    with zipfile.ZipFile(directory/(str(block["artifact"])+".zip")) as z:
        result={}
        for phase in ("old","new"):
            pairs={}
            for role in ("P","C"):
                sha=block["native"][role][phase]
                raw=subprocess.check_output(["zstd","-qdc"],input=z.read("native/"+sha+".zst"))
                assert body_hash(raw)==sha
                pairs[role]=sections(raw)
            assert set(pairs["P"])==set(pairs["C"])
            result[phase]={k:{role:pairs[role][k] for role in ("P","C")}
                           for k in pairs["P"] if pairs["P"][k]!=pairs["C"][k]}
        argv={}
        for role in ("P","C"):
            raw=json.loads(z.read(role+"/observed-edit/physical.json"))
            kernels=[a for a in raw["actual"] if a["crate"]=="ruff_python_parser"]
            selected,=kernels
            argv[role]=[v for v in selected["argv"] if v.startswith(("metadata=","extra-filename="))]
        result["actual_parser_codegen_flags"]=argv
    (directory/"cross-role-sections.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    for phase in ("old","new"):
        print(phase,sorted(result[phase]),"allocated",[n for n,v in result[phase].items() if v["P"]["allocated"]])
    print(argv)


if __name__=="__main__":
    main()
