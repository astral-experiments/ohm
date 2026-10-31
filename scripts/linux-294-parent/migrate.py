"""Move two already poisoned native Ruff targets to the strict Cargo in place."""
from pathlib import Path
import gzip,hashlib,json,os,shutil,subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import capture as c
HERE=Path(__file__).resolve().parent
EDIT=json.loads((HERE/'edit.json').read_bytes());SRC=c.R/EDIT['path'];PATCH=HERE/'historical-alias.patch'
SIGNED_MTIME=(Path(c.CFG['signed_sdk'])/'bin/cargo').stat().st_mtime_ns
def identity(path):
    s=path.stat();return [s.st_dev,s.st_ino]
def activate(role):
    binary,commit,sha=c.ROLES[role];exe=c.SDK/'bin/cargo';temp=exe.with_name('cargo.qa.next')
    assert not temp.exists();shutil.copyfile(binary,temp);temp.chmod(0o755)
    os.utime(temp,ns=(SIGNED_MTIME,SIGNED_MTIME));temp.replace(exe)
    assert exe.resolve()==exe and c.digest(exe)==sha and exe.stat().st_mtime_ns==SIGNED_MTIME
    v=subprocess.check_output([c.PROXY/'cargo','+ohm','-Vv'],env=c.ENV,text=True)
    assert v==c.CFG['roles'][role]['version'] and 'commit-hash: '+commit in v
    return dict(role=role,path=str(exe),inode=identity(exe),mtime=SIGNED_MTIME,sha256=sha)
def record(base,phase,role,state):
    b=c.phase(base,phase);enc=[];obj=c.rec/'objects';obj.mkdir(exist_ok=True)
    for top in [c.W/'shared',c.W/'target']:
        for file in sorted(top.rglob('dep-lib-chacha20')):
            if file.parent.parent.name!='.fingerprint':continue
            blob=file.read_bytes();key=c.digest(file)
            out=obj/(key+'.gz')
            if not out.exists():c.gz(out,blob)
            enc.append(dict(path=str(file),sha256=key))
    result=dict(cargo=role,provider=state,result=b,encoded=enc,
                roots={str(p):identity(p) for p in (c.W,c.W/'target',c.W/'shared',c.SDK,c.SDK/'bin/rustc',next((c.SDK/'lib').glob('librustc_driver-*')),c.SIDE.with_name('ld.bfd'))},
                generator_source=c.digest(SRC))
    c.jd(base/phase/'migration.json',result);return result
def main():
    c.setup();assert c.digest(PATCH)==EDIT['patch'] and c.digest(SRC)==EDIT['old']
    orig=SRC.read_bytes();st=SRC.stat();summary={}
    for state in ('83','bad'):
        base=c.rec/state;base.mkdir();seq={}
        with c.installation():
            signed=activate('signed');absent=c.side('absent')
            seq['signed-empty-absent']=record(base,'signed-empty-absent',signed,absent)
            seq['signed-repeat-absent']=record(base,'signed-repeat-absent',signed,absent)
            side=c.side(state)
            seq['signed-poisoned']=record(base,'signed-poisoned',signed,side)
            before={str(p):identity(p) for p in (c.W,c.W/'target',c.W/'shared',c.SIDE)}
            strict=activate('strict')
            assert all(identity(Path(k))==v for k,v in before.items()) and c.digest(c.SIDE)==side['sha256']
            seq['strict-migration']=record(base,'strict-migration',strict,side)
            seq['strict-repeat']=record(base,'strict-repeat',strict,side)
            if state=='83':
                changed=c.side('47',True);seq['strict-same-inode-47']=record(base,'strict-same-inode-47',strict,changed)
                bad=c.side('bad',True);seq['strict-same-inode-bad']=record(base,'strict-same-inode-bad',strict,bad)
            seq['strict-repair-absent']=record(base,'strict-repair-absent',strict,c.side('absent'))
            seq['strict-repair-repeat']=record(base,'strict-repair-repeat',strict,None)
        summary[state]=seq
    for role in ('signed','strict'):
        group='empty-'+role;base=c.rec/group;base.mkdir();seq={};binary=activate(role)
        for state in ('absent','83','47','bad'):
            with c.installation():seq[state]=record(base,state,binary,c.side(state))
        summary[group]=seq
    c.side('absent');strict=activate('strict');base=c.rec/'edit';base.mkdir();seq={}
    with c.installation():
        seq['original']=record(base,'original',strict,None)
        subprocess.run(['git','apply','--check',str(PATCH)],check=True,cwd=c.R)
        subprocess.run(['git','apply',str(PATCH)],check=True,cwd=c.R)
        assert c.digest(SRC)==EDIT['edited'];edited=SRC.read_bytes()
        seq['historical']=record(base,'historical',strict,None)
        seq['historical-repeat']=record(base,'historical-repeat',strict,None)
        SRC.write_bytes(edited+b'\nfn migration_typecheck_guard() { unavailable_ohm_migration_guard(); }\n')
        seq['invalid']=record(base,'invalid',strict,None)
        SRC.write_bytes(edited);seq['repair-edited']=record(base,'repair-edited',strict,None)
        SRC.write_bytes(orig);seq['restored']=record(base,'restored',strict,None)
    summary['edit']=seq;base=c.rec/'edit-empty';base.mkdir()
    with c.installation():
        SRC.write_bytes(edited);summary['edit-empty']={'independent':record(base,'independent',strict,None)}
    SRC.write_bytes(orig);os.utime(SRC,ns=(st.st_atime_ns,st.st_mtime_ns))
    assert c.digest(SRC)==EDIT['old'] and not subprocess.check_output(['git','diff','--name-only'],cwd=c.R)
    for group,seq in summary.items():c.jd(c.rec/group/'complete.json',seq)
    c.jd(c.rec/'complete.json',{k:c.digest(c.rec/k/'complete.json') for k in summary})
if __name__=='__main__':
    try:main()
    finally:
        if c.SIDE.exists() and c.SIDE.is_file() and not c.SIDE.is_symlink():c.SIDE.unlink()
