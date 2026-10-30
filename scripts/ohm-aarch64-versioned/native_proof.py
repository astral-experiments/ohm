"""Independently reopen GNU provider bodies, the actual consuming linker and exact old/new Cargo dep-info."""
import ast
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tarfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from outputs import encoded_file
from ruff_subjects import REG
from native_kits import CLASSIC,CLASSIC_ELF,rt
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
from verify_native import logs,EXEC,expect

H=lambda b:sha256(b).hexdigest()
V1='/dev/null/ohm-recheck-dependent-links'
V2=V1+'-v2'
HARD='/dev/null/ohm-untracked-relink-inputs'
MIGRATION={
    'trained-repeat':'17 7','upgrade-higher':'29 7','upgrade-unchanged':'29 7','upgrade-restamped':'29 7',
    'downgrade-unchanged':'29 7','downgrade-malformed':None,'upgrade-malformed':None,'upgrade-missing':None,
    'upgrade-repaired':'17 11','downgrade-repaired':'17 11',
}
def command(z,p):
    cmd=json.loads(z.read(p+'/command.json'))
    out,err=(gzip.decompress(z.read(f'{p}/{x}.gz')) for x in ('stdout','stderr'))
    assert (cmd['stdout'],cmd['stderr'])==(H(out),H(err))
    return cmd,out,err

def trace_entries(wire):
    with tarfile.open(fileobj=io.BytesIO(wire)) as tar:
        for f in tar:
            if not f.isfile():continue
            body=tar.extractfile(f).read()
            for line in body.splitlines():
                if not line.startswith((b'execve(',b'execveat(')) or not line.endswith(b'= 0'):continue
                match=EXEC.fullmatch(line);assert match,line[:180]
                exe,argv=(ast.literal_eval(x.decode()) for x in match.groups())
                yield exe,argv,int(f.name.rsplit('.',1)[1]),H(body)

def direct(z):
    committed=json.loads(z.read('direct-terminal.json'));sets={}
    allowed={'ordinary','general_only','vector_only','compact_input','compact_copy','external'}
    for role in 'PC':
        base='direct-version-'+role;wire=z.read(base+'/complete.json');row=json.loads(wire)
        assert H(wire)==committed[role] and list(row['driver'].values())==[REG['drivers'][role]]
        assert row['source']==REG['source']['rust']['source' if role=='C' else 'parent']
        assert len(row['cases'])==29 and allowed<=row['cases'].keys();sets[role]={}
        for label,obs in row['cases'].items():
            c,out,err=command(z,base+'/'+label)
            want=(V2 if role=='C' else V1) if label in allowed else HARD
            status=int(label=='bundled' or label.startswith('missing-'))
            assert c['exit']==obs['status']==status and c['argv'][:2]==['rustc','+ohm']
            assert c['argv'][c['argv'].index('--target')+1]=='aarch64-unknown-linux-gnu'
            assert c['stdout']==obs['depfile'] and c['stderr']==obs['diagnostic']
            assert [v for v in (V1,V2,HARD) if (v+':').encode() in out.splitlines()]==[want]
            if status:assert (b'qa_unavailable_library' if label=='bundled' else b'payload.bin') in err
            sets[role][label]=[status,want,c['stdout'],c['stderr']]
    return {'terminals':committed,'checks':sets}

