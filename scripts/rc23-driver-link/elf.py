"""Census the actual GNU x86_64 ELF inputs and preserve the named dynamic references."""
import collections
import gzip
import hashlib
import json
import mmap
import re
import struct
from pathlib import Path

def scan(path, output, pools=None):
    with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as image:
        def read(fmt, offset): return struct.unpack_from("<" + fmt, image, offset)
        assert image[:7] == b"\x7fELF\x02\x01\x01" and read("HH", 16) == (3, 62)
        phoff, shoff = read("QQ", 32)
        phsize, phnum, shsize, shnum, shstr = read("HHHHH", 54)
        assert phsize == 56 and shsize == 64 and 0 < shstr < shnum
        sections = [read("IIQQQQIIQQ", shoff + i*shsize) for i in range(shnum)]
        def string(section, pos):
            assert 0 <= pos < section[5]
            start = section[4]+pos
            end=image.find(b"\0", start, section[4]+section[5])
            assert end>=start
            return image[start:end].decode("ascii")
        sec = {string(sections[shstr], row[0]): row for row in sections}
        sy, st = sec[".dynsym"], sec[".dynstr"]
        assert sy[9]==24 and sections[sy[6]]==st
        syms=[]
        for off in range(sy[4],sy[4]+sy[5],24):
            idx, info, other, section, val, size=read("IBBHQQ",off)
            syms.append((string(st,idx),info>>4,info&15,other&3,section!=0,val))
        assert len([s[0] for s in syms])==len(set(s[0] for s in syms)), "duplicate dynamic ELF name"
        if pools is None:pools=json.loads((Path(__file__).resolve().parent/"probes.json").read_bytes())
        wanted={n:label for label,names in pools.items() for n in names}
        values=collections.Counter(s[5] for s in syms if s[4] and s[2]==2)
        probes={s[0]:{"pool":wanted[s[0]],"value":s[5],"slots":[]} for s in syms if s[0] in wanted and s[1:5]==(1,2,0,True) and values[s[5]]==1}
        indirect={v["value"]:n for n,v in probes.items()}
        named=collections.Counter()
        relocs=collections.Counter()
        targets=collections.Counter()
        def target_section(address):
            match=[name for name,row in sec.items() if row[2]&2 and not (row[1]==8 and row[2]&0x400) and row[3]<=address<row[3]+row[5]]
            assert len(match)==1,(address,match)
            return match[0]
        for name in (".rela.dyn",".rela.plt"):
            if name not in sec: continue
            tbl=sec[name]
            assert tbl[1]==4 and tbl[9]==24 and sections[tbl[6]]==sy
            for off in range(tbl[4],tbl[4]+tbl[5],24):
                addr,info,add=read("QQq",off)
                idx,kind=info>>32,info&0xffffffff
                relocs[name,kind]+=1
                if not idx and kind==8 and add in indirect:
                    slot=target_section(addr)
                    if slot in (".got",".data.rel.ro"):probes[indirect[add]]["slots"].append([addr,kind,slot])
                if idx:
                    sym=syms[idx]
                    slot=target_section(addr)
                    if sym[0] in probes and kind in (1,6) and add==0 and slot in (".got",".data.rel.ro"):
                        probes[sym[0]]["slots"].append([addr,kind,slot])
                    named[name,kind,slot,sym[0]]+=1
                    if sym[4] and sym[1:4]==(1,2,0) and sym[0].startswith("_R") and kind in (1,6) and slot in (".got",".data.rel.ro"):
                        targets[sym[0]]+=1
        comments=sec[".comment"]
        comment=image[comments[4]:comments[4]+comments[5]].rstrip(b"\0").split(b"\0")
        lld=[x.decode() for x in comment if x.startswith(b"Linker: LLD ")]
        assert len(lld)==1 and "23.1.1" in lld[0],lld
        corpus={"symbols":[list(s[:5]) for s in syms if s[0]],"named_relocations":[[*k,v] for k,v in sorted(named.items())],"own_strong_v0_slots":dict(sorted(targets.items()))}
        raw=(json.dumps(corpus,separators=(",",":"))+"\n").encode()
        if output is not None:
            with output.open("xb") as out: out.write(gzip.compress(raw,compresslevel=4,mtime=0))
        # Hash content of the loaded native text and dynamic lookup structures.
        mapping={n:hashlib.sha256(image[v[4]:v[4]+v[5]]).hexdigest() for n,v in sec.items() if (v[2]&4 and v[1]!=8) or n in (".rela.dyn",".rela.plt",".dynsym",".dynstr",".gnu.hash",".gnu.version",".note.bolt_info")}
        return {"text_and_dynamic_sha256":hashlib.sha256(json.dumps(mapping,sort_keys=True).encode()).hexdigest(),"sha256":hashlib.sha256(image).hexdigest(),"bytes":len(image),"linker":lld[0],"bolt_note":".note.bolt_info" in sec,
                "relocation_kinds":[[*k,v] for k,v in sorted(relocs.items())],"dynamic_symbols":len(syms)-1,
                "defined":sum(s[4] for s in syms),"strong_self_slots":sum(targets.values()),"strong_self_names":len(targets),
                "census_uncompressed_sha256":hashlib.sha256(raw).hexdigest(),"probes":probes}

if __name__=="__main__":
    import sys
    print(json.dumps(scan(Path(sys.argv[1]),Path(sys.argv[2])),sort_keys=True))
