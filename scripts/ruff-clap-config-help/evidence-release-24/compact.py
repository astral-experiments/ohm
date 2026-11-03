"""Preserve authenticated raw control members with their original bytes for offline replay."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

def need(value,reason):
    if not value:raise ValueError(reason)
def file_hash(path):
    with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main(source,expected,out,mode,metadata):
    need(not out.exists() and source!=out and file_hash(source)==expected,'input archive or occupied destination')
    with zipfile.ZipFile(source)as z,zipfile.ZipFile(out,'x') as target:
        paths=z.namelist();need(len(set(paths))==len(paths),'duplicate input')
        heads=('old','edit','repair','independent-clean-new')
        protected=set()
        if mode=='ordinary'and metadata:
            for stage in heads:
                p=json.loads(z.read(stage+'/products.json'))
                if 'rmeta'in p:protected.add('bodies/'+p['rmeta']['sha256']+'.zst')
        proof={}
        for name in sorted(paths):
            parts=name.split('/');base=parts[-1]
            if mode=='ordinary':
                selected=(name in ['admission.json','registration.json','compiler.json','intake.json'] or name in protected or name.startswith('four-native-bodies/')
                          or (len(parts)==2 and (base in ('hardware.json','products.json','selected-ruff-members.json','incremental-native-sessions.json','selected-artifact.json','real-ruff-rustcs.json') or base.endswith(('.stdout','.stderr'))or parts[0].startswith('invalid')and base=='stderr')))
            else:
                selected=(name=='accepted.json' or name=='lifetimes-complete.json'
                          or name in ('sampled-edit/kernel.perf','sampled-edit/kernel.perf.zst','sampled-edit/record-counts.json','sampled-edit/samples.ndjson.gz','sampled-edit/event-header.txt')
                          or parts[0]in ('sampled-edit-actual-execs','true-edit-actual-execs','unchanged-actual-execs')
                          or len(parts)==2 and parts[0]in ('sampled-edit','true-edit','unchanged')and base in ('owners.json','products.json'))
            if not selected:continue
            data=z.read(name);stamp=zipfile.ZipInfo(name,(2026,1,1,0,0,0));stamp.compress_type=zipfile.ZIP_DEFLATED
            target.writestr(stamp,data,compresslevel=9);proof[name]=[len(data),hashlib.sha256(data).hexdigest()]
        need(proof,'empty raw subset')
        att={'original':{'name':source.name,'size':source.stat().st_size,'sha256':expected},'files':proof,'mode':mode}
        stamp=zipfile.ZipInfo('member-custody.json',(2026,1,1,0,0,0));stamp.compress_type=zipfile.ZIP_DEFLATED
        target.writestr(stamp,json.dumps(att,sort_keys=True,indent=1).encode()+b'\n',compresslevel=9)
    with zipfile.ZipFile(out)as result:
        need(result.testzip()is None,'compact integrity')
        for name,(size,value)in proof.items():
            row=result.read(name);need(len(row)==size and hashlib.sha256(row).hexdigest()==value,'compact original mismatch')
    print(mode,out.stat().st_size,file_hash(out))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('sha');p.add_argument('out',type=Path);p.add_argument('mode',choices=('ordinary','diagnostic'));p.add_argument('--metadata',action='store_true');v=p.parse_args();main(v.source,v.sha,v.out,v.mode,v.metadata)
