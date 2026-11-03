"""Reopen the permanent stock compiler evidence; run from this directory with python3 -IB."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
here=Path(__file__).resolve().parent
def sha(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def need(test,msg):
    if not test:raise ValueError(msg)
def audit(name):
    p=here/'raw'/name
    with zipfile.ZipFile(p)as z:
        custody=json.loads(z.read('member-custody.json'));need(set(custody['files'])==set(z.namelist())-{'member-custody.json'},'unregistered data')
        for member,(size,digest)in custody['files'].items():
            data=z.read(member);need(len(data)==size and hashlib.sha256(data).hexdigest()==digest,member)
    return str(p),sha(p)
def launch(script,args,out):
    subprocess.run([sys.executable,'-IB',here/script,*args,out],check=True,cwd=here)
    return json.loads(out.read_bytes())
def check():
    listed={}
    for row in (here/'raw/SHA256SUMS').read_text().splitlines():
        digest,n=row.split('  ');need(sha(here/n)==digest,n);listed[n]=digest
    need(set(listed)=={str(p.relative_to(here))for p in (here/'raw').glob('*.zip')},'raw inventory')
    with tempfile.TemporaryDirectory()as temp:
        path=Path(temp)
        a=audit('check-ordinary.zip');d=audit('check-diagnostic.zip')
        r=launch('read_metadata.py',a,path/'metadata.json')
        need(r['old_to_edit']['changed_rows']==1145 and r['old_to_edit']['changed_expansion_rows']==17 and not r['old_to_edit']['required_changes'],'edited release metadata rows')
        s=launch('read_samples.py',d,path/'sampled.json')
        need(s['raw_sample_count']==1995 and s['task_totals']['rustc:ruff:lib']==1299,'check sample ownership')
        b=audit('first-build-ordinary.zip');g=audit('first-build-diagnostic.zip')
        c=launch('read_codegen.py',(*b,*g),path/'build.json')
        need(c['old_to_new_and_clean']['old to edit']['lib']['same_device_inode_mtime_size_sha']==232 and c['old_to_new_and_clean']['edit to independent-clean-new']['lib']['same_size_sha']==236,'genuine donors')
        need(c['exact_cgu_thread_clock']['lib']['typed_opt_modules']['26b50y1455r2nn7imncnrh1im']['full_thread_user_instructions']==9031628397,'true large optimization worker')
        need(c['unprofiled_reedit_clock']['whole']==17372334910 and c['pc_refused'],'whole PMU or first PC refusal')
        b=audit('final-build-ordinary.zip');g=audit('final-build-diagnostic.zip')
        low=launch('read_codegen.py',(*b,*g),path/'second-build.json')
        need(not low['pc_refused'] and low['unprofiled_reedit_clock']['whole']==17375687303,'lower rate true build')
        ss=path/'lower-samples.json';subprocess.run([sys.executable,'-IB',here/'read_samples.py',*g,ss,'--period','8000009'],check=True)
        samples=json.loads(ss.read_bytes());need(samples['raw_sample_count']==2174 and samples['task_totals']['rustc:ruff:lib']==1729,'unthrottled sample')
        obj=launch('read_objects.py',b,path/'objects.json');a=obj['modules']['26b50y1455r2nn7imncnrh1im']
        need(a['function_counts']==[125,125] and len(a['machine_byte_changes'])==2 and not a['resolved_relocation_changes'],'actual independent objects')
        groups=launch('derive_groups.py',b,path/'groups.json')
        need(groups['args_rank_by_full_object_size']==2 and groups['by_named_clap_receiver']['GlobalConfigArgs']=={'methods':7,'global_definitions':7,'native_bytes':9748},'typed receiver size')
        r=launch('read_metadata.py',b,path/'build-metadata.json')
        need(r['old_to_edit']['changed_rows']==1351 and len(r['edit_to_clean']['required_changes'])==30,'independent build metadata drift')
        print('All six raw packets, exact workers, named CGUs, native members, complete original sample rows and actual metadata controls reopened.')
if __name__=='__main__':check()
