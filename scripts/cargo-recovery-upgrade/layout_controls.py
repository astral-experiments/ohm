"""Separately exercise matched dev-channel default and opt-out upgrade identities."""
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import upgrade as u
m, probe, q = u.m, u.probe, u.q
ROLE = 'matched-Ruff'


def compiler_owners(rec):
    return [r[1] for r in rec['physical_rustcs']]


def use_gc_executable(artifact, spec):
    seal=m.read(artifact/'build.json')
    binary=artifact/'cargo'
    assert seal['qa']==os.environ['GITHUB_SHA'] and seal['candidate']==spec['head']
    assert seal['tree']['tree']==spec['tree'] and seal['tree']['mode_path_sha256_inventory']==spec['inventory']
    assert m.sha(binary)==seal['compiled']==seal['delivered']
    signed=m.read(m.R/'receipts/21/installed.json')
    for name in ('bin/rustc','bin/cargo',*(p for p in signed if 'librustc_driver' in p)):
        assert m.sha(m.R/'sdk-21'/name)==signed[name]==seal['signed_runtime'][name]
    dest=m.R/'sdk-C/bin/cargo'
    dest.parent.mkdir(parents=True)
    shutil.copyfile(binary,dest)
    dest.chmod(0o755)
    version=subprocess.check_output([dest,'-Vv'],text=True)
    assert m.sha(dest)==seal['delivered'] and version==seal['version'] and 'commit-hash: '+spec['head'] in version
    m.save(m.O/'matched-delivered-cargo.json',seal)
    return {'version':version,'sha256':m.sha(dest)}


