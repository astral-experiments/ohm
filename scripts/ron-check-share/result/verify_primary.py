#!/usr/bin/env python3
"""Independently reopen the original, failed-gate signed benchmark archive."""
import collections
import gzip
import hashlib
import json
import statistics
import sys
import zipfile
from pathlib import Path

DIGEST = '9e3a59e091c467c5139532dfb09cd8765eef343c938c0680e75da3ec2282ce3e'
SCOPES = [('0',1),('1',1),('2',1),('2',2),('exec',1),('thread',1),('thread',2)]
CARGO = ['check','-p','ty_project','--tests','--locked','--offline','-j8','--message-format=json']

def digest(b):
    return hashlib.sha256(b).hexdigest()

def read_trace(z, name):
    def read(s):
        return z.read(f'{name}/trace/{s}')
    counter={k:list(map(int,v)) for line in read('counts.tsv').decode().splitlines() for (k,*v) in [line.split('\t')]}
    assert set(counter)=={'root','hits','whole','selected'} and counter['root'][1]==0 and counter['hits']==[1]
    for k in ('whole','selected'):
        err,ins,enabled,running=counter[k]
        assert err==0 and ins>0 and enabled==running and enabled>0
    assert counter['selected'][1]<counter['whole'][1]
    roots={counter['root'][0]}
    children=collections.defaultdict(list)
    for line in read('events.tsv').splitlines():
        typ,pid,child=map(int,line.split())
        assert typ in (1,2,3) and pid in roots and child not in roots
        children[pid].append((typ,child))
        roots.add(child)
    execs=[]
    for n,line in enumerate(read('exec.tsv').decode().splitlines(),1):
        seq,pid,dev,ino,hit,exe=line.split('\t')
        assert int(seq)==n and int(pid) in roots
        arg=read(f'args-{n:04d}');assert arg.endswith(b'\0')
        execs.append((int(pid),(int(dev),int(ino)),int(hit),exe,[a.decode() for a in arg[:-1].split(b'\0')]))
    assert len([e for e in execs if e[2]])==1
    return counter,execs,children

