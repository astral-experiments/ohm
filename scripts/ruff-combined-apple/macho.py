"""Reconstruct the clean Mach-O from the repaired one and the linker's debug-object names."""
import hashlib
from pathlib import Path
import re
import struct

OBJECT = re.compile(rb"(.+\.rlink-objects/consumed_input(?:-[0-9a-f]+)?\.[0-9a-z]+\.)([0-9a-z]{7})(\.rcgu\.o)")


def offsets(data):
    magic, cpu, _, filetype, count, size, _, _ = struct.unpack_from("<8I", data)
    assert (magic, cpu, filetype) == (0xfeedfacf, 0x0100000c, 2)
    at = 32
    symbols, signature = None, None
    for _ in range(count):
        cmd, length = struct.unpack_from("<II", data, at)
        assert 8 <= length <= 32 + size - at
        if cmd == 2:
            assert symbols is None
            symbols = struct.unpack_from("<4I", data, at + 8)
        elif cmd == 0x1d:
            assert signature is None
            signature = struct.unpack_from("<2I", data, at + 8)
        at += length
    assert at == 32 + size and symbols and signature
    return symbols, signature


def objects(data):
    (symoff, count, stroff, strsize), _ = offsets(data)
    found = {}
    for n in range(count):
        strx, kind, _, _, _ = struct.unpack_from("<IBBHQ", data, symoff + 16*n)
        assert strx < strsize
        if kind == 0x66:  # N_OSO
            start = stroff + strx
            name = data[start:data.index(0, start, stroff+strsize)]
            match = OBJECT.fullmatch(name)
            if match:
                found[start] = (name, match.start(2), match.end(2))
    assert found
    return found


def sign(data, verify):
    _, (pos, size) = offsets(data)
    assert pos + size == len(data)
    magic, blobsize, count, slot, rel = struct.unpack_from(">5I", data, pos)
    assert magic==0xfade0cc0 and count==1 and slot==0 and rel==20 and blobsize<=size
    base = pos+rel
    magic,length,version,flags,hoff,_,special,ncode,limit,hsize,htype,_,pg = struct.unpack_from(">9I4B", data, base)
    page = 1 << pg
    assert magic==0xfade0c02 and version>=0x20400 and flags&2 and limit==pos
    assert special==0 and (hsize,htype)==(32,2) and hoff+ncode*32==length
    assert rel+length==blobsize and ncode==(limit+page-1)//page
    for i in range(ncode):
        digest = hashlib.sha256(data[i*page:min((i+1)*page,limit)]).digest()
        start = base+hoff+i*32
        if verify:
            assert data[start:start+32] == digest
        else:
            data[start:start+32] = digest
    return ncode


def compare(repaired, clean):
    assert len(repaired)==len(clean) and offsets(repaired)==offsets(clean)
    signatures = [sign(data, True) for data in (repaired,clean)]
    left,right = objects(repaired),objects(clean)
    assert left.keys()==right.keys()
    result = bytearray(repaired)
    old_ids,new_ids=set(),set()
    for at,(a,lo,hi) in left.items():
        b,blo,bhi=right[at]
        assert (lo,hi)==(blo,bhi) and a[:lo]==b[:lo] and a[hi:]==b[hi:]
        result[at+lo:at+hi]=b[lo:hi]
        old_ids.add(a[lo:hi].decode());new_ids.add(b[lo:hi].decode())
    assert len(old_ids)==len(new_ids)==1
    sign(result, False)
    assert result==clean, "native bytes outside the actual N_OSO names and derived code signature changed"
    return {"bytes":len(clean),"debug_objects":len(left),"signed_pages":signatures,"reconstructed_entire_file":True,
            "object_suffixes":[old_ids.pop(),new_ids.pop()]}
