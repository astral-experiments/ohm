"""Offline hostile tests for archive admissions, source projections and genuinely same-stat native providers."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *
import fixture
from sdk import reopen

def check_pack(tmp):
    """Run the deployed reader on a tiny synthetic artifact whose bytes satisfy its exact envelope."""
    from copy import deepcopy
    roles={k:{'commit':c,'tree':t,'path':'roles/'+k+'/cargo','release_channel':'dev'} for k,(c,t) in ROLES.items()}
    files={'sdk/bin/rustc':b'synthetic rustc','sdk/lib/driver':b'synthetic driver','sdk/bin/cargo':b'pinned','roles/pinned/cargo':b'pinned','roles/fourfix/cargo':b'fixed'}
    def test(tag,over=None):
        d=tmp/tag;d.mkdir();m={n:{'sha256':hashlib.sha256(x).hexdigest(),'bytes':len(x),'mode':0o755} for n,x in files.items()}
        for k,v in roles.items():v['sha256']=m[v['path']]['sha256']
        proposal={**files}
        if tag=='foreign-member':proposal['../outside']=b'no'
        if tag=='incomplete':proposal.pop('sdk/lib/driver')
        if tag=='different-body':proposal['roles/fourfix/cargo']=b'other'
        buff=io.BytesIO()
        with tarfile.open(fileobj=buff,mode='w') as ar:
            for n,body in proposal.items():
                i=tarfile.TarInfo(n);i.size=len(body);i.mode=0o755;ar.addfile(i,io.BytesIO(body))
        subprocess.run(['zstd','-q','-o',d/'kit.tar.zst'],input=buff.getvalue(),check=True);save(d/'members.json',m)
        j={'schema':1,'rust':{'host':host(),'commit':RUST,'tree':RTREE,'driver_path':'sdk/lib/driver','driver_sha256':m['sdk/lib/driver']['sha256'],'rustc_sha256':m['sdk/bin/rustc']['sha256']},'cargos':deepcopy(roles),'members_sha256':sha(d/'members.json'),'kit_sha256':sha(d/'kit.tar.zst'),'kit_bytes':(d/'kit.tar.zst').stat().st_size}
        if tag=='foreign-source':j['cargos']['fourfix']['commit']=ROLES['pinned'][0]
        if tag=='swapped-digest':j['kit_sha256']='a'*64
        save(d/'receipt.json',j)
        try:reopen(d,d/'installed')
        except (RuntimeError,KeyError):
            require(tag!='pass',tag);return
        require(tag=='pass',('admitted negative',tag))
    for tag in ('pass','foreign-member','incomplete','different-body','foreign-source','swapped-digest'):test(tag)

def test(tmp):
    registry=[{'name':k,'version':v,'source':'registry+https://github.com/rust-lang/crates.io-index','checksum':s,**({'dependencies':['objc2-encode']} if k=='objc2' else {})} for k,(v,s) in LOCKED.items()]
    registry.append({'name':'objc2-encode','version':'4.1.0','source':'registry+https://github.com/rust-lang/crates.io-index','checksum':'ef25abbcd74fb2609453eb695bd2f860d389e457f67dc17cafc8b8cbc89d0c33'})
    lock=tmp/'Ruff.lock';lock.write_text('version = 4\n'+''.join('[[package]]\n'+''.join(k+' = '+json.dumps(v)+'\n' for k,v in r.items()) for r in registry))
    for name in LOCKED:
        out=tmp/name
        fixture.project(out,name,lock);body=(out/'src/main.rs').read_text();require('qa_rc22_value' in body and 'qa_rc22_origin' in body and 'asm!' not in body and 'global_asm!' not in body and 'rerun-if-changed=build.rs' in (out/'build.rs').read_text(),'native provenance fixture')
    home=tmp/'platform';receipts=tmp/'receipts';receipts.mkdir()
    vals=fixture.providers(home,receipts);fixture.configure(home,vals,'low');fixture.configure(home,vals,'high29')
    good=fixture.configure(home,vals,'high41');bad=fixture.configure(home,vals,'bad');repair=fixture.configure(home,vals,'high29')
    for change in [good,bad,repair]:
        before,after=change['early'].values();require(before['sha256']!=after['sha256'] and all(before[k]==after[k] for k in ('ino','dev','bytes','mtime_ns')),'same-stat controls')
    require(fixture.configure(home,vals,'low')['early']['after'] is None,'removal')
    check_pack(tmp)
    print('two locked projections, valid/same-stat/malformed/repair/removal, one archive acceptance and five independent refusals')
if __name__=='__main__':
    with tempfile.TemporaryDirectory() as t:test(Path(t))
