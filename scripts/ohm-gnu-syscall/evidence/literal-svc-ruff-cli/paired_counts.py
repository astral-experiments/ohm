"""Recompute paired Ruff CLI measurements, complete program identities and build allocation."""
import collections
import gzip
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import stat
import statistics
import struct

ORIGINAL_RUN = 41104410375
ORIGINAL_QA = "61127b2e9531769dea162b31a267d86a0368b479"
PARENT='8f42a1c11e66c2a55299914d5025e4fa7549ead4'
CHILD='6ae50e2d0139132d86d4fdf50648a4ddfcb2730e'
DRIVERS=['d57260c5e0aca0d5957a8a4efbd8f6012baa2a9beb3d7b6c8a2cd224dee581aa','d38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084']
CARGO='9fb29f6abecad05acb6015990615c5fbb435a5907543f0bd33cf88cada4f5826'
ABI='aarch64-unknown-linux-gnu'
CMD=['cargo','+ohm','build','-p','ruff','--bin','ruff','--target',ABI,'--locked','--offline','-j4','--message-format=json']
RUFF={'02c02172ceae316dac14a7657d9c85fa8bb1c3ca':'5f59a731d262bb142782a1333d99e894fb1b1cee','193984681ef7185c90b548c27b0ac6326908f2ec':'df36660b9ba5936fbffd96197b0c828e9e5f68c6'}
LOCK='a049c8963abf121b242ebab5481739a33c2cf1d2bbc04b085d60e2e6d52a0b13'
SOURCE={'starred':'a = (1, 2, 3)\nprint((*a, 9)[2])\n','bounds':'print([1, 2][9])\n','valid':'print([1, 2][0])\n'}
sha=lambda v:hashlib.sha256(v).hexdigest()
def counted(row):
    assert row['code']==0 and row['stop']>row['start'] and row['user_us']+row['system_us']>0
    return row['event_errno']==0 and row['instructions']>0 and row['enabled']>0 and row['running']>=.995*row['enabled']

