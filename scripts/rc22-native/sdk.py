"""Build, export or fully read back one native source-built SDK with both Cargo readers."""
import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *

def log_run(cmd,root,log,env=None):
    with log.open('xb') as f:
        proc=subprocess.run(list(map(str,cmd)),cwd=root,env=env,stdout=f,stderr=subprocess.STDOUT)
    if proc.returncode:
        with log.open('rb') as f:
            f.seek(max(0,log.stat().st_size-15000));print(f.read().decode(errors='replace'),flush=True)
        proc.check_returncode()

def freeze(stage,dest,repo,host_):
    """Copy the actual native runtime and the checked standard-library source, excluding compiler-checkout aliases."""
    target=Path('lib/rustlib')/host_
    for d in ('bin','lib','lib/rustlib'): (dest/d).mkdir(parents=True,exist_ok=True)
    for n in ('rustc','rustdoc'):
        require((stage/'bin'/n).is_file(),n)
        shutil.copy2(stage/'bin'/n,dest/'bin'/n)
    for q in (stage/'lib').iterdir():
        if q.is_file():shutil.copy2(q,dest/'lib'/q.name)
    for sub in ('lib','bin','codegen-backends'):
        src=stage/target/sub
        if src.is_dir():shutil.copytree(src,dest/target/sub,symlinks=False)
    for n in ('core','std','alloc','proc_macro','test'):
        require(any((dest/target/'lib').glob('lib'+n+'-*.rlib')),n)
    shutil.copytree(repo/'library',dest/'lib/rustlib/src/rust/library',symlinks=True,ignore=shutil.ignore_patterns('.git'))
    require(not any(q.is_symlink() for q in dest.rglob('*')),'unexpected alias in exported SDK')

def rows(path):
    for line in path.read_bytes().splitlines():
        if line.startswith(b'{'):yield json.loads(line)

