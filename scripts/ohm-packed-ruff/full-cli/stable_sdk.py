"""Select immutable compiler trees at one path without changing any binary's identity."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent),str(HERE.parent/'harness')]
import study as kit
import native
from omission import publish,require,sha

PARK=kit.ROOT/'full-cli-parked-sdks'
MARK='.full-cli-physical-role'
IDENTITIES=kit.OUT/'full-cli-sdk-identities.json'
USES=kit.OUT/'full-cli-sdk-uses'
NAMESPACES=kit.OUT/'full-cli-stable-cargo.json'


def signature(root,name):
    p=root/name;info=p.stat();require(stat.S_ISREG(info.st_mode) and not p.is_symlink(),('invalid SDK identity',name))
    return {'device':info.st_dev,'inode':info.st_ino,'bytes':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns,'sha256':sha(p)}


def identity(root,names):return {name:signature(root,name) for name in names}


def prepare():
    require(not PARK.exists() and not (kit.SDK/MARK).exists(),'expected one original parent SDK')
    PARK.mkdir();USES.mkdir();candidate=PARK/'C'
    # Complete both sets of shared hardlinks before recording a single ctime.
    shutil.copytree(kit.SDK,candidate,symlinks=True,copy_function=os.link)
    changes=json.loads((kit.OUT/'enrolled.json').read_bytes())['changes']
    for role,root in [('P',kit.SDK),('C',candidate)]:
        files=json.loads((kit.OUT/f'{role}.json').read_bytes())['files']
        required={'bin/rustc','bin/cargo',kit.WILD,*[n for n in files if n.startswith('lib/librustc_driver-')]}
        require(len(required)>=4 and set(changes)<=required,'different executable or native compiler files')
        if role=='C':
            for name in changes:
                digest,size,mode=files[name];path=root/name;path.unlink();shutil.copyfile(kit.ROOT/'capsule/objects'/digest,path);path.chmod(mode)
                require(path.stat().st_size==size and sha(path)==digest,'incorrect candidate content')
        (root/MARK).write_text(role+'\n')
    result={}
    for role,root in [('P',kit.SDK),('C',candidate)]:
        result[role]=identity(root,sorted(required));expected=json.loads((kit.OUT/f'{role}.json').read_bytes())['files']
        for name,got in result[role].items():
            want=kit.TOOLS[name] if name in kit.TOOLS else expected[name][0]
            require(got['sha256']==want,('wrong frozen compiler or signed tool',role,name))
    publish(IDENTITIES,result)


def select(arm,label):
    wanted='P' if arm=='Full' else 'C';active=(kit.SDK/MARK).read_text().strip();frozen=json.loads(IDENTITIES.read_bytes())
    require(active in frozen and identity(kit.SDK,frozen[active])==frozen[active],('old active SDK identity changed',active))
    if wanted!=active:
        parked=PARK/wanted;old=PARK/active
        require(not old.exists() and parked.is_dir() and (parked/MARK).read_text().strip()==wanted and identity(parked,frozen[wanted])==frozen[wanted],'incorrect parked compiler')
        kit.SDK.rename(old)
        try:parked.rename(kit.SDK)
        except BaseException:
            old.rename(kit.SDK);raise
        require(identity(old,frozen[active])==frozen[active],'parking changed a contained file ctime or inode')
    current=identity(kit.SDK,frozen[wanted]);require(current==frozen[wanted],('active compiler file identity changed',wanted))
    env=kit.environment(arm)
    for name in ('rustc','cargo'):
        actual=subprocess.check_output(['rustup','which','--toolchain','ohm',name],env=env,text=True).strip();require(Path(actual).samefile(kit.SDK/'bin'/name),'wrong exposed canonical SDK')
    require((kit.WORK/'.owned-by-packed-study').read_text()==str(kit.ROOT),'unowned work directory')
    for name in ('target','build'):
        path=kit.WORK/name
        if path.exists():
            require(path.is_dir() and not path.is_symlink() and path.parent==kit.WORK,'refuse non-owned build root');shutil.rmtree(path)
        path.mkdir()
    publish(USES/(label+'.json'),{'arm':arm,'role':wanted,'canonical':str(kit.SDK),'files':current});return env


def output_directory(messages,package):
    output,=[m['out_dir'] for m in messages if m.get('out_dir') and m['package_id'].split('#')[-1].split('@')[0]==package]
    path=Path(output);context,=[v for v in path.parts if re.fullmatch(r'v2-[0-9a-f]{16}',v)]
    return {'context':context,'path':str(path)}


def check_namespaces():
    result={};observations=[];data=kit.OUT/'full-cli-namespace-probes';data.mkdir()
    kit.git('switch','-q',kit.NAMES['A'])
    for i,arm in enumerate(('Off','Full','Packed','Full','Off','Packed'),1):
        label=f'namespace-{i}-{arm}';env=select(arm,label);where=data/label;where.mkdir()
        # Use an actual locked dependency whose build script shares Ruff's workspace context.
        result_run=native.run(['cargo','+ohm','build','-p','proc-macro2@1.0.107','--locked','--offline','-j4','--message-format=json'],env,kit.TREE,where/'cargo');rows=list(map(json.loads,result_run.stdout.splitlines()))
        require(rows[-1]=={'reason':'build-finished','success':True} and all(not e['fresh'] for e in rows if e.get('reason')=='compiler-artifact'),'namespace probe did not start from empty outputs')
        seen=output_directory(rows,'proc-macro2');require(result.setdefault(arm,seen)==seen,('same option switched Cargo native directories',arm,result[arm],seen));observations.append({'arm':arm,'selected':seen})
    publish(NAMESPACES,{'expected':result,'checks':observations,'cargo_source':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c','signed_cargo_context_source':'c4e15d7bae3521c4746179fd7d17a975306e7dcb'})
