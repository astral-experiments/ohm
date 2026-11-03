"""Observe one actual canonical executable at the four normally executed native stages."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import workspace29697 as study
w=study.w
BASE='e2e-f5c6198f896cf7b0'
LITERALS={'old':'f203086dc58594dc33899d25dcbdcd5ec86d04e3dfb493efe7c7a59f6abd97e2','new':'86b94323a752a316a501f542a846408648ca8b74c56bc60298690b671b7b0563','list':'76d24b892727ff181fdf019636ef5e928d741eb8df4f58f06dcc626d0bf67c52'}
def sha_at(path):
    s=path.lstat()
    return {'bytes':s.st_size,'dev':s.st_dev,'ino':s.st_ino,'links':s.st_nlink,'sha256':w.hf(path)}
def prep_existing_output(canonical):
    src=(HERE.parent/'exec_count.c').read_text()
    start='static void record_image(struct task *task, const char *trigger) {'
    pos='require(n==0 && total && close(fd)==0 && fclose(f)==0,"argv completed");'
    assert src.count(start)==src.count(pos)==1
    src=src.replace(start,(HERE/'observe.inc').read_text()+'\n'+start).replace(pos,pos+'\n    canonical_at_exec(name,trigger,executable,task->group,id);')
    p=w.root/'exec-canonical.c';p.write_text(src)
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2','-DCANONICAL="'+str(canonical)+'"',p,'-lcrypto','-o',w.root/'exec_count'],check=True)
def phase(name,env,meta,out,expected,prior):
    before=sha_at(out);assert before['sha256']==prior
    inv=study.inventory(name,env,meta,'census');assert w.root/inv['binary']==out and len(inv['executables'])==102
    after=sha_at(out);assert after['sha256']==expected
    proof=study.PROOF/name;rows=[]
    for f in sorted((proof/'tasks').glob('canonical-*.tsv'),key=lambda p:int(p.stem.split('-')[-1])):
        cols=f.read_text().rstrip('\n').split('\t');assert cols[-1]==str(out)
        rows.append(cols)
    assert sorted(set(Path(row[2]).name for row in rows))==['collect2','ld.bfd','rustc','x86_64-linux-gnu-gcc-13'],[(r[0],r[2])for r in rows]
    e={'canonical':str(out),'before':before,'after':after,'at_exec':rows}
    study.write(proof/'output-lifetime.json',e)
    assert study.verdict(out,name+'-verdict',env,0)==LITERALS['list']
    return e
def main():
    assert os.environ['REVIEWED_HEAD']==os.environ['GITHUB_SHA']and os.environ['GITHUB_RUN_ATTEMPT']=='1'
    assert w.git('rev-parse','HEAD')==study.NEW and w.git('rev-parse','HEAD^')==study.OLD
    w.guard();assert shutil.disk_usage(w.root).free>45*2**30
    # The original BOOT proof already contains the two full canonical ELF hashes. Here no
    # complete ELF copy, compressed or uncompressed, is made for the contact receiver.
    study.save_elf=w.hf
    study.write(study.PROOF/'registration.json',{'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'run':os.environ['GITHUB_RUN_ID'],'head':os.environ['GITHUB_SHA'],'prior':LITERALS,'study':study.SPEC,'target':BASE,'scope':'Signed full-command canonical path lifetime only. Every target still links normally.'})
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2',HERE.parent/'whole_count.c','-o',w.root/'whole_count'],check=True)
    assert w.hf(w.src/'sdk.json')==study.SPEC['sdk_manifest']
    env=w.install();study.select(study.OLD);study.write(study.PROOF/'registry.json.gz',study.inputs(env))
    meta=json.loads(subprocess.check_output(['cargo','+ohm','metadata','--format-version=1','--locked','--offline','--no-deps'],cwd=w.work,env=env))
    assert len(meta['workspace_default_members'])==55
    old=study.inventory('ordinary-old',env,meta);out=w.root/old['binary']
    assert out.name==BASE and w.hf(out)==LITERALS['old']and len(old['executables'])==102
    assert study.verdict(out,'old-verdict',env,0)==LITERALS['list']
    prep_existing_output(out)
    study.select(study.NEW);assert study.verdict(out,'old-on-new-verdict',env,101)==LITERALS['list']
    result={}
    for name,prior in [('ordinary-edit',LITERALS['old']),('ordinary-unchanged',LITERALS['new'])]:
        result[name]=phase(name,env,meta,out,LITERALS['new'],prior)
    study.write(study.PROOF/'lifetime.json',result)
    assert not list(study.PROOF.rglob('*.elf*')) and sum(f.stat().st_size for f in study.PROOF.rglob('*')if f.is_file())<180*2**20
if __name__=='__main__':main()
