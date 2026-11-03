"""Verify instruction samples against raw perf.data, then report sampled task and symbols."""
import argparse
import bisect
import collections
import gzip
import hashlib
import json
import os
import re
import struct
import subprocess
import zipfile
from pathlib import Path

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(b):
    return hashlib.sha256(b).hexdigest()

def perf_rows(data,expected_period):
    marker, header_size, attr_size, attrs, attr_bytes, first, span = struct.unpack_from('<7Q', data)
    require(marker == int.from_bytes(b'PERFILE2','little') and header_size == 104 and attr_size == attr_bytes and first+span <=len(data),'perf header')
    kind, size, config, freq, flags = struct.unpack_from('<IIQQQ',data,attrs)
    require((kind,config,freq,flags)==(0,1,expected_period,295) and 64<=size<=attr_size,'require sole retired-user event with IP,TID,TIME,CALLCHAIN,PERIOD')
    # PERF_RECORD_SAMPLE obeys the documented kernel layout, with PERIOD before CALLCHAIN.
    control=struct.unpack_from('<Q',data,attrs+40)[0]
    require(control&(1<<5) and control&(1<<6) and not control&(1<<4),'counter does not isolate user instructions')
    modes=collections.Counter()
    events=collections.Counter()
    names=collections.Counter()
    task_names=collections.defaultdict(list)
    pos=first
    while pos<first+span:
        record,misc,width=struct.unpack_from('<IHH',data,pos)
        require(width>=8 and pos+width<=first+span,'record bounds')
        names[record]+=1
        if record==3:
            pid,tid=struct.unpack_from('<II',data,pos+8)
            label=data[pos+16:pos+width].split(b'\0',1)[0]
            require(len(label)<=15,'kernel task name')
            task_names[pid,tid].append(label.decode(errors='replace'))
        if record==9:
            require(misc & 7 in (1,2) and width>=48,'unrecognized delivery mode')
            modes[misc&7]+=1
            ip,pid,tid,time,period,count=struct.unpack_from('<QIIQQQ',data,pos+8)
            require(period==freq and 48+count*8==width,'complete callchain')
            events[(pid,tid,time,period,ip)]+=1
        pos+=width
    require(names[2]+names[5]+names[6]+names[13]==0 and names[9]>0,'lost/throttled event')
    return events,names,modes,task_names

def native_name(path):
    s=os.path.basename(path)
    return re.sub(r'-[0-9a-f]{16}(?=\.so)', '', s)

def classify(path,name):
    d=native_name(path)
    if d.startswith('libLLVM'):return 'LLVM'
    if d=='rustc':return 'rustc executable'
    if 'rustc_driver' not in d:
        return d or 'unmapped'
    if 'dep_graph::' in name or 'DepGraph' in name or 'on_disk_cache' in name or 'rustc_incremental' in name:
        return 'incremental graph and query records'
    if '::bridge::' in name and ('proc_macro' in name or 'rustc_expand' in name):return 'proc-macro bridge'
    if 'stable_hash' in name or 'HashStable' in name or 'SipHasher' in name or 'calculate_hash' in name or 'stable_hasher' in name or 'blake3' in name:
        return 'explicit hashing symbols'
    if 'rustc_resolve' in name:return 'name resolution'
    if 'rustc_expand' in name or 'rustc_builtin_macros' in name:return 'syntax expansion'
    if 'rustc_parse' in name or 'rustc_ast' in name:return 'AST and parser'
    if 'rustc_metadata' in name or 'rustc_serialize' in name:return 'metadata or codec'
    if any(i in name for i in ('rustc_hir_typeck','rustc_hir_analysis','rustc_trait_selection','rustc_borrowck','rustc_infer')):return 'type, trait and borrow checking'
    if 'rustc_monomorphize'in name:return 'monomorphization and partitioning'
    if 'rustc_codegen' in name:return 'codegen'
    if 'rustc_query' in name:return 'remaining query system'
    if not name or name=='[unknown]':return 'unresolved rustc driver'
    return 'other rustc driver'

def ranks(c):
    return sorted(c.items(),key=lambda x:(-x[1],x[0]))

