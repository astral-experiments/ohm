"""Acquire distinct, immutable upstream/signed/strict SDK receivers; leave existing donors untouched."""
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tomllib
import tarfile
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
import sdk

BASE=Path(__file__).resolve().parent.parent
SIGNED='abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a'
STRICT='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'
def stock():
    sdk.ROOT.mkdir(); out=sdk.ROOT/'receipt';out.mkdir();record={}
    table=sdk.load(BASE/'ohm-aarch64-registers/stock-components.json')
    vers='b940084d7eb6a299eb4bfeb8e34901bc051e7ac4';host='x86_64-unknown-linux-gnu';target='aarch64-unknown-linux-gnu'
    def fetch(url,path):
        assert url.startswith('https://static.rust-lang.org/dist/')
        subprocess.run(['curl','--fail','--location','--silent','--show-error','--retry','3','-o',str(path),url],check=True)
    with tempfile.TemporaryDirectory(dir=sdk.ROOT) as temp:
        tmp=Path(temp);manifest=tmp/'channel.toml';fetch('https://static.rust-lang.org/dist/channel-rust-1.99.0.toml',manifest)
        assert sdk.sha(manifest)=='ce6dddc886364f8d786514771212cebe9b731ba82d6b859951c6b0ccc516b6a2'
        raw=tomllib.loads(manifest.read_text());assert len(table)==4
        for name,registered in table.items():
            triple=host if name.endswith(host) else target;pkg=name.removesuffix('-'+triple)
            body=raw['pkg'][pkg];row=body['target'][triple]
            assert body['git_commit_hash']==registered['commit']==vers and (row['xz_url'],row['xz_hash'])==(registered['url'],registered['sha256'])
            archive=tmp/row['xz_url'].rsplit('/',1)[1];fetch(row['xz_url'],archive);assert sdk.sha(archive)==row['xz_hash']
            subprocess.run(['tar','-xJf',str(archive),'-C',str(tmp)],check=True);folder=tmp/archive.name.removesuffix('.tar.xz')
            subprocess.run(['sh',str(folder/'install.sh'),'--prefix='+str(sdk.SDK),'--disable-ldconfig'],cwd=folder,check=True,stdout=subprocess.DEVNULL)
            record[name]={'sha256':row['xz_hash'],'size':archive.stat().st_size,'commit':vers,'url':row['xz_url']}
    cargo=sdk.SDK/'bin/cargo';driver,=(sdk.SDK/'lib').glob('librustc_driver*.so')
    table={str(f.relative_to(sdk.SDK)):sdk.identity(f) for f in sorted(sdk.SDK.rglob('*')) if f.is_file()}
    cargo_v=subprocess.check_output([cargo,'-Vv']).decode();rust_v=subprocess.check_output([sdk.SDK/'bin/rustc','-vV']).decode()
    assert '5f94df478' in cargo_v and vers in rust_v
    sdk.save(out/'sdk.json',{'role':'upstream','source':{'reviewed':vers,'source':vers,'receiver':'5f94df478'},'driver_path':str(driver.relative_to(sdk.SDK)),'files':table,'components':record,'cargo_vv':cargo_v,'rustc_vv':rust_v})
def restore_signed(target):
    # The original signed Cargo bytes, release checksum and manifest were verified by ingress.sh when reconstructing this exact same capsule.
    ar=Path(os.environ['CENSUS_PARENT']).parent/'inputs/versioned/sdk.tar.zst'
    assert sdk.sha(ar)=='e64597a904354972d245e108bc2887a68c91dd1908f10533a4bf05872b9b8b06'
    getter=subprocess.Popen(['zstd','-q','-d','-c',ar],stdout=subprocess.PIPE)
    seen=[]
    with tarfile.open(fileobj=getter.stdout,mode='r|') as tar:
        for member in tar:
            if member.name.removeprefix('./')=='objects/'+SIGNED:
                assert member.isfile()
                with target.open('xb') as f:shutil.copyfileobj(tar.extractfile(member),f)
                seen.append(member.name.removeprefix('./'))
    getter.stdout.read();getter.stdout.close()
    assert getter.wait()==0 and seen==['objects/'+SIGNED] and sdk.sha(target)==SIGNED;target.chmod(0o755)
    return {'source':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','signed_archive':'ohm-1.99.0-20-x86_64-unknown-linux-gnu','original_capsule_sha256':sdk.sha(ar)}
def main(role):
    if role=='upstream':stock();return
    compiler='C' if role=='strict-C' else 'P'
    sdk.prepare(compiler,13018006260 if compiler=='C' else 0,'a6bfc63d174184cf46ef452323c30ef2520f455da866be6998400d55f4d63582' if compiler=='C' else '')
    prior=sdk.ROOT/'receipt/sdk.json';record=sdk.load(prior);prior.rename(sdk.ROOT/'receipt/donor-sdk.json')
    exe=sdk.SDK/'bin/cargo';tmp=exe.with_suffix('.new')
    if role.startswith('signed'):
        provenance=restore_signed(tmp)
    else:
        assert role in ('strict-P','strict-C')
        fn=runpy.run_path(str(BASE/'ohm-aarch64-fallback/acquire.py'))
        out=sdk.ROOT/'strict-physical';receipt=sdk.ROOT/'receipt/strict-original.json'
        fn['acquire']('gh',receipt,out);provenance=sdk.load(receipt)
        assert provenance['cargo']==STRICT and sdk.sha(out/'cargo')==STRICT
        shutil.copy2(out/'cargo',tmp)
    tmp.replace(exe);record['files']['bin/cargo']=sdk.identity(exe)
    sdk.verify(sdk.SDK,record['files']);record.update(role=role,receiver=provenance)
    version=subprocess.check_output([exe,'-Vv']).decode();assert ('2d44bd4' if role.startswith('signed') else '735e1528') in version
    record['receiver_version']=version;sdk.save(prior,record)
if __name__=='__main__':main(sys.argv[1])
