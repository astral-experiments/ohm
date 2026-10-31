"""Run the physically listed profile and worktree controls against the signed release."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
RELEASE='ohm-1.99.0-21'
SHA='c7f394c8c9aaef1272c621ff11d77dcf569ed94b'
TRIPLE='aarch64-apple-darwin'
NAMES=['profile_settings::ohm_default_debuginfo','profile_settings::ohm_default_debuginfo_respects_overrides',*('ohm_worktree::'+s for s in ['worktree_import_requires_cloning','bundled_clippy_isolation_defaults_follow_actual_snapshot_cloning','bundled_clippy_preserves_ordinary_seeds_without_importing_lint_state','clippy_isolation_overrides_are_inherited_and_child_flags_take_precedence','forced_clippy_isolation_preserves_compiler_trust_rejections','clippy_wrapper_scripts_still_deny_the_whole_seed'])]
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,d):p.write_text(json.dumps(d,sort_keys=True,indent=2)+'\n')
def fetch():
    root=Path(os.environ['RUNNER_TEMP'])/'current-306';root.mkdir()
    pre='repos/astral-experiments/ohm/';gh=['gh','api'];r=json.loads(subprocess.check_output([*gh,pre+'releases/tags/'+RELEASE]))
    assert r['id']==429373023 and not r['draft'] and r['target_commitish']=='6920a42c1f5ab44ccd8b6a3638478acd1b5efaf1'
    rows=[]
    for n,dst,ident,h in [('ohm-installer.sh','install.sh',693058653,'98b98b55ca70d480d6f031612edcfe2a7fa07152f9ce300bb93a60fbe28d4092'),(RELEASE+'-'+TRIPLE+'.tar.gz',None,693058656,'b9514511839ca0dd54e3f473df508c2d43f0dfc27de90ed3926811ed063c7f73')]:
        a,=[v for v in r['assets'] if v['name']==n and v['id']==ident];assert a['digest']=='sha256:'+h
        path=root/(dst or n)
        with path.open('xb') as f:subprocess.run([*gh,'-H','Accept: application/octet-stream',pre+'releases/assets/'+str(ident)],stdout=f,check=True)
        assert path.stat().st_size==a['size'] and digest(path)==h
        rows.append({'filename':n,'id':ident,'size':a['size'],'sha256':h})
    dump(root/'custody.json',{'assets':rows,'tag':r['tag_name'],'commit':r['target_commitish']})
def run(suite,subject,out,source):
    records={}
    for tool in ('rustc','cargo','clippy-driver'):
        p=Path(subprocess.check_output(['rustup','which','--toolchain',RELEASE,tool],text=True).strip())
        records[tool]={'path':str(p),'sha256':digest(p),'version':subprocess.check_output([p,'-vV' if tool!='clippy-driver' else '-V'],text=True)}
    assert RELEASE in records['rustc']['version'] and 'commit-hash: 2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c' in records['cargo']['version']
    env=os.environ.copy();env['RUSTUP_TOOLCHAIN']=RELEASE
    env['PATH']=':'.join([str(Path(records['rustc']['path']).parent),str(Path(shutil.which('rustup')).parent),'/usr/bin','/bin','/usr/sbin','/sbin'])
    assert 'commit-hash: '+SHA in subprocess.check_output([subject,'-Vv'],env=env,text=True)
    roster=subprocess.check_output([suite,'--list'],env=env,cwd=source,text=True).splitlines();assert all(roster.count(n+': test')==1 for n in NAMES)
    assert all(not l.startswith('profiles::ohm_default_debuginfo') for l in roster)
    terminal=[];dump(out/'installed.json',records)
    for n in NAMES:
        cmd=[str(suite),n,'--exact','--include-ignored','--nocapture'];d=subprocess.run(cmd,env=env,cwd=source,capture_output=True,timeout=240)
        name=n.replace('::','__')
        for ext,buf in [('stdout',d.stdout),('stderr',d.stderr)]:
            with gzip.open(out/(name+'.'+ext+'.gz'),'xb') as f:f.write(buf)
        actual=[(x.decode(),y.decode()) for x,y in re.findall(rb'^test (\S+) \.\.\. (ok|FAILED)$',d.stdout,re.M)]
        good=d.returncode==0 and actual==[(n,'ok')] and b'test result: ok. 1 passed; 0 failed; 0 ignored;' in d.stdout
        terminal.append({'name':n,'argv':cmd,'actual':actual,'exit':d.returncode,'qualified':good});print(n,'=>',d.returncode,actual,flush=True)
    dump(out/'named-terminal.json',{'cargo':digest(subject),'suite':digest(suite),'rows':terminal,'qa':os.environ['GITHUB_SHA'],'source':SHA})
    assert all(v['qualified'] for v in terminal),[(r['name'],r['exit']) for r in terminal if not r['qualified']]
if __name__=='__main__':fetch()