def verify(z, order, confirm, *, original_images=True):
    def raw(p):return z.read('paired/'+p)
    def doc(p):return json.loads(raw(p+'.json'))
    def data(p):return gzip.decompress(raw(p+'.gz'))
    reg=doc('registration');pair=doc('pair')
    assert reg['order']==pair['order']==order and reg['argv']==CMD and reg['source']==[PARENT,CHILD] and reg['driver']==DRIVERS[1]
    candidate=json.loads(z.read('candidate.json'));assert (candidate['source'],candidate['parent'],candidate['driver'][0],candidate['unchanged_members'])==(CHILD,PARENT,DRIVERS[1],118)
    cal=doc('calibration/summary');checks=[];all_valid=[]
    configs=[('0','1'),('1','1'),('2','1'),('2','2'),('exec','1')]+([('thread','1'),('thread','2')] if confirm else [])
    assert len(cal['rows'])==len(configs)*4
    for i,(depth,copies) in enumerate(configs):
        rows=[]
        for pos,it in enumerate([0,80000000,0,80000000]):
            idx=4*i+pos;r=cal['rows'][idx];b=raw(f'calibration/{idx}.json');v=json.loads(b);ok=counted(v)
            assert (r['depth'],r['copies'],r['iters'],r['receipt'],r['hardware'])==(depth,copies,it,sha(b),ok)
            all_valid.append(ok);rows.append(v)
        diff=lambda f:statistics.median(f(v) for v in rows[1::2])-statistics.median(f(v) for v in rows[::2])
        checks.append({'copies':copies,'depth':depth,'expected':160000000*int(copies),'delta':diff(lambda v:v['instructions']),'cpu_delta':diff(lambda v:v['user_us']+v['system_us'])})
    assert checks==cal['checks']
    hw=all(all_valid) and all(abs(c['delta']/c['expected']-1)<.02 for c in checks)
    one=checks[0]['cpu_delta']
    cpu=one>7000 and all(.45*one*int(c['copies'])<=c['cpu_delta']<=2.3*one*int(c['copies']) for c in checks)
    assert (hw,cpu)==(cal['whole_tree_hw'],cal['tree_cpu'])
    def inventory(where):
        ms=list(map(json.loads,data(where+'/stdout').splitlines()))
        assert ms[-1]=={'reason':'build-finished','success':True};units=[x for x in ms if x['reason']=='compiler-artifact']
        root,=[x['executable'] for x in units if x['target']['name']=='ruff' and x['target']['kind']==['bin'] and x['executable']]
        assert root.endswith('/target/'+ABI+'/debug/ruff') and len(units)==372
        roster=sorted(json.dumps([m[k] for k in ('package_id','target','features','profile')],sort_keys=True,separators=(',',':')) for m in units)
        return root,{'roster':sha(json.dumps(roster).encode()),'unit_count':len(units),'dirty':sorted(m['target']['name'] for m in units if not m['fresh'])}
    def probes(where,root,old,product):
        verdict={}
        for case,input in SOURCE.items():
            c=doc(where+'/'+case+'-cmd')
            assert c['source']==input and c['argv']==['qemu-aarch64','-L','/usr/aarch64-linux-gnu',root,'check','--isolated','--no-cache','--select','PLE0643','--output-format','json','--stdin-filename','qa.py','-']
            d=json.loads(data(where+'/'+case+'-stdout'));assert data(where+'/'+case+'-stderr')==b''
            expected=[['PLE0643',1]] if case=='bounds' else [['PLE0643',2]] if old and case=='starred' else []
            actual=[[v['code'],v['location']['row']] for v in d];assert actual==expected and c['exit']==int(bool(expected))
            verdict[case]=actual
        assert product['verdicts']==verdict
    def image(where,product):
        meta=doc(where+'/image');assert meta['sha256']==product['sha256'] and meta['bytes']==product['bytes']
        if not original_images:
            chunks = meta["ordered_MiB_chunks"]
            assert meta["bytes"] > 0 and len(chunks) == (meta["bytes"] + 2**20 - 1) // 2**20
            assert all(len(h) == 64 and bytes.fromhex(h) for h in chunks)
            return
        with os.fdopen(os.memfd_create('original-ruff-ELF'),'w+b') as f:
            digest=hashlib.sha256()
            for i,h in enumerate(meta['ordered_MiB_chunks']):
                b=data('native-elf/chunks/'+h)
                assert sha(b)==h and 0<len(b)<=2**20 and (i==len(meta['ordered_MiB_chunks'])-1 or len(b)==2**20)
                digest.update(b);f.write(b)
            assert f.tell()==meta['bytes'] and digest.hexdigest()==meta['sha256']
            f.seek(0);hdr=f.read(64);assert hdr[:7]==bytes.fromhex('7f454c46020101') and struct.unpack_from('<H',hdr,18)[0]==183
            offset,=struct.unpack_from('<Q',hdr,40);size,count,names=struct.unpack_from('<HHH',hdr,58);assert size==64 and 0<names<count
            f.seek(offset);sections=[struct.unpack('<IIQQQQIIQQ',f.read(size)) for _ in range(count)]
            f.seek(sections[names][4]);strings=f.read(sections[names][5]);code,=[s for s in sections if strings[s[0]:].split(b'\0',1)[0]==b'.text']
            f.seek(code[4]);assert code[5]>0 and sha(f.read(code[5]))==product['text_sha']
    endpoints={n:{} for n in ('edit','repeat','edit+repeat')};arms={}
    for role in 'PC':
        terminal=doc(role+'/terminal');enrol=doc(role+'/enrolment');native=terminal['native'];graph=terminal['graph']
        i='PC'.index(role)
        assert terminal['role']==role and terminal['commands']==enrol['cli']==CMD and enrol['compiler']['source']==[PARENT,CHILD][i]
        assert terminal['compiler']==enrol['compiler'] and enrol['compiler']['driver'][0]==DRIVERS[i] and terminal['cargo']==enrol['cargo_sha']==CARGO
        assert enrol['trees']==RUFF and enrol['lock_sha256']==LOCK and len(enrol['changed'])==2
        assert not {'CI','RUSTFLAGS','CARGO_INCREMENTAL','CARGO_ENCODED_RUSTFLAGS','RUSTC_WRAPPER','LD_PRELOAD'}&enrol['env'].keys()
        assert terminal['hardware_pass']==hw and terminal['tree_cpu_pass']==cpu and native['new']==native['empty'] and native['old']['sha256']!=native['new']['sha256']
        original=graph['edit']['roster'];stamps={}
        for step in ['cold','edit','repeat','independent-empty']+(['independent-old','individual-edit'] if confirm else []):
            prefix=role+'/'+step;root,observed=inventory(prefix);assert observed['roster']==original
            if step in ('edit','repeat','individual-edit'):
                assert observed==graph['edit' if step=='individual-edit' else step]
                assert all((v in observed['dirty'])==(role=='P') for v in ('rustix','tempfile','terminal_size'))
            if step=='edit':assert 'ruff_linter' in observed['dirty']
            if step!='edit':
                isold=step in ('cold','independent-old');p=native['old' if isold else 'new'];probes(prefix,root,isold,p)
                if confirm and step in ('independent-old','independent-empty','individual-edit'):image(prefix,p)
            if step in ('edit','repeat'):
                cl=doc(prefix+'/clock');ok=counted(cl);assert not hw or ok
                stamps[step]=cl
        e,r=stamps['edit'],stamps['repeat'];assert e['stop']<=r['start']
        for phase,a,b,rows in [('edit',e['start'],e['stop'],[e]),('repeat',r['start'],r['stop'],[r]),('edit+repeat',e['start'],r['stop'],[e,r])]:
            metrics={'elapsed_ns':b-a,'tree_cpu_us':sum(v['user_us']+v['system_us'] for v in rows) if cpu else None,'user_instructions':sum(v['instructions'] for v in rows) if hw else None}
            assert metrics==terminal['measurements'][phase]
            endpoints[phase][role]=metrics
        raw_files=json.loads(data(role+'/disk-inodes.json'));unique={};sessions=collections.Counter()
        for label,dev,ino,size,blocks,mode in raw_files:
            p=Path(label);assert p.parts[0] in ('target','shared')
            assert unique.setdefault((dev,ino),(size,blocks,mode))==(size,blocks,mode)
            if 'incremental' in p.parts and stat.S_ISDIR(mode) and p.name.startswith('s-'):sessions[str(p.parent)]+=1
        disk=512*sum(v[1] for v in unique.values())
        assert len(raw_files)==doc(role+'/disk')['count'] and disk==doc(role+'/disk')['allocated']==terminal['disk']==pair['storage'][role] and sessions
        arms[role]={'storage':disk,'physical_incremental_sessions':dict(collections.Counter(sessions.values())),'old':native['old'],'new':native['new'],'roster':original}
    assert arms['P']['roster']==arms['C']['roster'] and all(arms['P'][s]['text_sha']==arms['C'][s]['text_sha'] for s in ('old','new'))
    assert {r:a['new']['sha256'] for r,a in arms.items()}==pair['return_hashes']
    result={n:{m:[v[r][m] for r in 'PC'] for m in v['P']} for n,v in endpoints.items()};assert result==pair['endpoints']
    return {'order':order,'endpoints':result,'arms':arms,'calibration':checks,'cpu':cpu,'hardware':hw,'physical_ELFs':6 if confirm and original_images else 0}

def paired_stats(observations,planned_order):
    assert [p['order'] for p in observations]==planned_order
    results={}
    for end in ('repeat','edit','edit+repeat'):
        row={}
        for m in ('elapsed_ns','user_instructions','tree_cpu_us'):
            values=[p['endpoints'][end][m] for p in observations];v=[(a,b) for a,b in values if a is not None and b is not None]
            if not v:continue
            ratios=[a/b for a,b in v];ranked=sorted(ratios)
            d={'n':len(v),'median':statistics.median(ratios),'ratios':ratios,'median_parent':statistics.median(a for a,b in v),'median_child':statistics.median(b for a,b in v)}
            if len(v)==len(planned_order)==12:
                signed=[math.log(q/2)*(1 if order=='PC' else -1) for q,order in zip(ratios,planned_order)]
                real=statistics.mean(math.log(q/2) for q in ratios)
                scores=[sum(v if i in subset else -v for i,v in enumerate(signed))/12 for subset in itertools.combinations(range(12),6)]
                d.update(median_interval_96_14=[ranked[2],ranked[9]],sharp_2x_p=sum(t>=real-1e-12 for t in scores)/len(scores))
            row[m]=d
        results[end]=row
    return results