def main(zpath,expected,out,period):
    require(sha(zpath.read_bytes())==expected,'original archive SHA')
    with zipfile.ZipFile(zpath)as z:
        require(z.testzip() is None and 'accepted.json'in z.namelist(),'missing terminal acceptance')
        perf=subprocess.check_output(['zstd','-qdc'],input=z.read('sampled-edit/kernel.perf.zst'))
        raw,kinds,modes,thread_names=perf_rows(perf,period)
        decoded=[json.loads(x) for x in gzip.decompress(z.read('sampled-edit/samples.ndjson.gz')).splitlines()]
        symbols={r[1]:r[2:] for r in decoded if r[0]=='f'}
        samples=[r for r in decoded if r[0]=='s']
        require(len(symbols)+len(samples)==len(decoded) and all(r[1]=='instructions:u'for r in samples),'unknown decoded row')
        canonical=collections.Counter((r[2],r[3],r[4],r[5],r[6][1]) for r in samples)
        require(canonical==raw,'decoded samples differ from original event IP/PID/TID/time/period')
        # GNU binutils handles both v0 names and native names, with bracketed crate metadata removed only for display.
        ids=sorted(symbols);mangled=[symbols[i][1]for i in ids]
        require(all('\n'not in s for s in mangled),'multiple symbols per line')
        plain=subprocess.check_output(['c++filt','-n'],input=('\n'.join(mangled)+'\n').encode()).decode().splitlines()
        require(len(plain)==len(ids),'symbol count')
        names={i:re.sub(r'\[[a-f0-9]{8,16}\]', '',s)for i,s in zip(ids,plain)}
        owners=json.loads(z.read('sampled-edit/owners.json'))
        observed={x['image']:x for x in owners['all_execs']}
        known={x['image']:x['owner']for x in owners['lifetimes']}
        epochs=collections.defaultdict(list)
        for l in z.read('sampled-edit-actual-execs/epochs.tsv').decode().splitlines():
            f=l.split()
            if f[0]!='I':continue
            image,pid,_,stamp=map(int,f[1:5]);epochs[pid].append((stamp,image))
            raw_image=z.read(f'sampled-edit-actual-execs/{image:05}.nul').split(b'\0')
            require(int(raw_image[0])==pid and raw_image[-1]==b'','actual full kernel image record')
            path=raw_image[3].decode()
            if image not in observed:
                observed[image]={'path':path,'identity':list(map(int,raw_image[1:3]))}
                if f[5]=='first' and any(v['owner']=='wild' and v['identity']==observed[image]['identity'] for v in owners['lifetimes']):
                    known[image]='wild fork worker'
        scores=collections.defaultdict(lambda:{s:collections.Counter()for s in ['dsos','families','leaf','seen_frames','seen_families']})
        by_cgu=collections.defaultdict(lambda:{s:collections.Counter()for s in ['dsos','families','leaf','seen_frames','seen_families']})
        for _,_,pid,tid,stamp,weight,leaf,frames in samples:
            history=epochs[pid];loc=bisect.bisect_right(history,(stamp,1<<32))
            image=history[loc-1][1]if loc else -1
            role=known.get(image,native_name(observed.get(image,{}).get('path','')) or 'outside traced Cargo image')
            leaf_id=leaf[0];dso=native_name(symbols[leaf_id][0]);label=names[leaf_id]
            picked=[scores[role]]
            work={v for v in thread_names[(pid,tid)]if v.startswith(('opt ','cpy '))}
            if role.startswith('rustc:ruff:') and work:
                require(len(work)==1,'worker changed codegen assignment')
                event=next(iter(work))
                picked.append(by_cgu[role+' '+(event if event.startswith('opt ')else 'cpy')])
            # Inclusive reported only as observed; these frames overlap.
            walked={(native_name(symbols[x][0]),names[x])for x,_ in [leaf,*frames]}
            for spec in picked:
                spec['dsos'][dso]+=1;spec['families'][classify(dso,label)]+=1;spec['leaf'][dso+' '+label]+=1
                spec['seen_frames'].update({d+' '+s for d,s in walked});spec['seen_families'].update({classify(d,s)for d,s in walked})
        result={'archive_sha256':expected,'original_perf_sha256':sha(perf),'raw_sample_count':sum(raw.values()),'event_period':period,'codegen_sampled_subsets':{k:{q:ranks(x)for q,x in v.items()}for k,v in by_cgu.items()},'delivery_modes':modes,'record_types':kinds,'selected_lifetimes':[{k:v for k,v in l.items()if k!='argv'}for l in owners['lifetimes']],'task_totals':{k:sum(v['dsos'].values())for k,v in scores.items()},'tasks':{k:{q:ranks(x)for q,x in v.items()}for k,v in scores.items()}}
        out.write_text(json.dumps(result,sort_keys=True,indent=1)+'\n')
        for k in known.values():
            if k in scores:
                v=scores[k];print(k,sum(v['families'].values()),str(ranks(v['families'])[:6])[:250])
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('archive',type=Path);p.add_argument('sha');p.add_argument('out',type=Path);p.add_argument('--period',type=int,choices=(1_000_003,8_000_009),default=1_000_003);a=p.parse_args();main(a.archive,a.sha,a.out,a.period)
