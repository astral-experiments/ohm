"""Reopen both Cargo regressions and the late-mount controls from the same executable."""
import json
from pathlib import Path
import re
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]/'cargo-recovery-upgrade/result'))
from archive import read, sha
from matched_evidence import verify_visits

PRODUCT='70573e256d0d7e8ca0eac763e80f93b5bd79cdc4'
TREE='7f7731b4d5d857711e59d9ba08c06fdd2c0fea0d'
QA='46d28e8bff1c6b52f3e7b7bc13192019e964a7da'
SIGNED='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
FIXED='39ed11556c08de95863961763f9d95e3c61994193dbb756e6667beb3279bffe2'
DIGESTS={'build':'287b04b59ce0fa9d8aba07b21dafae36eb24c0da37639f4c1f5f3139f6ac4996',
         'ruff':'8bc57239266a8848f23a6852f3fa95782c5122d0b57992569e0b9e117fcefb79',
         'gc':'186f01e023e0c2558d69ed13ab05153957a43a0068efbc5505939fd0126fc392',
         'late':'65cdfeea4389a2dca1c82ea4c097423547f791eca4f970805b515e9ede906c0a'}


def checked_build(data,proof,source,cross_artifact=False):
    assert source['commit']==proof and 'release: 1.99.0-dev\n' in source['version'] and 'commit-hash: '+proof+'\n' in source['version']
    env=source['env'];assert env['CFG_RELEASE_CHANNEL']=='dev' and env['CFG_RELEASE']=='1.99.0-dev'
    prefix='' if cross_artifact else 'buildkit/P/compile/'
    output=data[prefix+('compile.stdout.gz' if cross_artifact else 'stdout.gz')]
    rows=[json.loads(line) for line in output.splitlines()];assert rows[-1]=={'reason':'build-finished','success':True}
    [built]=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and r['target']['kind']==['bin']]
    assert not built['fresh'] and {'all-static','ohm-defaults'}<=set(built['features'])


def deleted_sentinel(trace):
    return [int(s.split()[0]) for s in trace.splitlines() if re.search(rb'\b(?:unlink|unlinkat)\([^\n]*QA_SENTINEL[^\n]*\)\s+=\s+0$',s)]


