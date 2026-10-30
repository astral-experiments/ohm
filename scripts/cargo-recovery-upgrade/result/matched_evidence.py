"""Read every real Ruff visit from the independently matched-channel run."""
import json
from collections import Counter
from pathlib import Path
from archive import sha
from upgrade_evidence import native

P='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
C='58f94004f2cf0790be76db99a49f725a3611e5a6'
S='c79998a5cd143c445a4b2528f20953b176a65c5d'
SOURCE='crates/ty_project/src/lib.rs'
GOOD='OHM_QA_PRESERVED_WARNING'
BAD='OHM_RON_CHECK_BAD_TYPE'
PHASES={
    'signed-original':None,'signed-genuine-edit':['ron','ty_project'],'signed-valid-warning':['ron','ty_project'],
    'signed-invalid':['ron','ty_project'],'signed-poison':['ron'],'signed-stale-idle':['ron'],
    'off-signed-empty':None,'off-signed-idle':[],'source-parent-stale-idle':['ron'],'off-source-parent-idle':[],
    'fixed-first':'cold','fixed-repeat':['ron'],'fixed-repeat-human':['ron'],'off-fixed-first':[],'off-fixed-repeat':[],
    'fixed-forced-one-missing':['ron','ty_project'],'fixed-after-forced':['ron'],'fixed-independent-empty':'cold','fixed-independent-repeat':['ron'],
}