def main():
    # Both source roles use precisely the channel and release-version semantics
    # of the Rust bootstrap. The signed binary keeps its own release label.
    base=m.acquire()
    m.w.room(m.R,65)
    m.run(['cc','-O2','-Wall','-Werror',m.HERE/'observe.c','-o',m.R/'observer'])
    compile_env=q.build_env(base)
    compile_env.update(CFG_RELEASE_CHANNEL='dev',CFG_RELEASE='1.99.0-dev')
    if len(sys.argv)==5:
        q.HERE=Path(__file__).resolve().parents[1]/'gc-mount-evidence/candidate-source'
    spec=json.loads((q.HERE/'spec.json').read_bytes())
    pack=Path(sys.argv[3]).resolve()
    builds={'P':q.construct('P',pack,spec,compile_env)}
    builds['C']=use_gc_executable(Path(sys.argv[4]).resolve(),spec) if len(sys.argv)==5 else q.construct('C',pack,spec,compile_env)
    assert all('release: 1.99.0-dev\n' in v['version'] for v in builds.values())
    u.init_sdk()
    default=u.usage('same-path-default')
    off=u.usage('same-path-optout')
    empty=u.usage('missing-reference-empty')
    envs={'default':default,'off':off,'empty':empty}
    m.save(m.O/ROLE/'environment.json',envs)
    cmd=m.cmd[:-1];optout=cmd[:2]+['-Zohm-defaults=no']+cmd[2:]
    visits={}
    def visit(label,mode='default',observer='physical',style='json'):
        e=envs[mode]
        rec=probe.execute(ROLE,label,e,'U',optout if mode=='off' else cmd,observer=observer,style=style)
        visits[label]=rec
        return rec
    def swap(role):
        rec=u.install(role,default);m.save(m.O/ROLE/(role+'-runtime.json'),rec)
        assert 'release: 1.99.0-dev\n' in rec['version']
        return rec
    source=m.src/probe.SOURCE;valid=source.read_bytes()
    assert valid==m.w.git(m.src,'show','HEAD:'+probe.SOURCE)
    try:
        signed=swap('signed')
        visit('signed-original',observer='plain')
        probe.reverse_history();visit('signed-genuine-edit')
        source.write_bytes(valid+q.WARN);visit('signed-valid-warning')
        source.write_bytes(valid+probe.BAD);visit('signed-invalid')
        source.write_bytes(valid+q.WARN);visit('signed-poison')
        visit('signed-stale-idle')
        visit('off-signed-empty','off',observer='plain');visit('off-signed-idle','off')
        before={'source':probe.source(),'default':probe.cache(default),'off':probe.cache(off)}
        m.save(m.O/ROLE/'pre-switch.json',before)
        parent=swap('parent');u.assert_swap(signed,parent)
        assert before=={'source':probe.source(),'default':probe.cache(default),'off':probe.cache(off)}
        visit('source-parent-stale-idle');visit('off-source-parent-idle','off')
        before2={'source':probe.source(),'default':probe.cache(default),'off':probe.cache(off)}
        m.save(m.O/ROLE/'pre-fixed.json',before2)
        fixed=swap('fixed');u.assert_swap(parent,fixed)
        assert before2=={'source':probe.source(),'default':probe.cache(default),'off':probe.cache(off)}
        fixed_visit=visit('fixed-first')
        visit('fixed-repeat');visit('fixed-repeat-human',style='human')
        visit('off-fixed-first','off');visit('off-fixed-repeat','off')
        # Move exactly one regular, private Ruff metadata output, holding its
        # original physical bytes; all fingerprints and dependencies remain.
        name,info=fixed_visit['ty_artifacts'][0][1][0]
        out=Path(name);assert out.is_file() and not out.is_symlink()
        assert out.resolve().is_relative_to(Path(default['CARGO_TARGET_DIR']))
        assert '/ty_project/' in name and out.suffix=='.rmeta' and q.item_stat(out)['sha256']==info['sha']
        held=m.R/'held-one-Ruff-output';assert not held.exists()
        prior=q.item_stat(out);out.rename(held)
        assert not out.exists() and q.item_stat(held)['ino']==prior['ino']
        r=visit('fixed-forced-one-missing')
        m.save(m.O/ROLE/'forced-output.json',{'original':prior,'held':q.item_stat(held),'regenerated':q.item_stat(out)})
        visit('fixed-after-forced')
        assert not Path(empty['CARGO_TARGET_DIR']).exists() or not list(Path(empty['CARGO_TARGET_DIR']).rglob('*.rmeta'))
        visit('fixed-independent-empty','empty')
        visit('fixed-independent-repeat','empty')
        # Admission happens after all independent raw observations exist.
        issues=[]
        def gate(ok,msg):
            if not ok:issues.append(msg)
        labels={'signed-genuine-edit':['ron','ty_project'],'signed-valid-warning':['ron','ty_project'],
                'signed-invalid':['ron','ty_project'],'signed-poison':['ron'],'signed-stale-idle':['ron'],
                'off-signed-idle':[],'source-parent-stale-idle':['ron'],'off-source-parent-idle':[],
                'fixed-repeat':['ron'],'fixed-repeat-human':['ron'],'off-fixed-first':[],'off-fixed-repeat':[],
                'fixed-forced-one-missing':['ron','ty_project'],'fixed-after-forced':['ron'],'fixed-independent-repeat':['ron']}
        good_warnings={'signed-valid-warning','off-signed-empty','off-signed-idle','off-source-parent-idle','fixed-first','fixed-repeat','fixed-repeat-human',
            'off-fixed-first','off-fixed-repeat','fixed-forced-one-missing','fixed-after-forced','fixed-independent-empty','fixed-independent-repeat'}
        stale={'signed-invalid','signed-poison','signed-stale-idle','source-parent-stale-idle'}
        summary={}
        for k,v in visits.items():
            owners=compiler_owners(v)
            if k in labels:gate(owners==labels[k],(k,'physical-rustcs',owners))
            if k in ('fixed-first','fixed-independent-empty'):gate('ty_project' in owners and 'ron' in owners,(k,'full roots',owners))
            gate(v['exit']==(101 if k=='signed-invalid' else 0),(k,'exit',v['exit']))
            if v['style']=='json':
                msgs=u.typed(ROLE,k);w=u.valid_notice(msgs);err=u.old_error(msgs)
                gate(len([x for x in msgs if x['level']=='error'])==int(k in stale),(k,'raw errors'))
            else:
                raw=gzip.decompress((m.O/ROLE/k/'stderr.gz').read_bytes())
                w=b'OHM_QA_PRESERVED_WARNING' in raw;err=b'error[E0308]' in raw
            gate(w==(k in good_warnings) and err==(k in stale),(k,'diagnostics',w,err))
            summary[k]={'actual_rustcs':None if v['observer']=='plain' else owners,'warning':w,'E0308':err,'exit':v['exit']}
        off_path=lambda v:v['ty_artifacts'][0][1][0][0]
        gate(len({off_path(visits[k]) for k in ('off-signed-idle','off-source-parent-idle','off-fixed-first','off-fixed-repeat')})==1,'off same layout')
        gate(len({off_path(visits[k]) for k in ('signed-stale-idle','source-parent-stale-idle','fixed-first','fixed-repeat','fixed-forced-one-missing')})==1,'on same layout')
        gate(out.read_bytes()==held.read_bytes() and not out.samefile(held),'forced output independently regenerated')
        m.save(m.O/'matched-terminal.json',{'summary':summary,'issues':issues,'product':spec})
        if issues:raise ValueError(issues)
    finally:source.write_bytes(valid)


if __name__=='__main__':
    main()
