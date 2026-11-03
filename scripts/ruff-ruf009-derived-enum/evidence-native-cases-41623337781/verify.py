"""Decode all six exact images and repeat the full earlier native, ELF and DWARF observations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import read_native

def load(path):return json.loads(path.read_bytes())
def sha(path):
    with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    arg=argparse.ArgumentParser();arg.add_argument('--out',type=Path,required=True);a=arg.parse_args()
    commitments={line.split('  ',1)[1]:line.split('  ',1)[0] for line in (HERE/'SHA256SUMS').read_text().splitlines()}
    for name,h in commitments.items():assert sha(HERE/name)==h
    records=HERE/'original-records.zip';images=HERE/'images';manifest=load(images/'manifest.json')
    assert shutil.which('b3sum') and shutil.which('llvm-dwarfdump-18') and len(manifest)==6
    with tempfile.TemporaryDirectory()as d:
        d=Path(d);assert shutil.disk_usage(d).free>4<<30
        for item in manifest:
            key=item['sha256'];f=images/(key+'.zst');assert sha(f)==item['archive'] and f.stat().st_size==item['archive_size']
            options=[]
            if item['reference']is not None:
                reference=d/item['reference'];assert sha(reference)==item['reference'];options=['--long=28','--patch-from='+str(reference)]
            out=d/key
            with out.open('xb')as dest:subprocess.run(['zstd','-qdc',*options,f],stdout=dest,check=True)
            assert sha(out)==key and out.stat().st_size==item['size']
        result=read_native.main(records,sha(records),d)
        projected=load(HERE/'independent-original.json')
        assert result.pop('archive_sha256')==sha(records) and projected.pop('archive_sha256')=='07598db8d720885ff29156b3bc0ea92d31df72666bb1b70a3e0dd9807f6a125e'
        assert json.loads(json.dumps(result))==projected
        dst=d/'proof.json';subprocess.run([sys.executable,'-IB',HERE/'sections.py',records,sha(records),HERE.parent/'elf_gate.py',dst,'--objects',d],check=True)
        real=load(dst);ref=load(HERE/'forensic-stable.json');assert real.pop('sha')==sha(records) and ref.pop('sha')=='07598db8d720885ff29156b3bc0ea92d31df72666bb1b70a3e0dd9807f6a125e'
        assert real==ref
        for data in real['seed_vs_cold'].values():
            names=data['changed_strings'];assert len(names)==49 and data['changed_symbol_table_bytes']==833
            for v in names:
                old,o=v['previous'].rsplit('.llvm.',1);new,n=v['current'].rsplit('.llvm.',1)
                assert old==new and (o,n)==('1662158750336645859','5427985223311763881')
                assert all((s[2]&3)==2 for _,syms in v['symbols']for s in syms)
        proof={'qualified':False,'reason':'seed differs from independently empty in the same role','visits':18,
               'runtime':72,'errors':result['invalid'],'full_sha256':sorted(result['sections']),
               'all_native_observations':sha(HERE/'independent-original.json'),'all_decoded_fields':sha(HERE/'forensic-original.json')}
    a.out.write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')

if __name__=='__main__':main()
