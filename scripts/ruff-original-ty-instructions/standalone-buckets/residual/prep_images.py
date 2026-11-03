"""Extract and authenticate just the three Rust/LLVM ELF images needed by the offline PC reader."""
import argparse,hashlib,json,shutil,subprocess,tarfile,zipfile
from pathlib import Path
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def extract(kit,out):
    if sha(kit)!='2617b279f0ce68bd5ac6d325b64aa2cf4f7a8c430f5e39eeeb6896b8c7273bf9':raise ValueError('factory asset SHA')
    out.mkdir(exist_ok=True);z=subprocess.Popen(['unzip','-p',kit,'matched-stage.tar.zst'],stdout=subprocess.PIPE);decomp=subprocess.Popen(['zstd','-qdc'],stdin=z.stdout,stdout=subprocess.PIPE);z.stdout.close();seen=set();wanted={}
    with tarfile.open(fileobj=decomp.stdout,mode='r|')as store:
        for mem in store:
            if mem.name=='capsule/C.json':
                raw=store.extractfile(mem).read();manifest=json.loads(raw)
                assert manifest['commit']=='5c5af1a053326e6ce5df048c4dcb30b53e01a069';(out/'capsule-C.json').write_bytes(raw)
                for k,(digest,size,mode)in manifest['files'].items():
                    if k=='bin/rustc'or 'librustc_driver-'in k or k.startswith('lib/libLLVM.so.23.1'):wanted[digest]=size
            elif mem.name.startswith('capsule/objects/')and mem.name.split('/')[-1]in wanted:
                h=mem.name.split('/')[-1];p=out/('image-'+h)
                assert mem.isfile()and mem.size==wanted[h]
                with p.open('wb')as f:shutil.copyfileobj(store.extractfile(mem),f)
                assert sha(p)==h;seen.add(h)
    decomp.stdout.close();assert decomp.wait()==z.wait()==0 and len(seen)==len(wanted)==3
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('kit',type=Path);ap.add_argument('directory',type=Path);a=ap.parse_args();extract(a.kit,a.directory)
