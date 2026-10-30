"""Reopen the poisoned cache and both native sides of the stable-path tool change."""
import json
import re
from pathlib import Path
from archive import sha

def native(data,lane,name,runtime):
    path=lane+'/'+name+'/trace/'
    owners=[];linkers=[];cargos=[]
    for ln in data[path+'exec.tsv'].decode().splitlines():
        n,pid,dev,ino,hit,img=ln.split('\t')
        identity=tuple(map(int,(dev,ino)));b=data[path+f'args-{int(n):04d}'];assert b[-1:]==b'\0';a=[s.decode() for s in b[:-1].split(b'\0')]
        if identity==tuple(runtime['cargo']['ino']):
            assert img==runtime['cargo']['actual'];cargos.append(a)
        if Path(img).name=='rustc':assert identity==tuple(runtime['rustc'][:2])
        if identity==tuple(runtime['rustc'][:2]) and '--crate-name' in a and '--out-dir' in a and not any(s.startswith('--print') for s in a):
            n=a[a.index('--crate-name')+1]
            assert int(hit)==(n=='ron');owners.append(n)
        if Path(img).name in ('ld.bfd','ld','wild','rust-lld','ld.lld') and '-o' in a:linkers.append([int(pid),img])
    assert len(cargos)==1
    return owners,linkers,cargos[0]