def named(z):
    committed=json.loads(z.read('named-terminal.json'));checks={}
    for mode,ordinary in [('none',[]),('v1',[V1]),('v2',[V2]),('both',[V1,V2])]:
        root='named-'+mode;wire=z.read(root+'/complete.json');info=json.loads(wire)
        assert info['ordinary_names']==ordinary and info['compiler']==REG['source']['rust']['source'] and H(wire)==committed[mode]
        checks[mode]={};elfs=set()
        for phase in ('cold','repeat','empty'):
            p=root+'/'+phase;row=info['cases'][phase]
            cmd,out,_=command(z,p+'/ordinary')
            lines=[json.loads(l) for l in out.splitlines()];assert lines[-1]=={'reason':'build-finished','success':True} and not cmd['exit']
            assert row['typed'] in lines
            c,out,_=command(z,p+'/qemu');assert c['argv'][0].endswith('/qemu-aarch64') and c['exit']==0 and out==b'17\n'
            elf=z.read('objects/'+row['body']+'.elf');assert H(elf)==row['body'] and elf[:6]==b'\x7fELF\x02\x01' and int.from_bytes(elf[18:20],'little')==183
            elfs.add(row['body'])
            wire=z.read(p+'/trace.tar.gz');assert H(wire)==row['kernel']
            execs=list(trace_entries(wire))
            cargo,=[a for _,a,__,___ in execs if _.endswith('/rustup/toolchains/ohm/bin/cargo')];assert cmd['argv'][cmd['argv'].index('cargo')+2:]==cargo[1:]
            rust=[(a,pid,b) for e,a,pid,b in execs if e.endswith('/rustup/toolchains/ohm/bin/rustc') and '--crate-name' in a and a[a.index('--crate-name')+1]=='qa_collision']
            assert [v['argv'] for v in row['physical_root_rustcs']]==[v[0] for v in rust]
            assert bool(rust)==(phase!='repeat' or mode!='none') and row['cargo']==REG['cargo_elf']
            for n,f in row['files'].items():
                data=z.read(p+'/actual-files/'+f['sha256']);assert H(data)==f['sha256']
                if f['kind']=='encoded':
                    actual=encoded_file(data);assert actual['marker_v2'] and actual['has_LNK1']==(not ordinary)
                else:
                    own,=[l for l in data.decode().splitlines() if l.startswith(n+': ')]
                    assert sorted(n for n in own.split(': ',1)[1].split() if n in (V1,V2))==sorted(ordinary)
                    assert sorted(q[:-1] for q in data.decode().splitlines() if q in (V1+':',V2+':'))==sorted(ordinary+[V2])
            checks[mode][phase]={'ELF':row['body'],'kernel':row['kernel'],'producer_full':len(rust)}
        assert len(elfs)==1
    return {'terminals':committed,'checks':checks}

