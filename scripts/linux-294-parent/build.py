"""Materialize and compile the adjacent Cargo commits on the same released Linux SDK."""
from pathlib import Path
import gzip, hashlib, json, os, shutil, subprocess, sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'cargo-diagnostic-fix'))
import materialize as source
sys.path.insert(0,str(HERE.parent/'gc-mount-evidence'))
from build_candidate import digest,run
P='7277e6cdaba44c43294a07c0661fc8e69fd8e3e7'
PT='7efe7adf79d91264b1276b0281253023f9b58749'
def build(root,pack):
    sdk=root/'sdk-21'; assert digest(sdk/'bin/cargo')=='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
    path=root/'cargo-source'
    child=source.tree(path,pack)
    assert child['commit']==source.BASE and child['mode_path_sha256_inventory']=='da5d8cde02be6fcd82b87b490b937224dcd46f8e72841343d9fe00ce16d253d1'
    slug=HERE/'294-forward.patch.gz';patch=gzip.decompress(slug.read_bytes())
    git=lambda *args,data=None:source.git(path,*args,data=data)
    git('apply','-R','--binary','--index','-',data=patch)
    assert git('write-tree').decode().strip()==PT
    body=(HERE/'immediate.commit').read_bytes();assert body.startswith(('tree '+PT+'\nparent ').encode())
    assert git('hash-object','-t','commit','-w','--stdin',data=body).decode().strip()==P
    (path/'.git/shallow').write_text(source.SEED+'\n'+P+'\n')
    git('update-ref','HEAD',P);git('fsck','--full','--strict','--no-progress')
    parent=dict(commit=P,tree=PT,**source.hash_files(path,P))
    cargo=['cargo','+ohm','-Zohm-defaults=no']
    shims=root/'shims';shims.mkdir();rustup=Path(shutil.which('rustup'))
    for n in ('cargo','rustc'):(shims/n).symlink_to(rustup)
    alias=root/'build-rustup/toolchains/ohm';alias.parent.mkdir(parents=True);alias.symlink_to(sdk,target_is_directory=True)
    (root/'home').mkdir()
    env={'HOME':str(root/'home'),'PATH':str(shims)+':/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','RUSTUP_HOME':str(alias.parent.parent),
         'RUSTUP_AUTO_INSTALL':'0','CARGO_HOME':str(root/'registry'),'CARGO_TARGET_DIR':str(root/'target'),
         'CARGO_BUILD_BUILD_DIR':str(root/'shared'),'CFG_RELEASE':'1.99.0-dev','CFG_RELEASE_CHANNEL':'dev'}
    dest=root/'deliver';dest.mkdir();reports=root/'reports';reports.mkdir()
    run([*cargo,'fetch','--locked','--target','x86_64-unknown-linux-gnu'],path,env,reports/'fetch')
    for role,proof in [('parent',parent),('matched294',child)]:
        if role=='matched294':
            # Both modes produce Cargo's git stamp at build-script time. Use an empty
            # private build and target at the same logical path for the second role.
            for old in (root/'target',root/'shared'):
                if old.exists():
                    assert old.parent==root and not old.is_symlink()
                    old.rename(root/('completed-parent-'+old.name))
            git('checkout','-q','--detach',source.BASE)
        assert git('status','--porcelain')==b'' and git('rev-parse','HEAD').decode().strip()==proof['commit']
        cmd=[*cargo,'build','--release','--offline','--locked','-p','cargo','--bin','cargo','--features','all-static,ohm-defaults','-j12','--message-format=json']
        invocation=run(cmd,path,env,reports/role)
        rows=[json.loads(l) for l in invocation.stdout.splitlines()]; leaf,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and r['target']['kind']==['bin']]
        assert not leaf['fresh'] and {'all-static','ohm-defaults'}<=set(leaf['features']) and rows[-1]=={'reason':'build-finished','success':True}
        binary=Path(leaf['executable']);assert binary.resolve().is_relative_to(root/'target')
        output=dest/role;shutil.copyfile(binary,output);output.chmod(0o755)
        version=subprocess.check_output([output,'-Vv'],env=env,text=True)
        (reports/(role+'-version.txt')).write_text(version)
        assert 'commit-hash: '+proof['commit'] in version and 'release: 1.99.0-dev' in version
        data={'role':role,'source':proof,'commit':proof['commit'],'version':version,'sha256':digest(output),'compiled':digest(binary),'features':leaf['features'],
              'command':cmd,'environment':env,'qa':os.environ['GITHUB_SHA'],'signed_sdk':json.loads((root/'receipts/21/installed.json').read_bytes())}
        assert data['sha256']==data['compiled']
        (dest/(role+'.json')).write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
        print(role,proof['commit'],data['compiled'],flush=True)
if __name__=='__main__':build(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
