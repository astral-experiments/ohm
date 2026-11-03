"""Independently reopen the three original Ron frontier/role Actions ZIPs, in the order below."""
from pathlib import Path
import gzip
import hashlib
import json
import sys
import zipfile

SPECS=[
    (41627244884,13227000801,'7a7c03e6a296c212da3107b9a676dc406024f8a3',16473,'e2087843eac1f6cc61407897d1a45f1656c697ef0d42ae65e5efa89624ea54d8'),
    (41627562321,13227275399,'b0e72506cbe9c0784d87bdbdda61fc7c1471070d',33640,'5978bc1ac4c0f8afa51db130105f317147bc90a1203732f1f71bcc97ac28cb32'),
    (41628218885,13225974689,'f6f60accb8892ccb8f05fed0036126bc2896d0b1',82650,'b2e13b426ab0969f97fdc913247bb9098274690685e0b1cbbc2fdcf9df4c731c')]
ROOT_LIBRARY='da159c2ae58df1a78438e7afb316ae9e4659ce0a9fabccba7e83a3a1de8b70b3'
DRIVER='53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52'
QASOURCE='bfa2407e98ee1343caeefd02b4b69043509baa8c'
EARLIER='74933fe90daeb5b2b8d0b4ec48bd9d84356a7991028cf185c0734e744b930acc'


def read_json(z,p):
    return json.loads(z.read(p))


def begin(p,spec):
    run,artifact,rev,size,digest=spec
    assert p.stat().st_size==size and hashlib.sha256(p.read_bytes()).hexdigest()==digest
    z=zipfile.ZipFile(p)
    assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
    reg=read_json(z,'registration.json')
    assert reg['run']==str(run)and reg['head']==rev and reg['source']==QASOURCE
    s=read_json(z,'sdk-proof.json');assert 'd57fd1515986dccecdcece8da85e651bfb4b81f9'in s['rustc']and '7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed'in s['cargo']
    return z,reg


def gdb(z,reg,n):
    d=read_json(z,'results.json');assert reg['driver']==DRIVER and reg['previous_sha']==EARLIER
    cal=[]
    for m in (1000000,4000000):
        name=f'cal-{m}';v=read_json(z,name+'/counter.json')
        assert v['exitcodes']==[0] and v['events']==[]and v['enabled']==v['running']>0 and 8*m<=v['retired_user']<8*m+350000
        assert f'two actual workers {8*m}'.encode()in z.read(name+'/stdout')
        cal.append(v['retired_user'])
    assert 3.90<cal[1]/cal[0]<4.02
    native=[];argv=None
    for i,kind in enumerate(reg['order'][:n]):
        name=f'normal-{i}';v=read_json(z,name+'/counter.json');p=read_json(z,name+'/plan.json')
        if argv is None:argv=p['argv']
        assert p['argv']==argv and not any('incremental='in str(s)for s in argv)
        assert v['enabled']==v['running']>0 and d[name]['retired_user']==v['retired_user']
        names=[s[0]for s in v['events']]
        expected=['derive']*16+['analysis_complete']+([]if kind=='analysis_complete'else ['backend_entry'])
        assert names==expected
        assert all(a=={'derive':0x6525f80,'analysis_complete':0x6e96b80,'backend_entry':0x6e99a84}[k]for k,a,t in v['events'])
        products=d[name]['products'];assert any(key.endswith('.d')for key in products)
        if kind=='full':
            assert products['libron-0b42003ff6bbcee9.rlib']==ROOT_LIBRARY and v['exitcodes']==[0]and not v['stops']and d[name]['native']=='bits=2 rendered=2'
        else:
            assert v['exitcodes'] in ([None],[])and v['stops']==[kind] and not any(key.endswith('.rlib')for key in products)
            assert any(key.endswith('.rmeta')for key in products)==(kind=='backend_entry')
        native.append([kind,v['retired_user']])
    return {'calibration':cal,'frontiers':native,'derive_entries':16,'boot':reg['boot']}