def verify(packets, product, tree, binary, inventory, workflow, late_workflow):
    j=lambda data,key:json.loads(data[key]);build,ruff,gc,late=[packets[n] for n in ('build','ruff','gc','late')]
    compiled=j(build,'build.json')
    assert compiled==j(ruff,'matched-delivered-cargo.json')==j(gc,'packet/build.json')==j(late,'packet/build.json')
    assert compiled['qa']==workflow and compiled['candidate']==product and compiled['tree']['tree']==tree
    assert compiled['compiled']==compiled['delivered']==binary
    assert compiled['tree']['files']==3109 and compiled['tree']['mode_path_sha256_inventory']==inventory
    checked_build(build,product,{'commit':compiled['candidate'],'version':compiled['version'],'env':compiled['env']},True)
    parent=j(ruff,'buildkit/P/built.json');base=compiled['parent']
    checked_build(ruff,base,{'commit':parent['source']['commit'],'version':parent['version'],'env':j(ruff,'buildkit/P/compile/result.json')['env']})
    runtimes={r:j(ruff,'matched-Ruff/'+r+'-runtime.json') for r in ('signed','parent','fixed')}
    assert runtimes['signed']['cargo']['sha256']==SIGNED and runtimes['fixed']['cargo']['sha256']==binary
    assert runtimes['parent']['cargo']['sha256']==parent['cargo']['sha256']==parent['compiled']['sha256']
    subjects=j(ruff,'subjects.json');assert subjects['qa']==workflow and subjects['source']=='93526150df078af7dd8fc4226cdcc469539d2001'
    assert subjects['lock']=='c9e345325bec5ff08dbbe3916edd39ad0c3d1c7797a8c241ae32f62754e764bf'
    assert subjects['kit']['provenance']['sources']['rust']['revision']=='c79998a5cd143c445a4b2528f20953b176a65c5d'
    recovery=verify_visits(ruff,product,runtimes)
    cases={};races={}
    for data,qa in ((gc,workflow),(late,late_workflow)):
        terminal=j(data,'packet/terminal.json');assert terminal['qa']==qa and terminal['roles']=={'signed':0,'fixed':0}
        for role,expected in (('signed',SIGNED),('fixed',binary)):
            identity=j(data,'packet/'+role+'/identity.json');assert identity['cargo']['sha256']==expected and identity['uid']>0
            assert identity['rustc']['sha256']==compiled['signed_runtime']['bin/rustc'] and identity['driver']['sha256']==runtimes['fixed']['driver_sha']
            outer=j(data,'packet/'+role+'/outer.json');assert outer['exit']==0 and outer['residual']==[] and outer['before']==outer['after']
    for role in ('signed','fixed'):
        fixed=role=='fixed';basepath='packet/'+role+'/'
        summary=j(gc,basepath+'result.json');assert not summary['issues'] and not summary['errors'] and not summary['residual_mounts'] and len(summary['cases'])==7
        for case in ('eligible-mounted','marked-trash-mounted'):
            row=j(gc,basepath+case+'.json');trace=gc[basepath+case+'-real/native.trace.gz'];pids=deleted_sentinel(trace)
            assert row['real_ran'] and row['held']['ino']==row['base']['ino'] and row['held']['hash']==row['base']['sha256']
            assert row['held']['nlink']==int(fixed) and len(pids)==int(not fixed) and row['actual_exit']==(0 if fixed else 101)
            if fixed:assert row['external_after']==row['base'] and row['healthy_after'] is None and row['old_mount']['path']==row['new_mount']['path']
            else:assert row['external_after'] is None
            cases[role+'/'+case]={'exit':row['actual_exit'],'held_links':row['held']['nlink'],'external_unlinks':pids}
        for lane in (('native','no-openat2') if fixed else ('native',)):
            row=j(late,basepath+lane+'.json');trace=late[basepath+lane+'.trace.gz'];pids=deleted_sentinel(trace)
            assert sha(trace)==row['trace_sha256'] and row['collector_uid']>0 and row['mountpoint']==row['mount_position_after']
            assert row['bound']['dev']==row['before']['dev'] and row['bound']['ino']==row['before']['ino'] and row['bound']['mount_id']!=row['origin']['mount_id']
            assert row['held_ino']==row['before']['ino'] and row['held_hash']==row['before']['sha256'] and row['held_nlink']==int(fixed)
            assert row['status']==(0 if fixed else 101) and pids==([] if fixed else [row['collector_pid']])
            if fixed:assert row['external_after']==row['before'] and row['healthy_after'] is None and b'left untouched' in row['stderr'].encode()
            else:assert row['external_after'] is None
            if lane=='no-openat2':assert b'ENOSYS' in trace and b'INJECTED' in trace and b'/proc/self/fdinfo/' in trace
            elif fixed:assert b'EXDEV' in trace and b'RESOLVE_NO_XDEV' in trace and b'INJECTED' not in trace
            races[role+'/'+lane]={'exit':row['status'],'held_links':row['held_nlink'],'external_unlinks':pids}
    return {'cargo':product,'tree':tree,'binary_sha256':binary,'Ruff':recovery,'shared_gc':cases,'late_mount':races}

def main():
    packets={name:read(HERE/('combined-'+name+'.zip'),digest) for name,digest in DIGESTS.items()}
    return verify(packets, PRODUCT, TREE, FIXED, '80885f6cb1b78652e8cb62918bbf93fc4411d37c08f9a757e8f2de7b2a426886', QA, '59388fa4afc6f052c3edef2d7701a2823a34c700')

if __name__=='__main__':print(json.dumps(main(),indent=2,sort_keys=True))
