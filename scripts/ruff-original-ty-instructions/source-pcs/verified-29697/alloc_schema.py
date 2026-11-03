"""Compare per-item RDR results by stable local DefPathHash in actual original .rmetas."""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
import subprocess
import zipfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decode_symbols(text):
    keywords, symbols = text.split('Keywords {', 1)[1].split('Symbols {', 1)
    names = [m[1] for m in re.findall(r'^\s*(\w+):\s*"([^"\n]+)"', keywords, re.M)]
    assert names[56] == "'_"
    symbols = re.sub(r'\\\n\s*', '', symbols.replace('little, big,', 'little,\n        big,'))
    for line in symbols.splitlines():
        if line.strip() == '}':
            break
        m = re.match(r'^\s*(\w+)(?::\s*"([^"]*)")?,\s*(?://.*)?$', line)
        if m:
            names.append(m[2] if m[2] is not None else m[1])
    return names


class Reader:
    def __init__(self, raw, symbols):
        self.raw = raw
        self.symbols = symbols
        self.pos = 0

    def take(self, count):
        assert 0 <= count <= len(self.raw) - self.pos
        self.pos += count
        return self.raw[self.pos - count : self.pos]

    def byte(self):
        return self.take(1)[0]

    def var(self):
        val = 0
        for sh in range(0, 64, 7):
            b = self.byte()
            assert sh != 63 or b <= 1
            val |= (b & 127) << sh
            if b < 128:
                return val
        raise ValueError('overlong unsigned integer')

    def string(self):
        value = self.take(self.var()).decode()
        assert self.byte() == 0xc1
        return value

    def symbol(self):
        tag = self.byte()
        if tag == 0:
            return self.string()
        if tag == 2:
            n = self.var()
            return self.symbols[n] if n < len(self.symbols) else f'PREDEFINED#{n}'
        assert tag == 1
        dest = self.var()
        assert 0 < dest < self.pos
        self.pos, last = dest, self.pos
        label = self.string()
        self.pos = last
        return label


def schema(source):
    symbol_src = (source/'compiler/rustc_span/src/symbol.rs').read_bytes()
    struct_src = (source/'compiler/rustc_metadata/src/rmeta/mod.rs').read_bytes()
    hashes = [digest(symbol_src), digest(struct_src)]
    assert hashes == ['ccb5d381f80da43664eb3ef5ee25920bd5859f4020e0f949c4084fd9e904e81c','939927ea4e04ceeae1cbd63a7be80a91d213f594dafdce596ac0e7815ce8ca2c']
    field_list = struct_src.decode().split('define_tables! {',1)[1].split('\n}',1)[0]
    names = re.findall(r'^    (\w+): Table<', field_list, re.M)
    assert len(names)>85 and len(names)==len(set(names))
    return decode_symbols(symbol_src.decode()), names