def native_sources(z,reg):
    d=read_json(z,'result.json');assert reg['role']==EARLIER
    kinds=['split-fresh','split-warm-prior-products-present','split-independent-cold-repair']
    stubs={}
    for name in kinds:
        q=d[name];raw=gzip.decompress(z.read(name+'/file-syscalls.gz')).decode().splitlines()
        rows=[l for l in raw if '/stub.rmeta"'in l and 'openat('in l]
        creates=[l for l in rows if 'O_CREAT' in l and 'ENOENT'not in l]
        missing=[l for l in rows if 'O_RDONLY' in l and 'ENOENT'in l]
        successful_reads=[l for l in rows if 'O_RDONLY' in l and 'ENOENT'not in l]
        fail=name==kinds[1]
        assert len(missing)==int(fail)and len(successful_reads)==int(not fail)and len(creates)==int(not fail)
        assert q['returncode']==int(fail)and bool(q['messages'])==fail
        if fail:
            assert q['before']==d['split-fresh']['after']and {Path(p).suffix for p in q['before']}=={'.d','.rlib','.rmeta'}
            assert [e[0]for e in q['artifact_events']]==['dep-info']
            assert any('failed to create encoded metadata from file: No such file or directory' in m for m,c,s in q['messages'])
        else:assert z.read(name+'/typed-stdout')==b'2 2\n'
        stubs[name]=rows
    assert d['split-fresh']['argv']==d[kinds[1]]['argv']==d[kinds[2]]['argv']
    assert 'embed-metadata=no'in d[kinds[1]]['argv']
    full=d['embedded-training']['argv'];assert len(full)==len(d['split-fresh']['argv'])and [(x,y)for x,y in zip(d['split-fresh']['argv'],full)if x!=y]==[('embed-metadata=no','embed-metadata=yes')]
    costs={};bad=[]
    for name,q in d.items():
        if name in kinds:continue
        v=read_json(z,name+'/counter.json');assert v==q['counter']and v['enabled']==v['running']>0 and v['status']==q['returncode']<<8
        elves={Path(k).suffix:h for k,h in q['after'].items()}
        costs[name]={'instructions':v['instructions'],'enabled':v['enabled'],'running':v['running'],'session_bytes':q['bytes'],'allocated_files':q['files'],'rlib':elves.get('.rlib'),'rmeta':elves.get('.rmeta'),'native':None}
        if name.startswith('embedded-'):assert q['argv']==full
        if not q['returncode']:
            native=z.read(name+'/typed-stdout').decode().strip();assert native==('1 1'if name in ('embedded-source-edit','embedded-source-repair','embedded-independent-clean-edit')else'2 2')
            costs[name]['native']=native
        else:
            assert not any(t=='link'for t,p in q['artifact_events'])
            raw=[json.loads(l)for l in z.read(name+'/stderr').splitlines()if l.startswith(b'{')]
            observed=[(row['code']['code'],Path(s['file_name']).name,s['line_start'],s['column_start'],s['column_end'])for row in raw if row.get('level')=='error'and row.get('code')for s in row['spans']if s['is_primary']]
            expect=[('E0308','extensions.rs',60,15,31)]if name=='embedded-invalid-rust'else[('E0782','extensions.rs',5,83,94),('E0782','public.rs',17,37,98)]
            assert sorted(observed)==sorted(expect);bad.append([name,observed])
    assert len(bad)==2 and costs['original-native']['rlib']['sha256']==ROOT_LIBRARY
    for name in ['embedded-warm-1','embedded-warm-2']:
        fresh=d[name]['new_objects'];previous=(d['embedded-training']if name.endswith('1')else d['embedded-warm-1'])['new_objects']
        keys=lambda rows:{(x['name'],x['dev'],x['ino'],x['sha'])for x in rows}
        assert len(d[name]['new_session'])==1 and len(fresh)==len(keys(fresh))==68 and keys(previous)==keys(fresh)and all(x['prior']for x in fresh)
        costs[name]['new_session_prior_native_inode_and_digest_matches']=68
    assert len({costs[n]['rlib']['sha256']for n in ('embedded-training','embedded-warm-1','embedded-warm-2')})>1
    return {'boot':reg['boot'],'actual_stub_syscalls':stubs,'source_errors':bad,'counted_roles':costs}


def main(args):
    assert len(args)==3
    pairs=[begin(Path(p),s)for p,s in zip(args,SPECS)]
    results=[gdb(*pairs[0],3),gdb(*pairs[1],6),native_sources(*pairs[2])]
    assert len({s['boot']for s in results})==3
    first=read_json(pairs[1][0],'raw-normal/counter.json')
    assert first['enabled']==first['running']>0 and first['status']==0
    results[1]['direct_whole']=first
    print(json.dumps({'originals':[dict(zip(('run','artifact','head','bytes','sha256'),s))for s in SPECS],'partial_frontiers':results[0],'complete_frontiers':results[1],'native':results[2]},indent=2,sort_keys=True))


if __name__=='__main__': main(sys.argv[1:])
