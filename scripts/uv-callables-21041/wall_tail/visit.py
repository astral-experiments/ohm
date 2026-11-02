"""Acquire the first bare B wall, and independently identify the true binaries on a later restore."""
from pathlib import Path
from . import resources,policy
import os,re

def measured(at,argv,cwd,env,save,clock):
    assert all(x not in env for x in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_LOG','LD_PRELOAD','RUSTC_LOG','RUSTC_SELF_PROFILE'))
    before=resources.snapshot()
    rec=clock.command(at,argv,'native',cwd,env)
    after=resources.snapshot()
    assert before['end_ns']<=rec['start_ns']<rec['end_ns']<=after['start_ns'] and before['affinity']==rec['cpus']==after['affinity']
    save(at/'resources.json',{'before':before,'after':after,'delta':resources.delta(before,after),'scope':'RUSAGE_CHILDREN sums the waited child tree; maxrss is the prior-session high-water value. Cgroup and host counters may include other tasks. No counter is sampled inside the child wall.'})
    return rec

def kernel_receipt(events,enrollment,forms,expected_argv,decode):
    z=decode(events);root=z['root'];first=z['images'][0]
    assert first['pid']==root and first['argv']==expected_argv and first['exe']==expected_argv[0]and first['file']==enrollment['cargo_file']and z['exits'][root]==0
    rust=enrollment['compiler'];wanted={a[a.index('--crate-name')+1]:a for a in forms};assert len(wanted)==len(forms)==8;actual={}
    for image in z['images']:
        args=image.get('argv')or []
        if image['file']!=enrollment['rustc_file']and Path(image['exe']).name!='rustc'and not(args and Path(args[0]).name=='rustc'):continue
        pid=image['pid'];assert image['file']==enrollment['rustc_file']and image['exe']==rust and args[0]==rust and z['exits'].get(pid)==0
        assert args.count('--crate-name')==1 and args.count('--crate-type')==1 and args[args.index('--crate-type')+1]=='lib';name=args[args.index('--crate-name')+1]
        assert name not in actual and wanted.get(name)==args;actual[name]=pid
    assert set(actual)==set(wanted)and len(set(actual.values()))==8
    return {'cargo':root,'rustcs':actual,'images':len(z['images']),'tracees':len(z['exits'])+len(z['handoffs'])}

def kernel(at,forms,runtime,core,events):
    m=core.m; at.mkdir(); argv=core.CHECK; rust=str(m.RUSTC)
    pair={'cargo_file':events['file_id'](Path(argv[0])),'rustc_file':events['file_id'](m.RUSTC),'compiler':rust,'cargo_sha256':m.filesha(Path(argv[0])),'compiler_sha256':m.filesha(m.RUSTC),'original_argv':argv}
    assert pair['compiler_sha256']==runtime['bin/rustc'];m.save(at/'enrollment.json',pair)
    events['capture'](at,argv,m.ENV,m.SRC,pair['rustc_file']);cert=kernel_receipt(m.read(at/'kernel-events.json'),pair,forms,argv,events['decode']);m.save(at/'actual-rustcs.json',cert)
    for a in ('stdout','stderr'):os.link(at/a,at/('cargo.'+a))
    return cert

def boot():
    import core as c,wall_clock
    m=c.m;w,_=c.host();out=w/'trait-results';p=policy.plan();old=m.read(out/'fresh-boot.json');additional=m.read(policy.P/'later-boots.json')
    assert m.filesha(c.HERE/'pair.json')==p['previous_pair_sha256']and c.P['branch']==p['branch']and c.P['parent']==p['coordinator_parent'] and c.ROLES==[p['baseline'],p['candidate']]
    known=[v['boot']for v in p['initial_excluded_boots'].values()]+[v['boot']for v in p['additional_current_boots']];assert len(known)==22 and len(set(known))==22
    assert set(old['excluded'])=={v['boot']for v in c.PAIR['prior_boots'].values()} and set(old['excluded'])<set(known)
    local_phase=policy.P/'local-20992.json';assert m.filesha(local_phase)=='70f9faa511a78b113a78bf2bb4fcc01394ebd1f55906eceeb7a49834d3d115f6';known.append(m.read(local_phase)['boot'])
    for more in additional:
        assert type(more['run'])is int and type(more['job'])is int and type(more['artifact_id'])is int and re.fullmatch('[0-9a-f]{64}',more['zip_sha256'])and re.fullmatch('[0-9a-f]{64}',more['entry_sha256']);known.append(more['boot'])
    assert len(known)==len(set(known))and old['boot']==wall_clock.current()['boot']and old['boot']not in known
    obj={'boot':old['boot'],'prior_boots':sorted(known),'registration':policy.SHA,'initial_and_extra':m.filesha(policy.P/'later-boots.json'),'original_calibration_set':old,'run':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'head':os.environ['REVIEWED_HEAD'],'runner':os.environ['RUNNER_NAME']}
    result=out/'wall-tail-boot.json'
    if result.exists():assert m.read(result)==obj
    else:m.save(result,obj)
    return obj
