"""Independently compile the two Cargo sources, then reopen the signed Ruff recovery case."""
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import materialize
sys.path.insert(0,str(HERE.parent/'ron-check-share'))
import measure as m
import followthrough as probe

WARN=b'\n#[deprecated(note = "OHM_QA_PRESERVED_WARNING")]\nconst OHM_QA_OLD_CONST: u8 = 17;\n#[warn(deprecated)]\nconst _: u8 = OHM_QA_OLD_CONST;\n'
def out(p,b):
    assert not p.exists()
    m.gz(p,b)
def item_stat(p):
    x=p.stat()
    return {'path':str(p),'actual':str(p.resolve(strict=True)),
            'ino':[x.st_dev,x.st_ino],'size':x.st_size,'sha256':m.sha(p)}
def build_env(base):
    e=m.w.environment(m.R,'21',m.R/'buildkit')
    e['CARGO_BUILD_JOBS']='12'
    e['CARGO_HOME']=base['CARGO_HOME']
    return e
def builder(source,command,env,output):
    output.mkdir(parents=True)
    p=subprocess.run(command,cwd=source,env=env,capture_output=True,timeout=4400)
    out(output/'stdout.gz',p.stdout);out(output/'stderr.gz',p.stderr)
    m.save(output/'result.json',{'command':[str(a) for a in command],'exit':p.returncode,'source':str(source),'env':env})
    if p.returncode:print(p.stderr.decode(errors='replace')[-5000:],file=sys.stderr,flush=True)
    assert p.returncode==0,command
    return p
def construct(role,pack,spec,env):
    src=m.R/('cargo-src-'+role)
    proof=materialize.tree(src,pack,spec if role=='C' else None)
    if role=='P':assert proof['mode_path_sha256_inventory']=='da5d8cde02be6fcd82b87b490b937224dcd46f8e72841343d9fe00ce16d253d1'
    if role=='C':assert proof['mode_path_sha256_inventory']==spec['inventory']
    assert proof['lock']=='151c473e1a11532946ba9421ab1beeb238f98eb1f8cd4e5f94f9811003abd5a7'
    loc=m.O/'buildkit'/role;m.save(loc/'source.json',proof)
    cmd=['cargo','+ohm','-Zohm-defaults=no']
    if role=='P':
        online=dict(env);online.pop('CARGO_NET_OFFLINE')
        builder(src,[*cmd,'fetch','--locked','--target','x86_64-unknown-linux-gnu'],online,loc/'fetch')
    p=builder(src,[*cmd,'build','--release','--locked','--offline','--bin','cargo','--package','cargo',
                   '--features','ohm-defaults,all-static','-j12','--message-format=json'],env,loc/'compile')
    rows=[json.loads(l) for l in p.stdout.splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':True}
    leaf,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['name']=='cargo' and r['target']['kind']==['bin']]
    assert {'all-static','ohm-defaults'}<=set(leaf['features']) and not leaf['fresh']
    binary=Path(leaf['executable']);assert binary.is_file() and binary.resolve().is_relative_to(m.R/'buildkit')
    # Each genuine Rustup toolchain has its own Cargo executable. The other
    # SDK entries are symlinks to the same physical files in the signed SDK.
    sdk=m.R/('sdk-'+role);sdk.mkdir();(sdk/'bin').mkdir()
    real=m.R/'sdk-21'
    for f in real.iterdir():
        if f.name!='bin':(sdk/f.name).symlink_to(f,target_is_directory=f.is_dir())
    for f in (real/'bin').iterdir():
        if f.name!='cargo':(sdk/'bin'/f.name).symlink_to(f,target_is_directory=f.is_dir())
    dest=sdk/'bin/cargo';shutil.copyfile(binary,dest);dest.chmod(0o755)
    alias=m.w.environment(m.R,role,m.R/('tools-'+role))
    actual=m.get(['cargo','+ohm','-Vv'],env=alias).decode()
    rust=m.get(['rustc','+ohm','-vV'],env=alias).decode()
    sysroot=m.get(['rustc','+ohm','--print','sysroot'],env=alias).decode().strip()
    assert ('commit-hash: '+proof['commit']) in actual and 'c79998a5cd143c445a4b2528f20953b176a65c5d' in rust
    assert (sdk/'bin/rustc').samefile(real/'bin/rustc') and (Path(sysroot)/'lib').samefile(real/'lib')
    drivers=list((sdk/'lib').glob('librustc_driver*.so'));assert len(drivers)==1
    signed=m.read(m.R/'receipts/21/installed.json')
    assert m.sha(dest)==m.sha(binary) and m.sha(sdk/'bin/rustc')==signed['bin/rustc']
    assert m.sha(drivers[0])==signed[str(drivers[0].relative_to(sdk))]
    built={'source':proof,'version':actual,'rustc_version':rust,'compiler':item_stat(sdk/'bin/rustc'),
           'driver':item_stat(drivers[0]),'sysroot':sysroot,'cargo':item_stat(dest),'compiled':item_stat(binary),
           'typed_outputs':len(rows),'features':leaf['features'],'source_directory':str(src)}
    m.save(loc/'built.json',built)
    print(role,'physical source-built Cargo',proof['commit'],built['cargo']['sha256'],flush=True)
    return built

