"""Verify complete BSD archives and narrowly identify rustc's optional per-invocation CGU name."""
import hashlib
from pathlib import Path
import re

PATTERN=re.compile(rb'(?P<stem>ruff_python_ast(?:-[0-9a-f]{16})?)\.(?P<cgu>[0-9a-z]{25})\.(?:(?P<salt>[0-9a-z]{7})\.)?rcgu\.o')
MACHO_HEADER=bytes.fromhex('cffaedfe0c000001')
def need(ok,label):
    if not ok:raise ValueError(label)
def sha(b):return hashlib.sha256(b).hexdigest()


def examine(data, native=None):
    need(data.startswith(b'!<arch>\n'),'not BSD ar')
    out=bytearray(data);off=8;proof=[];members={};objects={};salts=set();metadata={}
    while off<len(data):
        header=data[off:off+60];need(len(header)==60 and header[58:60]==b'`\n','bad ar member header')
        raw_name=header[:16].rstrip(b' ');size=int(header[48:58]);start=off+60;end=start+size
        need(end<=len(data) and raw_name.startswith(b'#1/'),'unsupported archive name format')
        width=int(raw_name[3:]);need(0<width<=size,'invalid BSD extended name')
        field=data[start:start+width];name=field.rstrip(b'\x00')
        need(name and name+b'\x00'*(width-len(name))==field and name not in members,'ambiguous BSD member')
        body=data[start+width:end];name_str=name.decode('ascii')
        members[name]=(len(body),sha(body))
        match=PATTERN.fullmatch(name)
        if match:
            base=match['cgu'].decode('ascii');salt=match['salt'];need(base not in objects,'duplicate CGU')
            need(body[:8]==MACHO_HEADER and body[12:16]==b'\x01\x00\x00\x00','not a complete ARM64 Darwin object')
            item={'member':name_str,'cgu':base,'size':len(body),'sha256':sha(body)}
            if native is not None:
                need(native.get(base)==(len(body),item['sha256']),'rlib object differs from own physical rustc CGU: '+name_str)
            if salt is not None:
                need(int(salt,36)<=2**32-1,'impossible rustc invocation number')
                first=start+match.start('salt');out[first:first+7]=b'0'*7;salts.add(salt)
                proof.append([first,first+7,salt.decode(),base,item['sha256']])
            objects[base]=item
        elif name in (b'__.SYMDEF',b'__.SYMDEF SORTED',b'lib.rmeta',b'lib.rmeta-link'):
            metadata[name_str]=[len(body),sha(body)]
        else:raise ValueError('unenrolled archive member '+name_str)
        off=end+size%2
    need(off==len(data) and bool(objects) and 'lib.rmeta' in metadata and any(n.startswith('__.SYMDEF') for n in metadata),'incomplete AST ar')
    need(len(salts)<=1,'one invocation has multiple temporary names')
    if native is not None:need(objects.keys()==native.keys(),'orphan, duplicate or missing local incremental CGU')
    return bytes(out),{'raw_sha256':sha(data),'canonical_sha256':sha(out),'objects':objects,'metadata':metadata,'spans':proof}


def live_cgu(session):
    need(session.is_dir() and not session.is_symlink() and not session.name.endswith('-working'),'unfinalized Ruff session')
    table={}
    for p in session.glob('*.o'):
        need(re.fullmatch('[0-9a-z]{25}',p.stem) and p.is_file() and not p.is_symlink() and p.stem not in table,'ambiguous physical CGU')
        table[p.stem]=(p.stat().st_size,sha(p.read_bytes()))
    need(table and all((session/n).is_file() and (session/n).stat().st_size>0 for n in ('work-products.bin','dep-graph.bin')),'missing codegen generation')
    return table