def verify(data):
    get=lambda k:json.loads(data[k])
    posted=get('upgrade-terminal.json')
    assert posted['signed_to_final'] and set(posted['errors'])=={'Ruff'}
    failure=posted['errors']['Ruff']
    assert "offafter=visit('off-new-idle',e_off,off);settled(offafter,[])" in failure and "AssertionError: ('off-new-idle'," in failure
    assert not any(k.startswith('ruff-migration/fixed-') for k in data)
    src='crates/ty_project/src/lib.rs'
    good='OHM_QA_PRESERVED_WARNING';bad='OHM_RON_CHECK_BAD_TYPE'
    roles={}
    for lane in ('ruff-migration','fully-fresh-migration'):
        pre=get(lane+'/old-runtime.json');post=get(lane+'/new-runtime.json')
        assert pre['cargo']['path']==post['cargo']['path'] and pre['cargo']['sha256']!=post['cargo']['sha256']
        assert pre['cargo']['sha256']==get('subjects.json')['tools']['cargo']['sha256']
        assert post['cargo']['sha256']==get('buildkit/C/built.json')['cargo']['sha256'] and post['driver_sha']==get('buildkit/C/built.json')['driver']['sha256']
        assert all(pre[field]==post[field] for field in ('alias','rustc','driver','driver_sha'))
        roles[lane]={'old':pre['cargo']['sha256'],'new':post['cargo']['sha256'],'driver':pre['driver_sha'],'phase':{}}
    full=('old-ordinary-train','old-real-edit','old-valid-warning','old-warning-repeat','old-invalid','old-poisoned-repair','old-already-poisoned-json',
          'old-already-poisoned-human','off-old-empty','off-old-idle','upgraded-first','upgraded-settled-json','upgraded-settled-human','off-new-idle')
    prev=None; switch=get('ruff-migration/signed-before-swap.json')
    stale={'old-poisoned-repair','old-already-poisoned-json','old-already-poisoned-human'};invalid='old-invalid'
    for name in full:
        prefix='ruff-migration/'+name+'/'
        r=get(prefix+'receipt.json'); assert r['before']['source']==r['after']['source']
        is_old=name.startswith('old-') or name.startswith('off-old')
        runtime=get('ruff-migration/'+('old' if is_old else 'new')+'-runtime.json')
        if r['observer']=='physical':
            owners,links,cmd=native(data,'ruff-migration',name,runtime)
            assert owners==[a[1] for a in r['physical_rustcs']] and cmd[1:]==r['command'][2:]
        else:owners,links=None,None
        stdout,stderr=data[prefix+'stdout.gz'],data[prefix+'stderr.gz']
        assert sha(stdout)==r['stdout'] and sha(stderr)==r['stderr']
        assert r['exit']==(101 if name==invalid else 0)
        has_error=name==invalid or name in stale
        has_warn=name not in {invalid,'old-ordinary-train','old-real-edit',*stale}
        if r['style']=='json':
            stream=[json.loads(x) for x in stdout.splitlines()];assert stream[-1]=={'reason':'build-finished','success':r['exit']==0}
            messages=[v['message'] for v in stream if v['reason']=='compiler-message']
            errs=[v for v in messages if v['level']=='error'];warns=[v for v in messages if v['level']=='warning']
            assert bool(errs)==has_error and bool(warns)==has_warn
            if has_error:
                e,=errs
                assert e['code']['code']=='E0308' and any(bad in t['text'] for s in e['spans'] if s['is_primary'] and s['file_name']==src for t in s['text'])
            if has_warn:
                assert any(v['code'] and v['code']['code']=='deprecated' and good in v['message'] for v in warns)
        else:
            assert stdout==b'' and (b'error[E0308]' in stderr)==has_error and (good.encode() in stderr)==has_warn and b'Finished' in stderr
        if name=='old-poisoned-repair':
            assert owners==['ron'] and r['before']['source'][src]['bad']==[];prev=r
            mark,=[val for pat,val in r['before']['cache'].items() if Path(pat).name=='test-lib-ty_project']
            assert mark['size']==0
            af,=[val for pat,val in r['after']['cache'].items() if Path(pat).name=='test-lib-ty_project']
            assert af['size']==16
            cause,=[val for pat,val in r['after']['cache'].items() if Path(pat).name=='output-test-lib-ty_project']
            cached=data['diag-content/'+cause['sha']+'.gz'];assert sha(cached)==cause['sha'] and bad.encode() in cached and good.encode() not in cached
        if name=='upgraded-first':
            assert prev and r['before']['source']==switch['source']==prev['after']['source']
            assert r['before']['cache']==switch['cache'] and 'ty_project' in owners
            for cat in ('test-lib-ty_project','test-lib-ty_project.json','output-test-lib-ty_project'):
                key,val=switch['active'][cat]
                assert prev['after']['cache'][key]['sha']==r['before']['cache'][key]['sha']==val['sha']
            active=r['ty_artifacts'][0][1][0][0]
            candidates=[v for pat,v in r['after']['cache'].items() if Path(pat).parent==Path(active).parent.parent/'fingerprint' and Path(pat).name=='output-test-lib-ty_project']
            cured,=candidates;bytes_=data['diag-content/'+cured['sha']+'.gz']
            assert sha(bytes_)==cured['sha'] and good.encode() in bytes_ and bad.encode() not in bytes_
        if name in ('old-warning-repeat','old-already-poisoned-json','old-already-poisoned-human','upgraded-settled-json','upgraded-settled-human'):
            assert owners==['ron'] and links==[]
        if name in ('off-old-idle','off-new-idle'):
            assert '-Zohm-defaults=no' in r['command']
            path=r['ty_artifacts'][0][1][0][0]
            if name=='off-old-idle':
                assert owners==[] and links==[] and '/debug/build/.ohm-split-' in path
                off_path=path
            else:
                assert len(owners)==304 and '/debug/deps/.ohm-split-' in path and Path(path).name==Path(off_path).name
                assert stderr.count(b': fingerprint error for ')==338
                assert b': fingerprint dirty for ' not in stderr
        if name=='upgraded-first':
            assert len(owners)==304 and stderr.count(b'ConfigSettingsChanged')==303
            assert r['ty_artifacts'][0][1][0][0]==get('ruff-migration/old-already-poisoned-json/receipt.json')['ty_artifacts'][0][1][0][0]
        roles['ruff-migration']['phase'][name]={'exit':r['exit'],'rustcs':owners,'native_links':links,'stale_E0308':name in stale,'valid_warning':has_warn}
    lane='fully-fresh-migration'
    for name in ('old-valid','old-fresh','old-invalid','old-poisoned-repair','old-fully-fresh-poison','new-first','new-fully-fresh'):
        pref=lane+'/'+name+'/'
        r=get(pref+'receipt.json');runtime=get(lane+'/'+('old' if name.startswith('old') else 'new')+'-runtime.json')
        owners,linkers,cmd=native(data,lane,name,runtime)
        assert not linkers and owners==r['workers'] and cmd[1:]==['check','--tests','--locked','--offline','-j1','--message-format=json']
        stream=[json.loads(l) for l in data[pref+'stdout.gz'].splitlines()]
        assert stream[-1]=={'reason':'build-finished','success':r['exit']==0} and r['exit']==(101 if name=='old-invalid' else 0)
        msgs=[v['message'] for v in stream if v['reason']=='compiler-message']
        err=[m for m in msgs if m['level']=='error'];w=[m for m in msgs if m['level']=='warning']
        assert bool(err)==r['error'] and bool(w)==r['warning']
        if err:assert err[0]['code']['code']=='E0308' and any(bad in t['text'] for s in err[0]['spans'] if s['is_primary'] for t in s['text'])
        if w:assert any(good in m['message'] and m['code']['code']=='deprecated' for m in w)
        for path,(info,text) in r['cache'].items():assert len(text.encode())==info['size'] and sha(text.encode())==info['sha']
        if name=='old-fully-fresh-poison':
            assert owners==[] and r['error'] and not r['warning']
            assert any(Path(p).name=='test-lib-app' and re.fullmatch('[0-9a-f]{16}',b) for p,(_,b) in r['cache'].items())
            assert any(Path(p).name=='output-test-lib-app' and bad in b and good not in b for p,(_,b) in r['cache'].items())
            oldsrc=r['source']
        if name=='new-first':assert 'app' in owners and r['source']==oldsrc and r['warning'] and not r['error']
        if name=='new-fully-fresh':assert owners==[] and r['source']==oldsrc and r['warning'] and not r['error']
        roles[lane]['phase'][name]={'exit':r['exit'],'rustcs':owners,'warning':bool(w),'E0308':bool(err)}
    roles['initial_opt_out_gate']={'passed':False,'expected_rustcs':0,'actual_rustcs':304,'missing_prior_fingerprints':338,
        'outcome':'both given opt-out programs use different Cargo build directory layouts; retained as a failed identity control'}
    return roles
