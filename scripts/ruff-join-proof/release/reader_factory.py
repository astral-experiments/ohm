"""Reuse independently authenticated P/pre-reader Cargo, then build the actual v5 reader."""
from pathlib import Path
import json,os,shutil,subprocess,zipfile

BASE=Path(__file__).resolve().parent
REG=json.loads((BASE/'reader-registration.json').read_bytes())

def acquire(sdk):
    prior_zip=sdk.root/'prior-cargo.zip'
    env={k:os.environ[k]for k in ('PATH','HOME')};env['GH_TOKEN']=os.environ['OHM_SDK_READ_TOKEN']
    with prior_zip.open('wb')as out:
        subprocess.run(['gh','api',f"repos/astral-experiments/ohm/actions/artifacts/{REG['archive_id']}/zip"],check=True,stdout=out,env=env)
    assert prior_zip.stat().st_size==REG['archive_size'] and sdk.hf(prior_zip)==REG['archive_sha256']

def select(sdk,root,git,bodies,receipts):
    reg=REG['candidate'];overlay=BASE.parent/'fix/reader/overlay.bundle'
    assert sdk.hf(overlay)==reg['sha256'] and REG['prior']['release-child']['cargo_source']==reg['parent']
    git('fetch',str(overlay),'HEAD:refs/qa/consumed-input-reader')
    assert git('rev-parse',reg['source']+'^')==reg['parent'] and git('rev-parse',reg['source']+'^{tree}')==reg['tree']
    prior_zip=sdk.root/'prior-cargo.zip'
    assert prior_zip.stat().st_size==REG['archive_size'] and sdk.hf(prior_zip)==REG['archive_sha256']
    with zipfile.ZipFile(prior_zip)as z:
        old=json.loads(z.read('release-factories.json'))
        for before,now in [('release-parent','release-parent'),('release-child','pre-reader')]:
            spec=REG['prior'][before];assert all(old[before][k]==v for k,v in spec.items())
            dst=sdk.proof/('cargo-'+now)
            with z.open('cargo-'+before)as src,dst.open('wb')as out:shutil.copyfileobj(src,out)
            dst.chmod(0o755);assert dst.stat().st_size==spec['bytes'] and sdk.hf(dst)==spec['sha256']
            assert spec['cargo_source'] in subprocess.check_output([dst,'-vV'],text=True)
            bodies[now]=dst;receipts[now]={**old[before],'authenticated_prior_run':REG['prior_run']}
    sdk.put(sdk.proof/'release-factories.json',receipts)
    return [('release-child',reg['source'])]

def files(roots,sdk):
    records={}
    for role,root in roots:
        for p in root.rglob('dep-*'):
            if not p.is_file() or not any(v in ('fingerprint','.fingerprint')for v in p.parts):continue
            with p.open('rb')as f:head=f.read(6)
            if len(head)!=6 or head[:5]!=bytes.fromhex('01000000ff'):continue
            key=role+'/'+str(p.relative_to(root));assert key not in records
            records[key]={'version':head[5],'bytes':p.stat().st_size,'sha256':sdk.hf(p)}
    assert records
    return records