def build(root):
    h=host();repo=root/'rust';report=root/'reports';stage=repo/'build'/h/'stage1'
    require(shutil.disk_usage(root).free>32*2**30,'need 32 GiB free before bootstrap')
    require(git(repo,'rev-parse','HEAD')==RUST and git(repo,'rev-parse','HEAD^{tree}')==RTREE,'wrong staged source')
    require(git(repo/'library/backtrace','rev-parse','HEAD')=='d902726a1dcdc1e1c66f73d1162181b5423c645b','wrong backtrace')
    flags=['--ci','false','--set','build.submodules=false','--set','rust.channel=dev','--set','rust.omit-git-hash=false','--set','rust.debug-assertions=false','--set','rust.lto=off','--set','llvm.download-ci-llvm=true']
    n='4' if h==APPLE else '8';cmd=[sys.executable,'x.py',*flags,'build','--stage','1','-j'+n,'--host',h,'--target',h,'compiler/rustc','library','src/tools/rustdoc']
    log_run(cmd,repo,report/'bootstrap.log')
    require(not git(repo,'status','--porcelain','--untracked-files=no'),'bootstrap changed tracked source')
    kit=root/'kit';sdk=kit/'sdk';freeze(stage,sdk,repo,h)
    signed=root/'packages/sdk-21';prov=read(root/'packages/receipts/21/custody.json')
    installed=read(root/'packages/receipts/21/installed.json');native=[]
    wild=Path('lib/rustlib')/h/'bin/wild-ld/ld.bfd'
    if h==GNU:
        require(sha(signed/wild)==installed[str(wild)]==WILD,'different signed Wild')
        (sdk/wild).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(signed/wild,sdk/wild)
        native.append({'kind':'bundled-wild','path':str(wild),'sha256':sha(sdk/wild),'version':run([sdk/wild,'--version']),'source_archive':prov['archive_sha256']})
    else:
        require(not (signed/wild).exists() and not (sdk/wild).exists(),'unexpected Darwin Wild')
        ld=Path(run(['/usr/bin/xcrun','-f','ld'])).resolve(strict=True)
        native.append({'kind':'xcode-ld','path':str(ld),'sha256':sha(ld),'toolchain':run(['/usr/bin/xcodebuild','-version']),'source_archive':prov['archive_sha256']})
    shutil.copy2(signed/'bin/cargo',sdk/'bin/cargo')
    build_env=root/'cargo-build';build_env.mkdir();e=context(build_env,sdk)
    e.update(CFG_RELEASE='1.99.0-dev',CFG_RELEASE_CHANNEL='dev')
    stamp=run(['rustc','+ohm','-vV'],env=e);doc=run(['rustdoc','+ohm','-vV'],env=e)
    require(('commit-hash: '+RUST) in stamp and ('host: '+h) in stamp and ('commit-hash: '+RUST) in doc,('unknown native source',stamp,doc))
    driver,=list((sdk/'lib').glob('librustc_driver*'));cargos={}
    csrc=root/'cargo-source';frozen=read(report/'cargo-source.json')
    for role,(rev,tree) in ROLES.items():
        git(csrc,'checkout','--detach','-q',rev)
        require(git(csrc,'rev-parse','HEAD^{tree}')==tree and not git(csrc,'status','--porcelain'),'dirty Cargo source')
        dest=kit/'roles'/role/'cargo';dest.parent.mkdir(parents=True)
        for name in ('target','shared'):
            current=build_env/name
            if current.exists():current.rename(build_env/('completed-pinned-'+name))
        c=['cargo','+ohm','-Zohm-defaults=no']
        log_run([*c,'fetch','--locked','--target',h],csrc,report/(role+'-fetch.log'),e)
        cmd_c=[*c,'build','--release','--offline','--locked','-p','cargo','--bin','cargo','--features','all-static,ohm-defaults','-j'+n,'--message-format=json']
        log_run(cmd_c,csrc,report/(role+'-build.log'),e)
        parsed=list(rows(report/(role+'-build.log')))
        leaf,=[r for r in parsed if r['reason']=='compiler-artifact' and r['target']['kind']==['bin'] and r['target']['name']=='cargo']
        binary=Path(leaf['executable'])
        require(not leaf['fresh'] and {'ohm-defaults','all-static'}<=set(leaf['features']) and binary.resolve().is_relative_to(build_env/'target'),'wrong native Cargo leaf')
        require(parsed[-1]=={'reason':'build-finished','success':True},'incomplete native Cargo')
        shutil.copy2(binary,dest)
        version=run([dest,'-Vv'],env=e)
        require(('commit-hash: '+rev) in version and 'release: 1.99.0-dev' in version and ('host: '+h) in version,('Cargo stamp',version))
        cargos[role]={**frozen['roles'][role],'path':str(dest.relative_to(kit)),'sha256':sha(dest),'version_verbose':version,'release_channel':'dev','features':leaf['features'],'command':cmd_c,'log_sha256':sha(report/(role+'-build.log'))}
    (sdk/'bin/cargo').unlink();os.link(kit/cargos['pinned']['path'],sdk/'bin/cargo')
    files={str(q.relative_to(kit)):member(q) for q in sorted(kit.rglob('*')) if q.is_file()}
    out=root/'export';out.mkdir();save(out/'members.json',files)
    with subprocess.Popen(['zstd','-q','-T3','-3','-o',str(out/'kit.tar.zst')],stdin=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdin,mode='w|',dereference=True) as ar:
            for name in files:ar.add(kit/name,arcname=name,recursive=False)
        z.stdin.close();require(z.wait()==0,'zstd export')
    release=HERE/'source/22.json';manifest=read(release)
    require(sha(release)=='9a97fdf254dd8eca4a861689bcd113bc7bbfe8760ad3e99a92aca4764086fc02' and manifest['sources']['cargo']['revision']==ROLES['pinned'][0] and manifest['sources']['rust']['revision']==RUST and manifest['bundled_tools']['wild']['version']=='0.11.0','different packaging pins')
    receipt={'schema':1,'packaging':{'commit':'8b2380c1aa9d1707441e79fc549f156516f1aced','path':'toolchains/1.99.0/22.json','git_blob':'006b822e93d0023a89978332e3825bd78ad988cc','sha256':sha(release)},'source_qualification':'source-built native stage1; Cargo release profile with no distribution PGO','qa':job(),
             'rust':{**read(report/'rust-source.json'),'host':h,'driver_path':str(driver.relative_to(kit)),'driver_sha256':sha(driver),
                     'rustc_path':'sdk/bin/rustc','rustc_sha256':sha(sdk/'bin/rustc'),'version_verbose':stamp,'rustdoc_sha256':sha(sdk/'bin/rustdoc'),'rustdoc_verbose':doc,'bootstrap':list(map(str,cmd)),'bootstrap_sha256':sha(report/'bootstrap.log'),
                     'stage0':{n:sha(repo/'build'/h/'stage0/bin'/n) for n in ('rustc','cargo')}},
             'cargos':cargos,'native_linkers':native,'members_sha256':sha(out/'members.json'),'kit_sha256':sha(out/'kit.tar.zst'),'kit_bytes':(out/'kit.tar.zst').stat().st_size}
    save(out/'receipt.json',receipt);print('export',h,sha(out/'receipt.json'),len(files),flush=True)

