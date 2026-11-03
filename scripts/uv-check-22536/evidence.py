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
    cfg=w/'session-config.json';expected={};raw={};chosen=[];unavailable=[];required=[]
    if cfg.is_file():
        e=Env(read(cfg))
        def add(key,critical=False):
            if critical and key not in required:required.append(key)
            if key in expected or key in unavailable:return
            g=e.cas/(key+'.gz')
            if not g.is_file():unavailable.append(key);return
            expected[key]=[g.stat().st_size,filehash(g)];raw[key]=g
        requests=sorted(e.results.glob('pairs/*/*/native-?/live-raw-request.json.gz'),key=lambda f:f.stat().st_mtime_ns,reverse=True)
        def stopped(f):
            final=f.parent/'typed-warm-cold.json.gz'
            return not final.is_file()or not readz(final)['accepted']
        critical=next((f for f in requests if stopped(f)),None)
        for f in ([critical]if critical else [])+[f for f in requests if f!=critical]:
            q=readz(f);is_refusal=f==critical
            for row in q.values():
                for field in ('held','cold'):add(row[field][1],is_refusal)
            for row in q.values():
                for _,key in row['externs'].values():add(key,is_refusal)
            for hd in sorted((f.parent/'new-history-fixed').glob('*/actual-headers.json.gz')):
                add(readz(hd)['after_raw'][1])
        # A typed refusal may precede the optional external input list being written.
        for f in sorted(e.results.glob('pairs/*/*/native-?/initial-native-guard/typed-warm-cold.json.gz'),key=lambda f:f.stat().st_mtime_ns,reverse=True):
            r=readz(f)
            if not r['accepted']:
                for n in r['unresolved']:
                    for field in ('warm','cold'):add(r['changes'][n][field][1],not(f.parent.parent/'live-raw-request.json.gz').is_file())
        for f in sorted((e.results/'qualification').glob('*/fresh-?/typed-warm-cold.json.gz')):
            for name,row in readz(f)['changes'].items():
                if name in ('uv_client','uv_extract'):
                    for _,key in (row['warm'],row['cold']):add(key)
    inventory={k:[f.stat().st_size,filehash(f)]for k,f in files.items()}
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=5)as z:
        for k,f in sorted(files.items()):z.write(f,k)
        # Preserve the final refused source and every actual external input first.
        # Registry dependencies and synthetic products from earlier visits share
        # the same digest pool. The old 24 MiB limit still applies to extras.
        max_manifest=4*(len(canon(inventory))+len(canon(expected))+len(canon(required))+len(canon(unavailable)))+65536
        capacity=fit-z.fp.tell()-max_manifest
        total=extras=0;omitted=[]
        for key in list(dict.fromkeys(required+list(raw))):
            if key not in raw:continue
            g=raw[key];size=g.stat().st_size;critical=key in required
            if size+256>capacity or(not critical and extras+size>lim):omitted.append(key);continue
            k='metadata-origins/'+key+'.gz';z.write(g,k,compress_type=zipfile.ZIP_STORED);inventory[k]=expected[key];chosen.append(key);total+=size;capacity-=size+256
            if not critical:extras+=size
        manifest={'all_compact_primary_evidence':len(files),'optional_original_crate_bytes_compressed':total,'optional_raw_budget':lim,'available_raw_hashes':expected,'priority_refused_metadata_and_externs':required,'omitted_after_safe_budget':omitted,'requested_but_missing':unavailable,'all_priority_raw_retained':set(required)<=set(chosen),'members':inventory}
        assert len(canon(manifest))<max_manifest
        z.writestr('receipt.json',canon(manifest))
    assert archive.stat().st_size<=fit,(archive.stat().st_size,fit)
    with zipfile.ZipFile(archive)as z:
        assert z.testzip()is None and len(z.namelist())==len(inventory)+1
        for n,(length,h)in inventory.items():
            with z.open(n)as fp:assert hashlib.file_digest(fp,'sha256').hexdigest()==h
    write(out/'verified.json',{'bytes':archive.stat().st_size,'sha256':filehash(archive),'complete_score':all(f.is_file() and f.stat().st_size>0 for f in (w/'session-results'/n for n in ('result.json','fresh-publication-after.json','independent-replay.json','native-replay.json'))),'compact_file_count':len(files),'optional_rmeta_count':len(chosen),'all_priority_raw_retained':manifest['all_priority_raw_retained'],'maximum_bytes':fit})
if __name__=='__main__':export(Path(os.environ['GITHUB_WORKSPACE']).resolve())
