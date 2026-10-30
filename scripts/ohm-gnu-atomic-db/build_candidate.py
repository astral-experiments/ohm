"""Build the registered compiler diff after binding it to the rebased PR source."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE.parent/'ohm-gnu-syscall/source-rebuild'),str(HERE.parent/'ohm-gnu-syscall')]
from bootstrap import git, materialize, rt, stage
from rebuild import MEMBERS, patched_record

def build():
    spec=json.loads((HERE/'source/source.json').read_text())
    p,c=(spec['roles'][n] for n in ('parent','candidate'))
    rt.room(True)
    rt.release()
    src=rt.ROOT/'rust'
    materialize(src)
    def check(role):
        assert git(src,'rev-parse','HEAD')==role['source']
        assert git(src,'rev-parse','HEAD^{tree}')==role['tree']
        for n,h in (role['product']|role['paths']).items(): assert git(src,'rev-parse','HEAD:'+n)==h
        assert not git(src,'status','--porcelain','--untracked-files=no')
    check(p)
    diff=gzip.decompress((HERE/'source/candidate.patch.gz').read_bytes())
    obj=(HERE/'source/candidate.commit').read_bytes()
    assert hashlib.sha256(diff).hexdigest()==spec['patch_sha256']
    assert obj.splitlines()[:2]==[('tree '+c['tree']).encode(),('parent '+p['source']).encode()]
    git(src,'apply','--index','--binary','-',data=diff)
    assert git(src,'write-tree')==c['tree']
    assert git(src,'hash-object','-w','-t','commit','--stdin',data=obj)==c['source']
    git(src,'update-ref','--no-deref','HEAD',c['source'],p['source'])
    check(c)
    assert git(src,'diff','--name-only',p['source'],c['source']).splitlines()==sorted(c['paths'])
    rt.save(rt.LOG/'reviewed-and-built.json',spec)
    rt.CHILD=c['source']
    for part,target,what in [('host',rt.HOST,['compiler/rustc','library']),('target',rt.TARGET,['library'])]:
        stage(['build','--stage','1','-j8','--host',rt.HOST,'--target',target,*what],part)
        rt.freeze('C',part)
    manifest=rt.load(rt.LOG/'C-sdk.json')
    old=patched_record()
    assert old['source']==p['source'] and old['tree']==p['tree'] and old['bootstrap']==manifest['bootstrap']
    driver=MEMBERS['driver_path']
    expected=MEMBERS['common']|{driver:old['driver']}
    rows=manifest['files']
    assert set(rows)|set(rt.TOOLS)==set(expected) and not(set(rows)&set(rt.TOOLS))
    assert len(expected)==119 and [n for n in rows if rows[n]!=expected[n]]==[driver]
    blob=rt.CAP/'objects'/rows[driver][0]
    transfer=rt.ROOT/'atomic-transfer';transfer.mkdir()
    subprocess.run(['zstd','-q','-3','-T2',blob,'-o',transfer/'driver.zst'],check=True)
    result={'source':c['source'],'tree':c['tree'],'reviewed_source':c['reviewed'],'parent':p['source'],
            'reviewed_parent':p['reviewed'],'driver_path':driver,'driver':rows[driver],'parent_driver':old['driver'],
            'unchanged_members':118,'compression':rt.sha(transfer/'driver.zst'),'bootstrap':manifest['bootstrap']}
    rt.save(transfer/'atomic-candidate.json',result)
    rt.save(rt.LOG/'atomic-candidate.json',result)
    print('Both target libraries and all non-driver members match:',result,flush=True)

if __name__=='__main__':build()
