"""Re-read raw successful/failed Cargo streams, actual native execs, PMUs and macro events."""
import argparse
import collections
import functools
import gzip
import hashlib
import json
from pathlib import Path
import struct


def records(body):
    """Measureme v9's three published raw streams, retaining the recorded function arguments."""
    streams = {i:bytearray() for i in range(3)}; version=struct.pack('<I',9)
    assert body[:8]==b'MMPD'+version; pos=8
    while pos<len(body):
        tag,n=struct.unpack_from('<BI',body,pos);pos+=5
        assert 0<n<=len(body)-pos;streams[tag].extend(body[pos:pos+n]);pos+=n
    events,strings,index=(streams[i] for i in range(3))
    assert [s[:8] for s in (events,strings,index)]==[a+version for a in (b'MMES',b'MMSD',b'MMSI')]
    offsets=dict(struct.iter_unpack('<QQ',index[8:]))
    @functools.lru_cache(None)
    def word(k):
        i=offsets[k] if k<100000003 else k-100000003;assert 8<=i<len(strings);out=bytearray()
        while strings[i]!=255:
            if strings[i]==254:out.extend(word(struct.unpack_from('<Q',strings,i+1)[0]));i+=9
            else:out.append(strings[i]);i+=1
        return bytes(out)
    for kind,ident,tid,*_ in struct.iter_unpack('<QQIIII',events[8:]):
        yield word(kind).decode(),word(ident).decode().split('\x1e'),tid


def read(path):return json.loads(path.read_bytes())
def sha(b):return hashlib.sha256(b).hexdigest()