def warning_visits(role,release,env0):
    env=m.w.environment(m.R,release,m.R/('recover-'+role))
    env['CARGO_HOME']=env0['CARGO_HOME'];env['CARGO_LOG']='cargo::compiler=info,cargo::compiler::fingerprint=debug'
    leaf=m.src/probe.SOURCE;clean=m.w.git(m.src,'show','HEAD:'+probe.SOURCE)
    assert leaf.read_bytes()==clean
    try:
        leaf.write_bytes(clean+WARN)
        for name,style in [('warning-edit','json'),('warning-repeat','json'),('warning-human','human'),('warning-bad','json'),
                ('warning-repair','json'),('warning-settled','json')]:
            if name=='warning-bad':leaf.write_bytes(clean+WARN+probe.BAD)
            elif name=='warning-repair':leaf.write_bytes(clean+WARN)
            probe.execute(role,name,env,release,m.cmd[:-1],style=style,observer='physical')
    finally:leaf.write_bytes(clean)

def check_role(role):
    fixed=role=='fixed'
    observations={}
    for label in (*['train-original','edit','repeat','invalid','repair-json','idle-human','idle-json','cache-reads','bad-again',
                   'different-bad','unchanged-different-bad','different-repair','final-repair','empty-json','empty-human'],
                   'warning-edit','warning-repeat','warning-human','warning-bad','warning-repair','warning-settled'):
        d=m.O/role/label;r=m.read(d/'receipt.json')
        stdout=gzip.decompress((d/'stdout.gz').read_bytes());stderr=gzip.decompress((d/'stderr.gz').read_bytes())
        assert m.h(stdout)==r['stdout'] and m.h(stderr)==r['stderr'] and r['before']['source']==r['after']['source']
        row={'source':r['before']['source'][probe.SOURCE]['sha'],'exit':r['exit'],'workers':None}
        dirty=label in ('invalid','bad-again','different-bad','unchanged-different-bad','warning-bad')
        show_error=dirty or (not fixed and label in ('repair-json','idle-human','idle-json','cache-reads','warning-repair','warning-settled'))
        assert r['exit']==(101 if dirty else 0)
        if r['style']=='json':
            js=[json.loads(q) for q in stdout.splitlines()]
            assert js[-1]=={'reason':'build-finished','success':not dirty} and len([a for a in js if a['reason']=='compiler-artifact'])==(302 if dirty else 303)
            messages=[a for a in js if a['reason']=='compiler-message']
            errors=[a for a in messages if a['message']['level']=='error']
            assert len(errors)==int(show_error),(role,label,errors)
            if errors:
                msg=errors[0]['message'];assert msg['code']['code']=='E0308'
                loc,=[v for v in msg['spans'] if v['is_primary']]
                assert loc['file_name']==probe.SOURCE and ('OHM_RON_SECOND_BAD_TYPE' if label in ('different-bad','unchanged-different-bad') else 'OHM_RON_CHECK_BAD_TYPE') in loc['text'][0]['text']
            warnings=[a for a in messages if a['message']['level']=='warning']
            if label.startswith('warning'):
                if not dirty and (fixed or label not in ('warning-repair','warning-settled')):
                    assert any(a['message']['code']['code']=='deprecated' and 'OHM_QA_PRESERVED_WARNING' in a['message']['message'] for a in warnings)
            else:assert not warnings
            row['warnings']=[a['message']['message'] for a in warnings]
        else:
            assert not stdout and (b'error[E0308]' in stderr)==show_error and (b'OHM_RON_CHECK_BAD_TYPE' in stderr)==show_error
            assert b'Finished' in stderr and ((b'OHM_QA_PRESERVED_WARNING' in stderr)==label.startswith('warning'))
        if r['observer']=='physical':
            workers=[q[1] for q in r['physical_rustcs']]
            want=['ron']
            local=(dirty or label in ('edit','different-repair','final-repair','warning-edit') or fixed and label in ('repair-json','warning-repair'))
            if local:want+=['ty_project']
            assert workers==want,(role,label,workers,want)
            row['workers']=workers
        row['E0308']=show_error
        if label=='repair-json' or label=='warning-repair':
            name='test-lib-ty_project'
            before,=[v for k,v in r['before']['cache'].items() if Path(k).name==name]
            after,=[v for k,v in r['after']['cache'].items() if Path(k).name==name]
            assert before['size']==0 and after['size']==16
        observations[label]=row
    m.save(m.O/(role+'/gates.json'),observations)
    return observations

def main():
    spec=json.loads((HERE/'spec.json').read_bytes())
    assert spec['parent']==materialize.BASE
    # The physical local target/runtime used by downstream tools is held
    # independently from the transient source-build target below.
    env=m.acquire();m.w.room(m.R,65)
    m.run(['cc','-O2','-Wall','-Werror',m.HERE/'observe.c','-o',m.R/'observer'])
    base=build_env(env)
    pack=Path(sys.argv[3]).resolve()
    builds={v:construct(v,pack,spec,base) for v in ('P','C')}
    assert builds['P']['cargo']['sha256']!=builds['C']['cargo']['sha256']
    assert builds['P']['driver']['ino']==builds['C']['driver']['ino'] and builds['P']['driver']['sha256']==builds['C']['driver']['sha256']
    summary={}
    for role,code in [('parent','P'),('fixed','C')]:
        probe.run_role(role,code,env,True)
        warning_visits(role,code,env)
        summary[role]=check_role(role)
    m.save(m.O/'fix-terminal.json',{'product':spec,'driver':builds['P']['driver'],'source_workflow':m.w.git(HERE,'rev-parse','HEAD').decode().strip(),
        'source_parent':builds['P']['source'],'source_fixed':builds['C']['source'],'prior_qa':'9d1dd09be4d2346142957cc298093d8a75c755c3','roles':{k:len(v) for k,v in summary.items()}})
    print('All physical Ruff diagnostic controls passed as specified',flush=True)

if __name__=='__main__':main()