def run(path):
    assert path.stat().st_size==309996 and digest(path.read_bytes())==DIGEST
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None and len(z.namelist())==len(set(z.namelist())) and 'terminal.json' not in z.namelist()
        su=json.loads(z.read('subjects.json'))
        assert su['qa']=='6386ed93a6e4aabff744e92d70846f4e6170fceb' and su['source']=='93526150df078af7dd8fc4226cdcc469539d2001'
        assert su['history']=='32c5cd5daba51d9c3da691c5b43afa6a7a4bb731' and su['kit']['archive_sha256']=='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
        assert su['calibration_source']=='dacd1dd7fef85cacb44a236e0c4191d95db036a623b2a01ae3a5d76d2f3d0b0e'
        assert {k:su['kit']['provenance']['sources'][k] for k in ('rust','cargo')}=={'cargo':{'revision':'2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'},'rust':{'revision':'c79998a5cd143c445a4b2528f20953b176a65c5d'}}
        assert not {'CI','TF_BUILD','RUSTFLAGS','RUSTC_WRAPPER','CARGO_INCREMENTAL'} & su['environment'].keys()
        graphs={}
        for owner in ('ty_server','ruff_db','ty_project'):
            obj=json.loads(gzip.decompress(z.read(owner+'-graph.json.gz')))
            units=obj['units'];rons=[(i,u['features'],u['mode']) for i,u in enumerate(units) if u['target']['name']=='ron']
            assert (rons==[(184,['default','std'],'check')]) if owner=='ty_project' else (not rons)
            graphs[owner]={'units':len(units),'roots':[units[i]['target']['name'] for i in obj['roots']],'ron':rons}
        calibration=[]
        for group,(scope,copies) in enumerate(SCOPES):
            measured=[]
            for visit,count in enumerate([0,20000000,0,20000000]):
                counter,cmds,children=read_trace(z,f'calibration/g{group}-{visit}')
                picked,=[e for e in cmds if e[2]]
                assert Path(picked[3]).name=='cal-selected' and picked[4][1]=='selected'
                selected_pid=picked[0]
                root,= [e for e in cmds if e[0]==counter['root'][0]]
                assert Path(root[3]).name=='driver' and root[4][1]=='outer' and root[4][-4:]==[scope,str(count),str(copies),str(count//2)]
                select=([e for e in cmds if e[0]==selected_pid and Path(e[3]).name=='loop'])[0]
                assert select[4][-3:]==[scope,str(count),str(copies)] and picked[1]!=root[1]
                childset={child for typ,child in children[root[0]]}
                outside,=childset-{selected_pid}
                outer,=[e for e in cmds if e[0]==outside and Path(e[3]).name=='loop']
                assert outer[1]==select[1] and outer[4][-3:]==['0',str(count//2),'1']
                below=set()
                def descend(pid):
                    for typ,c in children[pid]:below.add(c);descend(c)
                descend(selected_pid)
                assert outside not in below
                if scope.isnumeric():assert len(below)==int(scope)*copies
                if scope=='thread':assert len(below)==copies and len(children[selected_pid])==copies
                if scope=='exec':assert any(e[0]==selected_pid and Path(e[3]).name=='env' for e in cmds)
                measured.append([counter['whole'][1],counter['selected'][1]])
            pair=lambda i:statistics.median(j[i] for j in measured[1::2])-statistics.median(j[i] for j in measured[::2])
            whole,part=pair(0),pair(1)
            want=40000000*copies
            assert abs(whole/(want+20000000)-1)<.02 and abs(part/want-1)<.02
            calibration.append({'scope':scope,'copies':copies,'whole_delta':whole,'selected_delta':part})
        phases={}
        for phase in ('edited','first-unchanged'):
            cnt,execs,_=read_trace(z,phase);tool=su['tools']
            names=[]
            for pid,identity,selected,image,args in execs:
                if identity==tuple(tool['cargo']['dev_ino']):assert image==tool['cargo']['physical'] and args[1:]==CARGO
                elif identity==tuple(tool['rustc']['dev_ino']):
                    assert image==tool['rustc']['physical'] and '--out-dir' in args and '--emit=dep-info,metadata' in args
                    n=args[args.index('--crate-name')+1]
                    assert selected==(n=='ron') and (n=='ron')!=any('incremental=' in a for a in args)
                    if n=='ron':assert any('/ron-0.12.0/src/lib.rs' in a for a in args)
                    names.append(n)
                else:assert Path(image).name=='rustup' and args[1:]==['+ohm',*CARGO]
            assert names==(['ron','ty_project'] if phase=='edited' else ['ron']) and len(execs)==len(names)+2
            dep,=[p for p in z.namelist() if p.endswith('.dep.gz')]
            raw=gzip.decompress(z.read(dep));assert digest(raw)==dep.split('.')[0] and raw.count(b'ohm-foreign-span-bytes')==3
            phases[phase]={'whole':cnt['whole'][1],'ron':cnt['selected'][1],'rustcs':names,'native_links':0,'share':cnt['selected'][1]/cnt['whole'][1]}
        small={}
        events={}
        for phase in ('cold','edited','first-unchanged','invalid','repair'):
            stdout=gzip.decompress(z.read(phase+'/stdout.gz'));stderr=gzip.decompress(z.read(phase+'/stderr.gz'))
            records=[json.loads(l) for l in stdout.splitlines()];ok=phase!='invalid'
            assert records[-1]=={'reason':'build-finished','success':ok}
            artifacts=[r for r in records if r['reason']=='compiler-artifact'];assert len(artifacts)==(303 if ok else 302) and not any(r['executable'] for r in artifacts)
            messages=[r for r in records if r['reason']=='compiler-message']
            if phase in ('invalid','repair'):
                err,note=messages
                assert err['target']['name']=='ty_project' and err['message']['level']=='error' and err['message']['code']['code']=='E0308' and note['message']['level']=='failure-note'
                loc,=[s for s in err['message']['spans'] if s['is_primary']]
                assert loc['file_name']=='crates/ty_project/src/lib.rs' and loc['line_start']==1240 and 'OHM_RON_CHECK_BAD_TYPE' in loc['text'][0]['text']
                assert (b'Finished' in stderr)==ok
            else:assert not messages
            facts=json.loads(z.read(phase+'/record.json'))
            assert facts['source_sha']==su['original_blob' if phase=='cold' else 'historical_parent_blob']
            events[phase]=messages
            small[phase]={'exit':0 if ok else 101,'artifact_count':len(artifacts),'messages':[r['message']['level'] for r in messages],
                        'stdout_sha256':digest(stdout),'stderr_sha256':digest(stderr)}
        assert events['invalid']==events['repair']
        r=phases['first-unchanged']
        return {'separate_native_counts':phases,'whole_instruction_ceiling':r['whole']/(r['whole']-r['ron']),
                'phase_verdicts':small,'calibration':calibration,'graphs':graphs,'original_diagnostic_gate':'failed','sha256':DIGEST}

if __name__=='__main__':
    path=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'primary.zip'
    print(json.dumps(run(path),indent=2,sort_keys=True))