def provider(z,mode):
    read=lambda p:json.loads(z.read(p))
    info=read('versioned-native-terminal.json');selections=read('all-product-selections.json')
    assert info['mode']==mode and selections['registered']==REG
    assert info['sources']=={'signed':rt.CARGO_SOURCE,'classic':CLASSIC,'aware':REG['source']['cargo']['source']}
    legacy=mode=='legacy-writer';migrating=mode.startswith('migrate-')
    assert info['compiler']==REG['source']['rust']['parent' if legacy else 'source']
    want_driver=REG['drivers']['P' if legacy else 'C'];ids=selections['identities']
    assert {k:v['sha256'] for k,v in ids.items()}=={'signed':rt.TOOLS['bin/cargo'],'classic':CLASSIC_ELF,'aware':REG['cargo_elf']}
    for i,s in enumerate(selections['visits']):
        name=s['name'];assert s['cargo']==ids[name] and s['driver']['sha256']==want_driver
        p=f'versions/{i:03}-{name}';c,out,_=command(z,p)
        assert c['argv']==['cargo','+ohm','-Vv'] and not c['exit'] and 'commit-hash: '+info['sources'][name] in out.decode()
        assert H(z.read(p+'/command.json'))==s['version_receipt']
    assert (len(info['rosters']),len(selections['visits']))==(2 if legacy or migrating else 6,10 if migrating else 2 if legacy else 6)
    all_results={};elfs={}
    for label,terminal in info['rosters'].items():
        body=z.read(label+'/completed.json');finished=json.loads(body)
        assert finished['defaults'] and finished['source']==info['compiler'] and H(body)==terminal['terminal']
        placement=finished['placement'];crate='barrier' if placement=='library' else 'qa_owned_test'
        reports={r['name']:r for r in finished['cases']};answers=MIGRATION if migrating else expect
        assert len(reports)==(21 if migrating else 18) and len(finished['cases'])==len(reports)
        physical={}
        for name,row in reports.items():
            n=name.removeprefix('empty-');ans='17 7' if n=='cold-lower' else answers[n]
            p=label+'/'+name;assert read(p+'/result.json')==row
            s=logs(z,p,101 if ans is None else 0,row['elf'],True,elfs)
            assert s['answer']==ans and s['actual_provider_ld']>=1
            early=n in ('higher','upgrade-higher','upgrade-unchanged')
            if ans is not None:assert s['selected_provider']==(['early'] if early else ['late'])
            elif 'missing' in n:assert s['selected_provider']==[] and s['earlier_negative'] and s['later_negative']
            else:assert s['selected_provider']==['late'] and s['earlier_negative']
            if n=='restored-repeat' and mode in ('signed','classic'):
                successful=[a for e,a,_,__ in trace_entries(z.read(p+'/trace.tar.gz')) if e.endswith('/rustup/toolchains/ohm/bin/rustc') and '--crate-name' in a and a[a.index('--crate-name')+1]==crate and not any(v.startswith('-Zlink-only') for v in a)]
                assert successful, (mode,n,crate)
            provenance=p+'/actual-dep-info-provenance.json'
            if not name.startswith('empty-') and row['exit']==0:
                raw=read(provenance);assert raw['crate']==crate
                entries={k:v for k,v in raw['files'].items() if v['kind']=='encoded'}
                names=raw['matched_openat'] or list(entries)
                assert names
                for f in raw['files'].values():
                    data=z.read(p+'/actual-files/'+f['sha256']);assert H(data)==f['sha256'] and len(data)==f['len']
                for k in names:
                    f=entries[k];d=encoded_file(z.read(p+'/actual-files/'+f['sha256']))
                    assert d['has_LNK1']==(raw['selection']=='aware') and d['marker_v2']==(not legacy)
                    assert all(f[q]==v for q,v in d.items())
            s['source_specific_terminal']=terminal['rows'][name]['kernel_trace'];assert s['source_specific_terminal']==s['opening_trace']
            physical[name]=s
        for n in answers:
            cold='empty-'+('restored-edit' if n=='restored-repeat' else n)
            for k in ('answer','elf','cargo_exit','selected_provider','earlier_negative','later_negative'):
                assert physical[n][k]==physical[cold][k],(label,n,k)
        extra={}
        if migrating:
            m=read(label+'/same-physical-roots.json');first=mode.removeprefix('migrate-')
            assert m['variants']==[first,'aware',first,'aware',first] and len(set(tuple(v) for v in m['source_target_shared']))==3
            assert set(m['pairs'])==set(answers) and all(m['pairs'][n]==[physical[n]['elf'],physical['empty-'+n]['elf']] for n in answers)
            extra['same_physical_roots']=H(z.read(label+'/same-physical-roots.json'))
        else:
            m=read(label+'/physical-provider-bytes.json')
            for change in ('value','malformed','repair'):
                a,b=(m[change][s] for s in ('before','after'))
                assert a['nlink']==1 and all(a[k]==b[k] for k in ('dev','ino','mtime_ns','size','mode','nlink')) and a['sha256']!=b['sha256']
                for s in (a,b):
                    by=z.read('objects/'+s['sha256']+'.a');assert len(by)==s['size'] and H(by)==s['sha256']
            extra['same_inode_mutations']=H(z.read(label+'/physical-provider-bytes.json'))
        all_results[label]={'phases':physical,**extra}
    return {'mode':mode,'terminal':H(z.read('versioned-native-terminal.json')),'histories':all_results,'ELFs':elfs,
            'total_Cargo':sum(len(v['phases']) for v in all_results.values()),'physical_switches':selections['visits']}