def reopen(m,prior):
    j=lambda name:json.loads(m[name])
    subjects=j('subjects.json')
    assert subjects['qa']=='dd924fb185c608fcd06756877c1a502b393a6299'
    canonical=json.loads(prior['subjects.json'])
    for field in ('source','tree','lock','history','changed','original_blob','historical_parent_blob'):assert canonical[field]==subjects[field]
    assert subjects['kit']['provenance']['sources']['rust']['revision']==S
    lane='matched-Ruff';pj=lambda name:j(lane+'/'+name+'.json')
    tools={role:pj(role+'-runtime') for role in ('signed','parent','fixed')}
    for code,role,commit in [('P','parent',P),('C','fixed',C)]:
        build=j('buildkit/'+code+'/built.json');exist=json.loads(prior['buildkit/'+code+'/built.json'])
        assert build['source']['commit']==commit and build['source']['tree']==exist['source']['tree']
        assert build['source']['mode_path_sha256_inventory']==exist['source']['mode_path_sha256_inventory']
        actual=tools[role];assert build['cargo']['sha256']==build['compiled']['sha256']==actual['cargo']['sha256']
        env=j('buildkit/'+code+'/compile/result.json')['env']
        assert env['CFG_RELEASE_CHANNEL']=='dev' and env['CFG_RELEASE']=='1.99.0-dev'
        assert 'release: 1.99.0-dev\n' in actual['version'] and 'commit-hash: '+commit+'\n' in actual['version']
        rows=[json.loads(l) for l in m['buildkit/'+code+'/compile/stdout.gz'].splitlines()]
        assert rows[-1]=={'reason':'build-finished','success':True}
        leaf,=[v for v in rows if v['reason']=='compiler-artifact' and v['target']['name']=='cargo' and v['target']['kind']==['bin']]
        assert not leaf['fresh'] and set(leaf['features'])>={'all-static','ohm-defaults'}
    assert tools['signed']['cargo']['sha256']==subjects['tools']['cargo']['sha256']
    assert len({t['cargo']['sha256'] for t in tools.values()})==3 and len({t['cargo']['path'] for t in tools.values()})==1
    for field in ('alias','rustc','driver','driver_sha'):assert all(v[field]==tools['signed'][field] for v in tools.values())
    assert tools['signed']['driver_sha']==subjects['versions']['physical_driver']['sha256']
    envs=pj('environment')
    for env in envs.values():assert not {'CI','TF_BUILD','CFG_RELEASE','CFG_RELEASE_CHANNEL','RUSTC_WRAPPER','GH_TOKEN','GITHUB_TOKEN','RUSTFLAGS'}&env.keys()
    assert len({e['CARGO_TARGET_DIR'] for e in envs.values()})==len({e['CARGO_BUILD_BUILD_DIR'] for e in envs.values()})==3
    terminal=j('matched-terminal.json')
    assert terminal['product']['head']==C and not terminal['issues'] and set(terminal['summary'])==set(PHASES)
    table={};recs={};raw_msgs={}
    for name,want in PHASES.items():
        r=pj(name+'/receipt');recs[name]=r;pre=lane+'/'+name+'/'
        tool='parent' if 'source-parent' in name else 'signed' if 'signed' in name else 'fixed'
        cache=r['before']['cache']
        stdout,stderr=m[pre+'stdout.gz'],m[pre+'stderr.gz']
        assert sha(stdout)==r['stdout'] and sha(stderr)==r['stderr'] and r['label']==name and r['before']['source']==r['after']['source']
        for instant in ('before','after'):
            for path,info in r[instant]['cache'].items():
                body=m['diag-content/'+info['sha']+'.gz']
                assert len(body)==info['size'] and sha(body)==info['sha']
        command=['cargo','+ohm']+(['-Zohm-defaults=no'] if name.startswith('off-') else [])+['check','-p','ty_project','--tests','--locked','--offline','-j8']
        assert r['command']==command+(['--message-format=json'] if r['style']=='json' else [])
        assert r['exit']==(101 if name=='signed-invalid' else 0)
        source=r['before']['source'][SOURCE]
        old_source='0aa431793a70' if name=='signed-invalid' else 'd560695aa852' if name in ('signed-original','signed-genuine-edit') else '3e9f6852ac58'
        assert source['sha'].startswith(old_source)
        assert r['before']['source'][subjects['changed']]['sha']==subjects['original_blob' if name=='signed-original' else 'historical_parent_blob']
        stale=name in ('signed-poison','signed-stale-idle','source-parent-stale-idle')
        errs=(stale or name=='signed-invalid')
        warn=not errs and name not in ('signed-original','signed-genuine-edit')
        if r['style']=='json':
            rows=[json.loads(l) for l in stdout.splitlines()]
            assert rows[-1]=={'reason':'build-finished','success':r['exit']==0}
            arts=[x for x in rows if x['reason']=='compiler-artifact']
            assert len(arts)==(302 if name=='signed-invalid' else 303)
            msgs=[x['message'] for x in rows if x['reason']=='compiler-message'];raw_msgs[name]=msgs
            e=[v for v in msgs if v['level']=='error'];w=[v for v in msgs if v['level']=='warning']
            assert len(e)==int(errs) and len(w)==int(warn)
            if e:
                assert e[0]['code']['code']=='E0308'
                span,=[s for s in e[0]['spans'] if s['is_primary']]
                assert span['file_name']==SOURCE and BAD in span['text'][0]['text']
            if w:
                assert w[0]['code']['code']=='deprecated' and GOOD in w[0]['message']
            if name!='signed-invalid':
                a,=[x for x in arts if x['target']['name']=='ty_project']
                assert a['filenames']==[r['ty_artifacts'][0][1][0][0]] and a['fresh']==r['ty_artifacts'][0][0]
        else:
            assert stdout==b'' and GOOD.encode() in stderr and b'error[E0308]' not in stderr and b'Finished' in stderr
        if want is None:
            assert r['observer']=='plain';workers=links=None
        else:
            workers,links,argv=native(m,lane,name,tools[tool])
            assert argv[1:]==r['command'][2:] and workers==[x[1] for x in r['physical_rustcs']]
            if want=='cold':
                assert {'ron','ty_project'}<=set(workers) and len(workers)==304
                wild=subjects['tools']['wild']
                assert wild['sha256']=='0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
                traces=m[pre+'trace/exec.tsv'].decode().splitlines();outs={};emits=Counter()
                for ln in traces:
                    seq,pid,dev,ino,_,img=ln.split('\t')
                    args=[v.decode() for v in m[pre+f'trace/args-{int(seq):04d}'][:-1].split(b'\0')]
                    if [int(dev),int(ino)]==wild['dev_ino'] and '-o' in args:
                        assert pid not in outs and img==wild['physical']
                        outs[pid]=args[args.index('-o')+1]
                    if [int(dev),int(ino)]==tools[tool]['rustc'][:2] and '--crate-name' in args and '--out-dir' in args:
                        emit,=[v for v in args if v.startswith('--emit=')];emits[emit]+=1
                        if emit=='--emit=llvm-ir':
                            assert args[args.index('--crate-name')+1].startswith('autocfg_') and '/memoffset/' in args[args.index('--out-dir')+1]
                assert len(links)==len(outs)==len(set(outs.values()))==48
                assert dict(emits)=={'--emit=dep-info,metadata,link':66,'--emit=dep-info,link':48,'--emit=dep-info,metadata':189,'--emit=llvm-ir':1}
            else:assert workers==want and links==[],(name,want,workers,links)
        assert terminal['summary'][name]=={'actual_rustcs':workers,'warning':warn,'E0308':errs,'exit':r['exit']}
        table[name]={'rustcs':len(workers) if workers is not None else None,'named_rustcs':workers if workers is not None and len(workers)<6 else None,
                     'physical_links':None if links is None else len(links),'exit':r['exit'],'E0308':errs,'real_warning':warn}
    for phase in ('fixed-first','fixed-repeat','off-fixed-first','fixed-forced-one-missing','fixed-after-forced','fixed-independent-repeat'):
        assert raw_msgs[phase]==raw_msgs['fixed-independent-empty']
    paths=lambda ns:{recs[n]['ty_artifacts'][0][1][0][0] for n in ns}
    on,=paths(['signed-stale-idle','source-parent-stale-idle','fixed-first','fixed-repeat','fixed-forced-one-missing','fixed-after-forced'])
    off,=paths(['off-signed-idle','off-source-parent-idle','off-fixed-first','off-fixed-repeat'])
    assert '/debug/build/.ohm-split-' in off and '/debug/build/workspaces/' in on
    assert on!=off and on!=next(iter(paths(['fixed-independent-empty'])))
    assert recs['source-parent-stale-idle']['before']['cache']==pj('pre-switch')['default'] and recs['fixed-first']['before']['cache']==pj('pre-fixed')['default']
    assert recs['source-parent-stale-idle']['before']['source']==recs['fixed-first']['before']['source']
    forced=pj('forced-output')
    a,b,c=(forced[k] for k in ('original','held','regenerated'))
    assert all(r['sha256']==a['sha256'] and r['size']==a['size'] for r in (b,c))
    assert a['path']==c['path']==on and a['ino']==b['ino']!=c['ino']
    reason=m[lane+'/fixed-first/stderr.gz']
    return {'product':C,'signed_source':P,'channel':'dev','bootstrap_release':'1.99.0-dev','same_default_output':on,'same_optout_output':off,
            'default_fingerprint_config_changes':reason.count(b'ConfigSettingsChanged'),'forced_rmeta_bytes':c['size'],'phases':table}
