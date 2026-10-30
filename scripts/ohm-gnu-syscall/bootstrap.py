"""Bootstrap a direct V child and require all other 118 selected SDK members to agree."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-linux'))
import runtime as rt

PARENT='8f42a1c11e66c2a55299914d5025e4fa7549ead4'
CHILD='6ae50e2d0139132d86d4fdf50648a4ddfcb2730e'
TREE='979169f06d795cbf0752bc6e56e1240dc41caeac'
STEPS=[
 ('ohm-aarch64-registers/transport','d3538b42a2dc56edb9bffbc9cc2373fb93c35054','5b86b3516db45ace6bbbdd536bbff9face291fbd'),
 ('ohm-aarch64-compact/transport','f2edebc7a23b809749fb0cc44dd6ac902ca448ff','c4205f70f7807a7309d0a56abc7d772cb18899c1'),
 ('ohm-aarch64-versioned/rust-transport',PARENT,'43cf560431e6d70ff01db3d4b9e50272153e9dfb'),
 ('ohm-gnu-syscall/source',CHILD,TREE)]

def git(src,*args,data=None):
    return subprocess.check_output(['git',*args],cwd=src,input=data).decode().strip()

def materialize(src):
    donor=HERE.parent/'ohm-apple-zmij/source-transport'
    subprocess.run(['sha256sum','--quiet','-c','SHA256SUMS'],cwd=donor,check=True)
    with (rt.LOG/'first-source.json').open('x') as out:
        subprocess.run([sys.executable,'-IB',donor/'prepare.py',src],check=True,stdout=out)
    last='444c0273a2e2bc0b161e988d43c882349bc2d7a6'
    git(src,'switch','--detach',last)
    for n,child,tree in STEPS:
        directory=HERE.parent/n
        commit=(directory/'commit').read_bytes();patch=gzip.decompress((directory/'source.patch.gz').read_bytes())
        assert commit.splitlines()[:2]==[('tree '+tree).encode(),('parent '+last).encode()]
        assert git(src,'hash-object','-t','commit','--stdin',data=commit)==child
        assert not git(src,'status','--porcelain','--untracked-files=no')
        git(src,'apply','--index','--binary','-',data=patch)
        assert git(src,'write-tree')==tree
        assert git(src,'hash-object','-w','-t','commit','--stdin',data=commit)==child
        git(src,'update-ref','--no-deref','HEAD',child,last)
        last=child
    identity=json.loads((HERE/'source/identity.json').read_text())
    assert (identity['source'],identity['parent'],identity['tree'])==(CHILD,PARENT,TREE)
    assert set(git(src,'diff','--name-only',PARENT,CHILD).splitlines())==set(identity['paths'])
    for path,want in identity['paths'].items():assert git(src,'rev-parse','HEAD:'+path)==want
    assert git(src,'rev-parse','HEAD:library')==git(src,'rev-parse',PARENT+':library')
    assert not git(src,'status','--porcelain','--untracked-files=no')
    rt.save(rt.LOG/'source.json',identity)

def stage(arguments,label):
    f=rt.LOG/(label+'.log')
    with f.open('xb') as log:
        p=subprocess.run([sys.executable,'x.py','--ci','false','--set','build.submodules=false','--set','rust.omit-git-hash=true',
            '--set','rust.debug-assertions=false','--set','rust.lto=off','--set','llvm.download-ci-llvm=true',
            '--set',f'target.{rt.TARGET}.cc=/usr/bin/aarch64-linux-gnu-gcc','--set',f'target.{rt.TARGET}.cxx=/usr/bin/aarch64-linux-gnu-g++',
            '--set',f'target.{rt.TARGET}.ar=/usr/bin/aarch64-linux-gnu-ar','--set',f'target.{rt.TARGET}.linker=/usr/bin/aarch64-linux-gnu-gcc',*arguments],
            cwd=rt.ROOT/'rust',stdout=log,stderr=subprocess.STDOUT)
    if p.returncode:
        print(f.read_text(errors='replace')[-6500:],flush=True);p.check_returncode()
    print(label,'passed',flush=True)

def export():
    base=json.loads((HERE.parent/'ohm-aarch64-portable-review/source/sdk-members.json').read_text())
    parent=base['roles']['M'];driver=base['driver_path'];assert parent['source']==PARENT
    expected=base['common']|{driver:parent['driver']}
    donor=Path(os.environ['CENSUS_PARENT']).resolve(strict=True)
    for name,(h,size,mode) in expected.items():
        p=donor/name;assert (rt.sha(p),p.stat().st_size,p.stat().st_mode&0o777)==(h,size,mode)
    manifest=rt.load(rt.LOG/'C-sdk.json')
    assert (manifest['source'],manifest['tree'])==(CHILD,TREE)
    rows=manifest['files'];assert set(rows)|set(rt.TOOLS)==set(expected) and not(set(rows)&set(rt.TOOLS))
    assert [k for k,v in rows.items() if v!=expected[k]]==[driver]
    sdk=rt.ROOT/'candidate-sdk'
    shutil.copytree(donor,sdk,copy_function=os.link)
    obj=rt.CAP/'objects'/rows[driver][0]
    tmp=sdk/(driver+'.new');shutil.copyfile(obj,tmp);tmp.chmod(rows[driver][2]);tmp.replace(sdk/driver)
    assert rt.sha(sdk/driver)==rows[driver][0] and rt.sha(donor/driver)==parent['driver'][0]
    table={'source':CHILD,'tree':TREE,'parent':PARENT,'driver_path':driver,'driver':rows[driver],'bootstrap':manifest['bootstrap'],'unchanged_members':118}
    rt.save(rt.LOG/'candidate.json',table)
    emit=rt.ROOT/'export';emit.mkdir()
    shutil.copyfile(rt.LOG/'candidate.json',emit/'candidate.json')
    subprocess.run(['zstd','-q','-T2','-3','-o',str(emit/'driver.so.zst'),str(sdk/driver)],check=True)
    rt.save(rt.LOG/'export.json',{'driver':rows[driver][0],'compressed':rt.sha(emit/'driver.so.zst'),'member':driver})

def restore(transfer):
    rt.room()
    base=rt.load(HERE.parent/'ohm-aarch64-portable-review/source/sdk-members.json')
    record=rt.load(transfer/'candidate.json')
    assert (record['source'],record['parent'],record['tree'])==(CHILD,PARENT,TREE)
    driver=base['driver_path']
    assert record['driver_path']==driver and record['unchanged_members']==118
    donor=Path(os.environ['CENSUS_PARENT']).resolve(strict=True)
    def verify(sdk,driver_row):
        expected=base['common']|{driver:driver_row}
        assert len(expected)==119 and {p.relative_to(sdk).as_posix() for p in sdk.rglob('*') if p.is_file()}==set(expected)
        for name,(hash_value,size,mode) in expected.items():
            f=sdk/name
            assert (rt.sha(f),f.stat().st_size,f.stat().st_mode&0o777)==(hash_value,size,mode),name
    verify(donor,base['roles']['M']['driver'])
    assert record['driver']!=base['roles']['M']['driver']
    sdk=rt.ROOT/'candidate-sdk'
    shutil.copytree(donor,sdk,copy_function=os.link)
    tmp=sdk/(driver+'.new')
    with tmp.open('xb') as f:
        subprocess.run(['zstd','-q','-dc',str(transfer/'driver.so.zst')],stdout=f,check=True)
    tmp.chmod(record['driver'][2])
    tmp.replace(sdk/driver)
    verify(sdk,record['driver'])
    rt.save(rt.LOG/'candidate.json',record)

def main():
    if len(sys.argv)==3 and sys.argv[1]=='restore':
        restore(Path(sys.argv[2]).resolve(strict=True))
        return
    rt.CHILD=CHILD;rt.room(sys.argv[1]=='build')
    src=rt.ROOT/'rust'
    if sys.argv[1]=='build':
        materialize(src)
        for label,target,parts in [('host',rt.HOST,['compiler/rustc','library']),('target',rt.TARGET,['library'])]:
            stage(['build','--stage','1','-j8','--host',rt.HOST,'--target',target,*parts],label)
            rt.freeze('C',label)
        export()
    else:
        assert sys.argv[1:] == ['host-test'] and git(src,'rev-parse','HEAD')==CHILD
        stage(['test','--stage','1','-j8','--host',rt.HOST,'--target',rt.HOST,'tests/run-make/ohm-checked-dep-info',
               'tests/run-make/ohm-relink-assembler-inputs'],'host-regression')

if __name__=='__main__':main()