def decode(raw, symbols, table_names, expected_crate, version, *, typed=None, selected_tables=()):
    r = Reader(raw,symbols)
    assert r.take(8)==b'rust\0\0\0\n'
    root = int.from_bytes(r.take(8), 'little')
    ver = r.string()
    assert ver == version and r.pos < root < len(raw)-13, (ver,version)
    r.pos = root
    last = None
    def position():
        nonlocal last
        n = r.var()
        nxt = root-n if last is None else last+n
        assert 0<nxt<=root and (last is None or last<=nxt)
        last=nxt
        return nxt
    def array():
        n = r.var()
        return n,position() if n else None
    def table():
        return r.var(), r.var(), position()
    assert r.symbol()=='x86_64-unknown-linux-gnu'
    private, public = r.take(16).hex(), r.take(16).hex()
    assert r.symbol()==expected_crate and r.byte()==0 and r.byte()==0
    suffix,stable=r.string(),r.take(8).hex()
    assert re.fullmatch(r'-[0-9a-f]{16}',suffix)
    assert [r.var() for _ in range(7)]==[0,0,3,0,0,0,0]
    arrays = [array() for _ in range(13)]
    assert r.byte() in (0,1)  # EncodedTraitImpls variants each own one LazyArray.
    for _ in range(3): array()
    assert r.byte()==0
    for _ in range(5): array()
    assert r.byte() in (0,1)
    tables={key:table() for key in (*table_names,'syntax_contexts','expn_data','expn_hashes')}
    position(); tables['source_map']=table(); array(); array()
    flags=[r.var() for _ in range(9)]
    option = r.byte()
    assert flags[-1] in (0,1) and option in (0,1)
    if option:
        tables['rdr_local'],tables['rdr_expn']=table(),table()
        global_hash=r.take(16).hex()
    else:
        tables['rdr_local']=tables['rdr_expn']=(0,0,0)
        global_hash=None
    assert r.take(13)==b'rust-end-file' and r.pos==len(raw)
    def slots(name):
        code,n,at=tables[name]
        w=code&127
        assert n<2**22 and 0<=w<=17
        if not (code&128):
            assert at+w*n<=root
            for i in range(n):
                v=raw[at+i*w:at+(i+1)*w]
                if any(v):yield i,v
            return
        groups=(n+63)//64; data=at+12*groups; seen=0
        assert data<=root
        for g in range(groups):
            bits,rank=struct.unpack_from('<QI',raw,at+12*g)
            assert rank==seen and bits.bit_length()<=min(64,n-64*g)
            while bits:
                bit=bits&-bits
                off=data+w*seen
                assert off+w<=root
                yield 64*g+(bit.bit_length()-1),raw[off:off+w]
                bits^=bit; seen+=1
    rows={i:b[1:].hex() for i,b in slots('rdr_local') if len(b)==17 and b.startswith(b'\x01')}
    assert len(rows)==sum(1 for _ in slots('rdr_local'))
    identities={i:h.hex() for i,h in slots('def_path_hashes')}
    assert len(identities)==tables['def_path_hashes'][1] and len(set(identities.values()))==len(identities)
    defs={}; tags=('crate','impl','extern','use','global_asm','type','value','macro','lifetime','closure','ctor','anon_const','opaque','opaque_lifetime','anon_assoc','corout','nested')
    for i,b in slots('def_keys'):
        r.pos=int.from_bytes(b,'little'); present=r.byte();assert present<=1
        parent=r.var() if present else None
        assert (parent is None and i==0) or parent in defs
        kind=r.var(); tag=tags[kind]; name=r.symbol() if kind in (5,6,7,8,13,14) else None; ord_=r.var()
        part=name if name is not None else '{'+tag+'#'+str(ord_)+'}'
        path=(defs[parent][0]+'::' if parent else '')+part if i else '{{crate}}'
        defs[i]=(path,parent,tag,name,ord_)
    assert len(defs)==len(identities) and all(i in identities for i in rows)
    ds={identities[i]:d for i,d in defs.items()}; local={identities[i]:f for i,f in rows.items()}
    expn={i:b[1:].hex() for i,b in slots('rdr_expn') if len(b)==17 and b.startswith(b'\x01')}
    assert len(expn)==sum(1 for _ in slots('rdr_expn'))
    n,pos=arrays[1];r.pos=pos;deps={}
    for _ in range(n):
        name=r.symbol();hashed=r.take(16).hex();has_host=r.byte();assert has_host<=1
        host=r.take(16).hex() if has_host else None
        kind=r.byte();extra=r.string();private_dep=r.byte();assert kind<5 and private_dep<=1
        key=name+extra;assert key not in deps;deps[key]=(hashed,host,kind,private_dep)
    if typed is not None:
        if selected_tables:
            typed['selected_tables']={k:dict(slots(k)) for k in selected_tables}
        typed['path_by_index']={i: (identities[i], defs[i][0]) for i in defs}
        typed['kinds']={identities[i]: int.from_bytes(b,'little') for i,b in slots('def_kind')}
        scopes={}
        for i,b in slots('visibility'):
            r.pos=int.from_bytes(b,'little');tag=r.var();assert tag in (0,1)
            scopes[identities[i]]=identities[r.var()] if tag else None
        typed['visibility']=scopes
    return dict(crate=expected_crate,compiler=version,stable=stable,private=private,public=public,global_hash=global_hash,full=digest(raw)),ds,local,expn,deps
