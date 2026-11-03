"""Source and external compiler-input custody on an initially empty, uninterrupted Cargo target."""
from pathlib import Path
import json
import external
import git_manifests
import locked_git
import tomllib

BOUNDARIES = ('ordinary-buggy-cold','ordinary-edited','ordinary-fixed-idle2','kernel-buggy-return','kernel-edited','kernel-fixed-idle2','repair','empty-edit')
EMPTY = ('ordinary-buggy-cold','empty-edit','native-buggy','native-fully-empty-fixed')


def entry(case, label, role, env):
    case.fresh_state()
    state=case.w.STATE
    assert not list(state.iterdir())
    assert Path(env['CARGO_TARGET_DIR'])==state/'target' and Path(env['CARGO_BUILD_BUILD_DIR'])==state/'build'
    assert not any('TRUST' in k or 'WRAPPER' in k for k in env)
    case.save(case.w.OUT/(label+'-empty-entry.json'),dict(role=role,entries=[],state=str(state),target=env['CARGO_TARGET_DIR'],
              build=env['CARGO_BUILD_BUILD_DIR'],cargo_home=env['CARGO_HOME'],structural='independently empty outputs, locked source archives and checkouts only'))


def capture(case, label, rows, environment):
    if label not in BOUNDARIES:
        return
    artifact,=[r for r in rows if r['target']['name']=='get_size_derive2' and r['target']['kind']==['proc-macro']]
    (plugin,)=map(Path,artifact['filenames'])
    assert plugin.suffix=='.so' and artifact['package_id'].startswith('registry+') and 'get-size-derive2@0.5.1' in artifact['package_id']
    dest=case.w.OUT/'normal-external-inputs'
    dest.mkdir(exist_ok=True)
    check=external.actual_expansion(dest,label,plugin,environment,case.ROOT)
    assert check['macro']==case.sha(plugin)
    git={}
    if label in ('ordinary-buggy-cold','empty-edit'):
        lock=tomllib.loads((case.w.SRC/'Cargo.lock').read_text())
        for row in rows:
            pid=row['package_id']
            if pid.startswith('git+'):
                name,_,rev=locked_git.owner(pid,lock)
                path=Path(row['manifest_path']);oid=git_manifests.verify(pid,path,case.ROOT/'cargo',rev,name,True)
                git[pid]=[str(path),str(case.ROOT/'cargo'),rev,name,oid]
        assert len(git)==4 and set(git)==set(git_manifests.records()['packages'])
    case.save(dest/(label+'.json'), dict(package=artifact['package_id'],file=str(plugin),expansion=check,git=git))


def reopen(folder):
    dest=folder/'normal-external-inputs';evidence={}
    for label in BOUNDARIES:
        d=dest/('expansion-'+label);mark=json.loads((dest/(label+'.json')).read_bytes())
        outcome=external.read_expansion(d)
        assert outcome==mark['expansion']
        rows=[json.loads(line)for line in (folder/label/'stdout').read_bytes().splitlines()]
        art,=[r for r in rows if r.get('reason')=='compiler-artifact' and r['target']['name']=='get_size_derive2' and r['target']['kind']==['proc-macro']]
        assert art['package_id']==mark['package'] and art['filenames']==[mark['file']]
        if label in ('ordinary-buggy-cold','empty-edit'):
            assert set(mark['git'])=={r['package_id']for r in rows if r.get('reason')=='compiler-artifact' and r['package_id'].startswith('git+')}==set(git_manifests.records()['packages'])
            for pid,(path,home,rev,name,oid) in mark['git'].items():
                assert git_manifests.verify(pid,Path(path),Path(home),rev,name,False)==oid
        entries=json.loads((folder/label/'external-products.json').read_bytes())
        selected,=[p for p in entries if p[3]==mark['file']]
        assert selected[5]==outcome['macro']
        evidence[label]=outcome
    assert all(v==evidence[BOUNDARIES[0]] for v in evidence.values()), ('independent compiled external macro/expansion differs',evidence)
    for label in EMPTY:
        e=json.loads((folder/(label+'-empty-entry.json')).read_bytes())
        assert e['role']==folder.name and e['entries']==[] and e['target']==e['state']+'/target' and e['build']==e['state']+'/build'
        rows=[json.loads(line)for line in (folder/label/'stdout').read_bytes().splitlines()]
        a=[r for r in rows if r['reason']=='compiler-artifact'];assert a and all(r['fresh']is False for r in a)
    return {'real_ordinary_boundary':evidence,'genuinely_empty':list(EMPTY)}
