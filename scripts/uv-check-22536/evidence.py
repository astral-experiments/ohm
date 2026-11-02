"""Export native receipts and all bare/PMU values, without publishing target trees or tools."""
from pathlib import Path
import hashlib,io,json,os,sys,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import CASE,Env,canon,digest,filehash,read,readz,write
def export(w):
    fit=128<<20;lim=24<<20;out=w/'session-evidence';out.mkdir();archive=out/'original.zip';files={};optional={}
    def allow(root):
        for f in root.rglob('*'):
            if f.is_symlink() or not f.is_file():continue
            rel=str(f.relative_to(w))
            if f.name in ('stdout','stderr','cargo.stdout','cargo.stderr')or f.name.endswith(('.json','.json.gz','.log','.jsonl')):files[rel]=f
    for d in (w/'session-results',w/'trait-results'):
        if d.is_dir():allow(d)
    if not files:
        # A source, ref or host gate can stop before the first native command.
        # Keep that distinction visible even when there is no experiment to read.
        stopped=w/'session-results/pre-intake-stop.json'
        write(stopped,{'protocol':CASE['protocol'],'observed_score':False,'run_id':os.environ.get('GITHUB_RUN_ID'),'source_commit':os.environ.get('GITHUB_SHA'),'empty_native_and_transport_receipts':True})
        files[str(stopped.relative_to(w))]=stopped
    assert files and all('/.git/'not in name for name in files)
    cfg=w/'session-config.json';expected={};total=0
    if cfg.is_file():
        e=Env(read(cfg))
        for f in sorted((e.results/'qualification').glob('*/fresh-?/typed-warm-cold.json.gz')):
            z=readz(f)
            for name,row in z['changes'].items():
                if name not in('uv_client','uv_extract'):continue
                for _,key in(row['warm'],row['cold']):
                    if key in expected:continue
                    g=e.cas/(key+'.gz');expected[key]=[g.stat().st_size,filehash(g)]
                    if total+g.stat().st_size<=lim:
                        optional['metadata-origins/'+key+'.gz']=g;total+=g.stat().st_size
    inventory={k:[f.stat().st_size,filehash(f)]for k,f in (files|optional).items()};manifest={'all_compact_primary_evidence':len(files),'optional_original_crate_bytes_compressed':total,'optional_raw_budget':lim,'available_raw_hashes':expected,'members':inventory}
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=5)as z:
        for k,f in sorted((files|optional).items()):z.write(f,k)
        z.writestr('receipt.json',canon(manifest))
    assert archive.stat().st_size<=fit,(archive.stat().st_size,fit)
    with zipfile.ZipFile(archive)as z:
        assert z.testzip()is None and len(z.namelist())==len(inventory)+1
        for n,(length,h)in inventory.items():
            with z.open(n)as fp:assert hashlib.file_digest(fp,'sha256').hexdigest()==h
    write(out/'verified.json',{'bytes':archive.stat().st_size,'sha256':filehash(archive),'complete_score':(w/'session-results/result.json').is_file(),'compact_file_count':len(files),'optional_rmeta_count':len(optional),'maximum_bytes':fit})
if __name__=='__main__':export(Path(os.environ['GITHUB_WORKSPACE']).resolve())