def reopen(bundle,dest):
    """Only create enrolled regular paths in an empty directory. Hash both compressed and decoded bytes."""
    j=read(bundle/'receipt.json');index=read(bundle/'members.json');pack=bundle/'kit.tar.zst';h=host()
    require(j['schema']==1 and j['rust']['commit']==RUST and j['rust']['tree']==RTREE and j['rust']['host']==h,'wrong native SDK')
    require(sha(pack)==j['kit_sha256'] and pack.stat().st_size==j['kit_bytes'] and sha(bundle/'members.json')==j['members_sha256'],'untrusted kit or member list')
    require(set(j['cargos'])==set(ROLES),'different Cargo roles')
    for role,(head,tree) in ROLES.items():
        c=j['cargos'][role];require((c['commit'],c['tree'],c['release_channel'])==(head,tree,'dev') and c['path']=='roles/'+role+'/cargo' and c['sha256']==index[c['path']]['sha256'],'Cargo role changed')
    require(index['sdk/bin/cargo']['sha256']==j['cargos']['pinned']['sha256'] and index['sdk/bin/rustc']['sha256']==j['rust']['rustc_sha256'] and index[j['rust']['driver_path']]['sha256']==j['rust']['driver_sha256'],'native identities changed')
    dest.mkdir();seen=set()
    with subprocess.Popen(['zstd','-q','-dc',pack],stdout=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdout,mode='r|') as ar:
            for item in ar:
                name=item.name;p=PurePosixPath(name)
                require(p.as_posix()==name and not p.is_absolute() and '..' not in p.parts and p.parts[0] in ('roles','sdk') and name in index and name not in seen and item.isreg(),'unsafe archive member')
                seen.add(name);m=index[name];require(item.size==m['bytes'] and item.mode==m['mode'],name)
                out=dest/p;out.parent.mkdir(parents=True,exist_ok=True)
                with out.open('xb') as f:shutil.copyfileobj(ar.extractfile(item),f)
                out.chmod(item.mode);require(member(out)==m,name)
        z.stdout.read();require(z.wait()==0 and seen==set(index),'incomplete kit')
    return j

if __name__=='__main__':
    a=argparse.ArgumentParser();s=a.add_subparsers(dest='kind',required=True)
    b=s.add_parser('build');b.add_argument('root',type=Path)
    b=s.add_parser('reopen');b.add_argument('bundle',type=Path);b.add_argument('dest',type=Path)
    args=a.parse_args()
    if args.kind=='build':build(args.root.resolve())
    else:reopen(args.bundle.resolve(),args.dest.resolve())
