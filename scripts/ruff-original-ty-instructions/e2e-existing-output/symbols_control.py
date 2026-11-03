"""Challenge the exact Rust symbols.o gate using the authenticated temporary from the native Cargo job."""
import hashlib
import struct
import subprocess

def source(body):
    name='pub(crate) fn symbols_only('
    assert body.count(name)==1
    start=body.index(name);end=body.index('\n}\n',start)+3
    return body[start:end]+'''\nfn main(){ use std::io::Read; let mut b=Vec::new();std::io::stdin().read_to_end(&mut b).unwrap();
        std::process::exit(if symbols_only(&b){0}else{2}); }\n'''
def build(root,script,env):
    p=root/'qa_symbols_gate.rs';p.write_text(source((script/'reuse.rs').read_text()))
    subprocess.run(['rustc','+ohm','--edition=2024',p,'-o',root/'qa-symbols-gate'],env=env,check=True,timeout=120)
def cases(file,known):
    b=file.read_bytes();assert len(b)==39760 and hashlib.sha256(b).hexdigest()==known
    table=struct.unpack_from('<Q',b,40)[0];sympos=struct.unpack_from('<Q',b,table+2*64+24)[0]+24
    mutate=lambda p,v:b[:p]+v+b[p+len(v):]
    assert b[sympos+4]==16 and b.count(b'\x00main\x00')==1
    return [('ordinary genuine object',0,b),('different symbol name still structurally pure',0,b.replace(b'\x00main\x00',b'\x00zzQA\x00')),
          ('symbol with file provenance',2,mutate(sympos+4,b'\x14')),('symbol defined in input',2,mutate(sympos+6,b'\x01\x00')),
          ('unexpected property payload',2,mutate(64+24,b'\x02')),('executable section',2,mutate(table+64+8,b'\x04')),
          ('relocations',2,mutate(table+64+4,b'\x04')),('truncated',2,b[:-1]),('segment',2,mutate(56,b'\x01'))]
def run(root,file):
    out={}
    for name,code,raw in cases(file,'686f6a2749ab0d980e5627e5568850d2a8d8e79e480d6d62499241056036873d'):
        r=subprocess.run([root/'qa-symbols-gate'],input=raw,capture_output=True,timeout=5)
        assert r.returncode==code and not r.stdout and not r.stderr,(name,r.returncode)
        out[name]={'exit':r.returncode,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    assert len({x['sha256']for x in out.values()})==len(out)
    return out
