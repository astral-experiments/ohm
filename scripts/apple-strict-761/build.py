"""Reopen the strict two-parent tree, then build it using the native signed Apple SDK."""
from pathlib import Path
import gzip,json,os,platform,shutil,subprocess,sys
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent/'gc-mount-evidence'))
import build_candidate as lib
C='761ea115605c34f11a1cd29afd68812c1e1359dd';T='19c379477ec24be16c82b952dc2e892c0563e2c7'
def build(root):
    root=root.resolve();sdk=root/'sdk-21';h=lib.digest;desc=json.loads((root/'receipts/21/installed.json').read_bytes())
    assert platform.machine()=='arm64' and platform.system()=='Darwin'
    assert desc['bin/rustc']==h(sdk/'bin/rustc')=='b5f538b1ff22cee592ece6736c692ccae982ca376faf669d939fb904ac760a5b'
    assert desc['bin/cargo']==h(sdk/'bin/cargo')=='e38550244b4d17a58c58be69940ee1fd94b6cfe10eb2c0e660ce5b287eca28a7'
    objects=D.parent/'gc-mount-evidence/candidate-source';spec=json.loads((objects/'spec.json').read_bytes())
    assert (spec['head'],spec['tree'])==(C,T)
    src=root/'source';proof=lib.strict_source(src,D.parent/'ohm-apple-zmij/cargo293/source.pack',objects,spec)
    assert proof['commit']==C and proof['tree']==T and proof['mode_path_sha256_inventory']==spec['inventory'] and proof['lock']==spec['lock_sha256']
    shims=root/'shims';shims.mkdir();rustup=Path(shutil.which('rustup'))
    for name in ('cargo','rustc'):(shims/name).symlink_to(rustup)
    alias=root/'build-rustup/toolchains/ohm';alias.parent.mkdir(parents=True);alias.symlink_to(sdk)
    home=root/'home';home.mkdir()
    reports=root/'build';reports.mkdir()
    env={k:os.environ[k] for k in ('USER','TMPDIR','DEVELOPER_DIR','SDKROOT','LOGNAME') if k in os.environ}
    env.update(HOME=str(home),PATH=str(shims)+':/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',LANG='en_US.UTF-8',RUSTUP_HOME=str(alias.parent.parent),
               CARGO_HOME=str(root/'registry'),CARGO_TARGET_DIR=str(root/'target'),CARGO_BUILD_BUILD_DIR=str(root/'shared'),RUSTUP_AUTO_INSTALL='0',CFG_RELEASE_CHANNEL='dev',CFG_RELEASE='1.99.0-dev')
    def command(args):return subprocess.check_output(args,cwd=src,env=env,text=True)
    sig=command(['cargo','+ohm','-Vv']);rust=command(['rustc','+ohm','-vV']);assert 'ohm-1.99.0-21' in sig and 'c79998a5cd143c445a4b2528f20953b176a65c5d' in rust
    triple='aarch64-apple-darwin';base=['cargo','+ohm','-Zohm-defaults=no']
    lib.run([*base,'fetch','--locked','--target',triple],src,env,reports/'fetch')
    cmd=[*base,'build','--release','--locked','--offline','--bin','cargo','--package','cargo','--features','all-static,ohm-defaults','-j8','--message-format=json']
    p=lib.run(cmd,src,env,reports/'compile')
    rows=[json.loads(r) for r in p.stdout.splitlines()];assert rows[-1]=={'reason':'build-finished','success':True}
    leaf,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['kind']==['bin'] and r['target']['name']=='cargo']
    assert not leaf['fresh'] and {'ohm-defaults','all-static'}<=set(leaf['features'])
    source=Path(leaf['executable']);assert source.resolve().is_relative_to(root/'target')
    out=root/'deliver';out.mkdir();cargo=out/'cargo';shutil.copyfile(source,cargo);cargo.chmod(0o755)
    v=command([cargo,'-Vv']);assert 'commit-hash: '+C+'\n' in v and 'release: 1.99.0-dev\n' in v and 'host: '+triple in v
    arch=command(['/usr/bin/lipo','-archs',cargo]);deps=command(['/usr/bin/otool','-L',cargo]);assert arch.strip()=='arm64' and str(root/'target') not in deps
    subprocess.run(['/usr/bin/codesign','--verify','--strict',cargo],check=True)
    xcode=Path(command(['xcrun','--find','ld']).strip()).resolve()
    record={'qa':os.environ['GITHUB_SHA'],'source':proof,'parents':spec['parents'],'features':leaf['features'],'version':v,'sha256':h(cargo),'compiled':h(source),
            'compiler':rust,'signed_cargo':sig,'signed_runtime':desc,'release':json.loads((root/'receipts/21/custody.json').read_bytes()),
            'arch':arch,'linkage':deps,'command':cmd,'env':env,'xcode_ld':[str(xcode),h(xcode)],'rows':len(rows)}
    assert record['compiled']==record['sha256']
    for d in (out,reports):(d/'build.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
    print(C,record['sha256'],arch.strip(),record['xcode_ld'],flush=True)
if __name__=='__main__':build(Path(sys.argv[1]))
