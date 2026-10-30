"""Authenticate both registered SDKs and select one compiler at a stable absolute path."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

DIR=Path(__file__).resolve().parent
sys.path[:0]=[str(DIR.parent/'ohm-gnu-ty-input-census'),str(DIR.parent/'ohm-gnu-syscall/source-rebuild')]
import census
from rebuild import MEMBERS, patched_record

BOOT=41138808306
BOOT_HEAD='f251bcb417be911fc3ed9c4814b17ffa7b360c28'
REPO='astral-experiments/ohm'
SOURCE=json.loads((DIR/'source/source.json').read_text())['roles']
DRIVER=MEMBERS['driver_path']

def restore():
    gh=lambda endpoint: json.loads(subprocess.check_output(['gh','api','repos/'+REPO+'/actions/'+endpoint]))
    job=gh('runs/'+str(BOOT))
    assert (job['head_sha'],job['head_branch'],job['event'],job['status'],job['conclusion'])==(BOOT_HEAD,'charlie/qa-gnu-atomic-ruff-db','workflow_dispatch','completed','success')
    artifacts=gh('runs/'+str(BOOT)+'/artifacts')['artifacts']
    product,=[r for r in artifacts if r['name']=='gnu-atomic-registered-compiler']
    assert not product['expired'] and product['workflow_run']['id']==BOOT and product['workflow_run']['head_sha']==BOOT_HEAD
    root=Path(os.environ['RUNNER_TEMP'])/'atomic-subjects';root.mkdir()
    parent=Path(os.environ['CENSUS_SDK']).resolve(strict=True)
    candidate=root/'candidate-sdk';shutil.copytree(parent,candidate,copy_function=os.link)
    with tempfile.TemporaryDirectory(dir=root) as scratch:
        zip_path=Path(scratch)/'transfer.zip'
        with zip_path.open('xb') as f:
            subprocess.run(['gh','api',f"repos/{REPO}/actions/artifacts/{product['id']}/zip"],stdout=f,check=True)
        assert 'sha256:'+census.sha(zip_path)==product['digest']
        with zipfile.ZipFile(zip_path) as z:
            assert sorted(z.namelist())==['atomic-candidate.json','driver.zst']
            z.extractall(scratch)
        rec=json.loads((Path(scratch)/'atomic-candidate.json').read_text())
        assert rec['source']==SOURCE['candidate']['source'] and rec['tree']==SOURCE['candidate']['tree']
        assert rec['reviewed_source']==SOURCE['candidate']['reviewed'] and rec['parent']==SOURCE['parent']['source']
        assert rec['driver_path']==DRIVER and rec['unchanged_members']==118 and rec['parent_driver']==patched_record()['driver']
        assert rec['driver']!=rec['parent_driver'] and census.sha(Path(scratch)/'driver.zst')==rec['compression']
        driver=candidate/DRIVER;tmp=driver.with_name('atomic-driver.installing')
        subprocess.run(['zstd','-qd',Path(scratch)/'driver.zst','-o',tmp],check=True)
        tmp.chmod(rec['driver'][2]);tmp.replace(driver)
    for role,kit,seal in [('P',parent,rec['parent_driver']),('C',candidate,rec['driver'])]:
        roster=MEMBERS['common']|{DRIVER:seal}
        found={f.relative_to(kit).as_posix():[census.sha(f),f.stat().st_size,f.stat().st_mode&0o777]
               for f in kit.rglob('*') if f.is_file()}
        assert found==roster and len(found)==119,role
        census.save(root/(role+'-sdk.json'),found)
    census.save(root/'atomic-candidate.json',rec)
    census.save(root/'origin.json',{'head':BOOT_HEAD,'run':BOOT,'artifact':product['id'],'digest':product['digest'],
                                    'parent':str(parent),'candidate':str(candidate)})
    return root

def preparation():
    root=Path(os.environ['RUNNER_TEMP'])/'atomic-subjects'
    origin=json.loads((root/'origin.json').read_text())
    subjects={r:Path(origin[k]) for r,k in [('P','parent'),('C','candidate')]}
    stable=root/'stable-sdk'
    if not stable.exists():shutil.copytree(subjects['P'],stable,copy_function=os.link)
    return root,subjects,stable

def switch(role):
    root,subjects,stable=preparation()
    expected=json.loads((root/(role+'-sdk.json')).read_text())[DRIVER]
    dest=stable/DRIVER;src=subjects[role]/DRIVER
    if not dest.samefile(src):
        new=dest.with_name('atomic-next-driver');os.link(src,new);new.replace(dest)
    assert [census.sha(dest),dest.stat().st_size,dest.stat().st_mode&0o777]==expected
    return stable

def acquire(role,cmd):
    from screen import OLD,NEW,TREES,LOCK,FILE
    stable=switch('P')
    os.environ['CENSUS_SDK']=str(stable)
    work,out,src,env=census.acquire(OLD,NEW,TREES,LOCK,[FILE],cmd)
    switch(role)
    live=Path(census.command(['rustup','which','--toolchain','ohm','rustc'],src,env))
    assert live.samefile(stable/'bin/rustc') and census.qualify.rt.SDK==stable
    rec=json.loads((out/'enrolled.json').read_text())
    (out/'enrolled.json').rename(out/'fetch-sdk.json')
    tuple_=json.loads((preparation()[0]/(role+'-sdk.json')).read_text())[DRIVER]
    rec['compiler']={**SOURCE['parent' if role=='P' else 'candidate'],'driver':tuple_}
    rec['rustc']=census.command(['rustc','+ohm','-vV'],src,env)
    assert rec['cargo_sha']==MEMBERS['common']['bin/cargo'][0]
    census.save(out/'enrolled.json',rec)
    return work,out,src,env

if __name__=='__main__':restore()
