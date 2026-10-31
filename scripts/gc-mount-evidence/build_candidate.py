"""Compile the exact candidate from a verified fork-only source pack and released Rust."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'cargo-diagnostic-fix'))
import materialize

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(cmd,repo,env,out):
    result=subprocess.run(cmd,cwd=repo,env=env,capture_output=True,timeout=3600)
    for suffix,b in [('stdout',result.stdout),('stderr',result.stderr)]:
        with gzip.open(out.with_suffix('.'+suffix+'.gz'),'xb') as f:f.write(b)
    if result.returncode:print(result.stderr.decode(errors='replace')[-2500:],file=sys.stderr)
    assert result.returncode==0
    return result

def strict_source(dest, seed, specdir, spec):
    """Restore the signed source and both PR branches from their sealed Git objects."""
    original = materialize.tree(dest, seed)
    assert original['commit'] == materialize.BASE
    extra = (specdir / 'strict-candidate.pack').read_bytes()
    assert hashlib.sha256(extra).hexdigest() == spec['pack_sha256']
    git = materialize.git
    git(dest, 'index-pack', '--stdin', data=extra)
    assert git(dest, 'cat-file', '-t', spec['base_parent']) == b'commit\n'
    shallow = dest / '.git/shallow'
    assert set(shallow.read_text().splitlines()) == {materialize.SEED, materialize.BASE}
    shallow.write_text(spec['base_parent'] + '\n')
    git(dest, 'checkout', '--quiet', '--detach', spec['head'])
    assert git(dest, 'show', '-s', '--format=%P', 'HEAD').decode().split() == spec['parents']
    assert git(dest, 'rev-parse', materialize.BASE + '^').decode().strip() == spec['base_parent']
    assert git(dest, 'rev-parse', 'HEAD^^^').decode().strip() == spec['base_parent']
    assert git(dest, 'status', '--porcelain') == b''
    git(dest, 'fsck', '--no-progress', '--full', '--strict')
    return {'commit': git(dest, 'rev-parse', 'HEAD').decode().strip(),
            'tree': git(dest, 'rev-parse', 'HEAD^{tree}').decode().strip(),
            'source_pack': original['source_pack'], 'extra_pack': spec['pack_sha256'],
            'lock': digest(dest / 'Cargo.lock'), **materialize.hash_files(dest, spec['head'])}

def main(root,pack):
    specdir=HERE/'candidate-source';spec=json.loads((specdir/'spec.json').read_bytes())
    assert spec['parent']==materialize.BASE
    data=root/'build-cert';data.mkdir()
    native=root/'sdk-21';assert digest(native/'bin/cargo')=='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
    src=root/'source';tree=strict_source(src,pack,specdir,spec)
    assert tree['commit']==spec['head'] and tree['tree']==spec['tree'] and tree['mode_path_sha256_inventory']==spec['inventory']
    assert tree['lock']==spec['lock_sha256']
    rustup=Path(shutil.which('rustup'));home=root/'build-home';home.mkdir()
    alias=root/'build-rustup/toolchains/ohm';alias.parent.mkdir(parents=True);alias.symlink_to(native,target_is_directory=True)
    shims=root/'build-shims';shims.mkdir()
    for n in ('cargo','rustc'):(shims/n).symlink_to(rustup)
    env={'HOME':str(home),'PATH':str(shims)+':/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','RUSTUP_HOME':str(alias.parent.parent),
         'RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(root/'build-cargo'),'CARGO_TARGET_DIR':str(root/'build-target'),
         'CARGO_BUILD_BUILD_DIR':str(root/'build-shared'),'CFG_RELEASE':'1.99.0-dev','CFG_RELEASE_CHANNEL':'dev'}
    cargo=['cargo','+ohm','-Zohm-defaults=no']
    run([*cargo,'fetch','--locked','--target','x86_64-unknown-linux-gnu'],src,env,data/'fetch')
    argv=[*cargo,'build','--release','--offline','--locked','-p','cargo','--bin','cargo','--features','all-static,ohm-defaults','-j12','--message-format=json']
    p=run(argv,src,env,data/'compile')
    records=[json.loads(l) for l in p.stdout.splitlines()]
    assert records[-1]=={'reason':'build-finished','success':True}
    leaf,=[r for r in records if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and r['target']['kind']==['bin']]
    binary=Path(leaf['executable']);assert not leaf['fresh'] and binary.resolve().is_relative_to(root/'build-target') and {'ohm-defaults','all-static'}<=set(leaf['features'])
    deliver=root/'deliver';deliver.mkdir();out=deliver/'cargo';shutil.copyfile(binary,out);out.chmod(0o755)
    version=subprocess.check_output([out,'-Vv'],env=env,text=True);assert 'commit-hash: '+spec['head'] in version and 'release: 1.99.0-dev' in version
    proof={'tree':tree,'candidate':spec['head'],'parent':spec['parent'],'compiled':digest(binary),'delivered':digest(out),'version':version,
           'args':argv,'env':env,'signed_runtime':json.loads((root/'receipts/21/installed.json').read_bytes()),'features':leaf['features'],'qa':os.environ['GITHUB_SHA']}
    assert proof['compiled']==proof['delivered']
    for path in (deliver/'build.json',data/'build.json'):path.write_text(json.dumps(proof,sort_keys=True,indent=2)+'\n')
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