def check(root):
    phys=read(root/'subjects.json')['tools'];results={};inv={};macros={}; diagnostics={}
    phases=('train','edit','repeat','second','invalid','repair','repaired-repeat','profile','empty-edited')
    acquired=read(root/'acquired.json');assert acquired['order']==['sham','session'] and tuple(acquired['phases'])==phases
    selections={}
    assert len(read(root/'calibration/summary.json'))==7 and all(a['admit'] for a in read(root/'calibration/summary.json'))
    control=read(root/'native-boundary/terminal.json');assert control['calls']==[v for v in ('17','29','"invalid"','17') for _ in range(2)] and len(control['visits'])==8
    for i in range(4):
        lhs,rhs=control['visits'][2*i:2*i+2];assert lhs['verdict']==rhs['verdict'] and lhs['code']==rhs['code']==(1 if i==2 else 0)
    subject=read(root/'comparison-subject.json'); actual_cargo=subject['actual_cargo']
    assert actual_cargo['sha256']==subject['cargo']=='f1a88bf5fb2bf431eeea068455d9d4e98dcfbfee3dc381ee47cc7c96df3e128f'
    for mode in ('sham','session'):
        results[mode]={}; inv[mode]={}; diagnostics[mode]={};selections[mode]={}
        for phase in phases:
            p=root/mode/phase; raw=gzip.decompress((p/'stdout.gz').read_bytes());msgs=[json.loads(l) for l in raw.splitlines()]
            assert msgs[-1]=={'reason':'build-finished','success':phase!='invalid'}
            art=[a for a in msgs if a['reason']=='compiler-artifact']; ers=[a['message'] for a in msgs if a.get('message',{}).get('level')=='error']
            if phase=='invalid':assert any((e.get('code') or {}).get('code')=='E0308' for e in ers)
            else:assert not ers
            inv[mode][phase]=sorted((a['package_id'],a['target']['name'],a['target']['kind'],a['features'],a['profile']['test']) for a in art)
            diagnostics[mode][phase]=[a['message'] for a in msgs if a['reason']=='compiler-message']
            assert len(art)==(302 if phase=='invalid' else 303)
            got=[];workers=[];root_pids=[];actual_native=[]
            for line in (p/'trace/exec.tsv').read_text().splitlines():
                idx,pid,dev,ino,picked,img=line.split('\t');a=(p/f'trace/args-{int(idx):04d}').read_bytes();assert a[-1:]==b'\0'
                av=[v.decode() for v in a[:-1].split(b'\0')]
                if img==actual_cargo['physical'] and av[1:3]==['check','-p']:
                    assert [int(dev),int(ino)]==actual_cargo['dev_ino'];root_pids.append(pid)
                if [int(dev),int(ino)]==phys['rustc']['dev_ino'] and '--crate-name' in av and '--out-dir' in av and not any(x.startswith('--print') for x in av):workers.append(av[av.index('--crate-name')+1])
                if Path(img).name in ('ld.bfd','ld','wild','rust-lld','ld.lld') and '-o' in av:actual_native.append(img)
                if picked=='1':
                    assert [int(dev),int(ino)]==phys['rustc']['dev_ino'] and '--emit=dep-info,metadata' in av
                    assert av[av.index('--crate-name')+1]=='ron' and any(a.endswith('/ron-0.12.0/src/lib.rs') for a in av)
                    assert sum(a.startswith('-Cincremental=') for a in av)==(mode=='session')
                    assert sum(a.startswith('-Zself-profile=') for a in av)==(phase=='profile');got.append(av)
            observed=read(p/'observed.json');assert len(root_pids)==len(got)==1 and got[0]==observed['literal_ron_argv']
            selections[mode][phase]={'native_argv':[a for a in got[0] if not a.startswith(('-Cincremental=','-Zself-profile'))],'externs':observed['externs']}
            if phase in ('repeat','second','profile'):assert workers==['ron'] and not actual_native
            counters={name:list(map(int,v)) for name,*v in (l.split('\t') for l in (p/'trace/counts.tsv').read_text().splitlines())}
            assert counters==read(p/'pmu.json') and counters['hits']==[1] and counters['root'][1]==(101 if phase=='invalid' else 0)
            for key in ('selected','whole'):
                status,instr,enabled,running=counters[key];assert status==0 and instr>0 and enabled==running and running>0
            tab=read(p/'session.json'); by_ino={tuple(a[2:]):a[1] for a in tab['files'].values()}
            assert sum(by_ino.values())==tab['allocated'] and (tab['allocated']>0)==(mode=='session')
            if mode=='session':
                graphs=[Path(n).parent for n in tab['files'] if Path(n).name=='dep-graph.bin'];tables=[Path(n).parent for n in tab['files'] if Path(n).name=='query-cache.bin']
                assert len(graphs)==1 and graphs==tables
            _,digest,size=observed['rmeta']; body=gzip.decompress((root/'rmeta-blobs'/(digest+'.gz')).read_bytes()); assert len(body)==size and sha(body)==digest
            results[mode][phase]={'whole':counters['whole'][1],'ron':counters['selected'][1],'allocated':tab['allocated'],
                                  'regular_file_storage':observed['regular_file_storage'],'rustcs':workers,'links':len(actual_native),'rmeta':observed['rmeta'][1]}
        warm=root/mode/'repeat';empty=root/mode/'empty-edited'
        assert inv[mode]['repeat']==inv[mode]['empty-edited'] and diagnostics[mode]['repeat']==diagnostics[mode]['empty-edited']
        assert read(warm/'reader.json')==read(empty/'reader.json')
        assert results[mode]['repeat']['rmeta']==results[mode]['empty-edited']['rmeta']
        dump,=(root/(mode+'-profiles')).glob('*.mm_profdata'); events=list(records(dump.read_bytes()))
        counts=collections.Counter(k for k,_,_ in events)
        inner=[a for k,a,_ in events if k=='GenericActivity' and a[0]=='expand_proc_macro'];outer=[a for k,a,_ in events if k=='GenericActivity' and a[0]=='expand_derive_proc_macro_outer']
        assert len(inner)==len(outer)==16 and all(len(a)>1 for a in inner+outer)
        macros[mode]={'inner':sorted(inner),'outer':sorted(outer),'categories':dict(counts),'profile_sha256':sha(dump.read_bytes())}
        if mode=='session':assert counts['IncrementalLoadResult']>0
    assert inv['sham']==inv['session'] and diagnostics['sham']==diagnostics['session']
    assert selections['sham']==selections['session']
    assert macros['sham']['inner']==macros['session']['inner'] and macros['sham']['outer']==macros['session']['outer']
    ratios={s:results['sham'][s]['whole']/results['session'][s]['whole'] for s in ('edit','repeat','second')}
    return {'kind':'mechanism feasibility, single installation per policy, no release claim','modes':results,'macros':macros,'whole_ratios':ratios,
            'promote_to_independent_confirmation':all(ratios[s]>=2 for s in ('repeat','second'))}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('raw_packet',type=Path)
    print(json.dumps(check(parser.parse_args().raw_packet),sort_keys=True,indent=2))
