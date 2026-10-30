"""Authenticate one experimental, unpushed Cargo commit delivered through workflow_dispatch."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from receipt_cargo import build, materialize
from study import need, run

BASE = '735e1528ed741015c57676dccf05dbdc0ff7bed1'
CHILD = '6b2d0f6c1a23c862d5373d0bce03db5d889dd042'
TREE = '71a66ff87b11d3c7584883a5589099a2f2957a46'
BLOB = 'd6eb3eecf130bb9a0443b84aa4ce721eeceed0db'
PACKET = 'fd36fae1395175e914d9fbe80dc919f780d1567d58ec0cbcc87354dd3c0d5a71'
PATCH = '2d4ffa3b8fb6e31e57600ad801b0bf80faa19aba01efe0ef903bda1f1ea1298c'
NAME = 'src/compiler/fingerprint/mod.rs'

def insert(src, base, packet):
    need(len(packet)==2176 and hashlib.sha256(packet).hexdigest()==PACKET,'unregistered experiment input')
    data=json.loads(packet)
    patch=data['patch'].encode()
    need(base['commit']==data['parent']==BASE and data['child']==CHILD and data['tree']==TREE
         and hashlib.sha256(patch).hexdigest()==PATCH,'different source subject')
    def git(*args,body=None):
        return run(['git','-c','core.autocrlf=false',*args],cwd=src,data=body)
    git('apply','--index','--check','-',body=patch)
    git('apply','--index','-',body=patch)
    need(git('write-tree').decode().strip()==TREE,'different patched Git tree')
    raw=base64.b64decode(data['commit_object'],validate=True)
    need(raw.splitlines()[:2]==[('tree '+TREE).encode(),('parent '+BASE).encode()]
         and git('hash-object','-t','commit','-w','--stdin',body=raw).decode().strip()==CHILD,'different commit object')
    git('update-ref','--no-deref','HEAD',CHILD)
    need(git('rev-parse','HEAD:'+NAME).decode().strip()==BLOB and git('status','--porcelain')==b''
         and git('diff','--name-only',BASE,CHILD)==(NAME+'\n').encode(),'source or index mismatch')
    return {**base,'commit':CHILD,'parent':BASE,'tree':TREE,'qualification_only':True,
            'packet_sha256':PACKET,'patch_sha256':PATCH,'source_path':NAME,'blob':BLOB}

def packet_from_event():
    event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
    entry=event['inputs']['experiment'];need(len(entry)<4000,'oversize input')
    return base64.b64decode(entry,validate=True)

if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('action',choices=['build','verify']);cli.add_argument('path',type=Path);cli.add_argument('--local-packet',type=Path)
    a=cli.parse_args();packet=a.local_packet.read_bytes() if a.local_packet else packet_from_event()
    source=lambda src,base:insert(src,base,packet)
    if a.action=='build':build(a.path.resolve(),source)
    else:print(json.dumps(source(a.path.resolve(),materialize(a.path.resolve())),sort_keys=True))
