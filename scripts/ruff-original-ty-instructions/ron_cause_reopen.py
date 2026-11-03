"""Independently open the immutable first causal packet, including a partial terminal refusal."""
from collections import Counter
from pathlib import Path
import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess as sp
import sys
import zipfile

RUN=41621281440
HEAD='5bbcf310dc4f1d1717d289cccdf4540df57b0c3f'
ORIGINAL=41617756983
OHM='repos/astral-experiments/ohm/'
HASH=lambda s:hashlib.sha256(s).hexdigest()
def hfile(p):
    with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,x):p.write_text(json.dumps(x,indent=1,sort_keys=True)+'\n')


def unpack(z,remove):
    def js(n):
        q=z.read(n)
        return json.loads(gzip.decompress(q) if n.endswith('.gz') else q)
    def sig(n):
        with z.open(n)as f:return hashlib.file_digest(f,'sha256').hexdigest()
    names=set(z.namelist())
    r=js('registration.json')
    assert r['run']==str(RUN) and r['original']==ORIGINAL and r['source']==HEAD and len(r['study']['default_members'])==55
    out={'boot':r['boot'],'old':r['study']['old'],'new':r['study']['new'],'states':{},'phases':[]}
    if 'unit-graph.json.gz' not in names:return out
    graph=js('unit-graph.json.gz')
    assert len(graph['units'])==693 and len(graph['roots'])==118
    rons=[(i,u['pkg_id'],u['features'])for i,u in enumerate(graph['units'])if u['target']['name']=='ron']
    out['ron_graph']=rons
    for side in ('old','new'):
        states={}
        for phase in ('untouched','ablated','restored'):
            label=side+'-'+phase
            p=label+'/'
            if p+'producer/dep-record' not in names:continue
            raw=z.read(p+'producer/dep-record')
            rustc=z.read(p+'producer/rustc-d')
            rsmeta=sig(p+'producer/metadata.rmeta');rslib=sig(p+'producer/archive.rlib')
            o=js(p+'owner-census.json.gz')
            roles={k['epoch']:k for k in o['roles']}
            parents={};records={};maps={};clock=None
            for line in z.read(p+'tasks/epochs.tsv').decode().splitlines():
                v=line.split()
                if v[0]=='I':
                    idx,pid,tid=map(int,v[1:4]);key=roles[idx]
                    expr=z.read(p+'tasks/'+key['argv']);argv=expr.split(b'\0')
                    assert HASH(expr)==key['argv_sha256'] and list(map(int,argv[:3]))==[pid,key['dev'],key['ino']] and key['path']==os.fsdecode(argv[3])
                    assert (tid,key['trigger'])==(key['tid'],v[5]);args=list(map(os.fsdecode,argv[4:-1]))
                    if v[5]=='exec':
                        records[idx]=(pid,args);maps.setdefault(pid,[]).append(idx)
                elif v[0]=='F':
                    parent,caller,child,event=map(int,v[1:]);assert child not in parents;parents[child]=parent
                elif v[0]=='W':clock=list(map(int,v[1:]))
            assert clock and clock[-1]==0 and clock[:3]==o['outer'][:3]
            cls=Counter();outputs={}
            for idx,(pid,args) in records.items():
                k=roles[idx]
                if k['path'].endswith('/sdk/bin/rustc'):
                    only=any(a=='-Zlink-only' or a=='-Zlink-only=yes' or i>0 and args[i-1]=='-Z' and a in('link-only','link-only=yes')for i,a in enumerate(args))
                    st='link-only' if only else 'test' if '--test'in args else 'config' if '--crate-name'not in args else 'full'
                    assert st==k['mode'];cls[(st,k['crate'])]+=1
                elif k['mode']=='Wild':
                    assert '-o'in args and args[args.index('-o')+1]==k['output']
                    owner=None;seen=set()
                    while pid in parents:
                        assert pid not in seen;seen.add(pid);pid=parents[pid]
                        found=[i for i in maps.get(pid,[])if i<=idx and roles[i]['mode']in('full','test','link-only')]
                        if found:owner=found[-1];break
                    assert owner==k['owning_rustc_epoch'];outputs[k['output'].split('/ohm-foreign-join/',1)[1]]=(owner,args,idx)
            link=js(p+'link-inputs.json.gz')
            assert len(outputs)==len(link['links'])
            rosters=[];missing=set();missing_ron=[]
            for row in link['links']:
                own,args,idx=outputs[row['destination']]
                assert idx==row['epoch'] and row['mode']==roles[own]['mode']
                selected=[a for a in args if a.startswith('/')and Path(a).name.startswith('libron-')and a.endswith('.rlib')]
                assert selected==row['literal_ron']
                assert all(link['literal_files_after_command'][s][1]==rslib for s in selected)
                for f in row['absolute_file_operands']:
                    if link['literal_files_after_command'][f] is None:missing.add(f)
                if not selected:missing_ron.append(row['destination'])
                u=row['unit'];paths=[]
                if u:
                    for i,candidate in enumerate(graph['units']):
                        if [candidate['pkg_id'],candidate['target']['name'],candidate['target']['kind']]!=u[:3] or candidate['mode']!=('test' if u[-1] else 'build'):continue
                        queue=[i];closure=set()
                        while queue:
                            n=queue.pop()
                            if n not in closure:closure.add(n);queue.extend(x['index']for x in graph['units'][n]['dependencies'])
                        paths.append([i,sorted(n for n,_,_ in rons if n in closure)])
                assert paths==row['graph_path_to_ron']
                rosters.append([row['destination'],row['mode'],roles[own]['crate'],bool(selected),[n for _,ss in paths for n in ss]])
            inv=js(p+'inventory.json.gz')
            units=[json.loads(ln) for ln in z.read(p+'stdout.jsonl').splitlines()]
            assert units[-1]=={'reason':'build-finished','success':True}
            dirty=[m for m in units if m['reason']=='compiler-artifact'and not m['fresh']]
            assert len(dirty)==sum(not f for _,f in inv['units'])
            if phase=='untouched':
                filtered,proven=remove(raw)
                assert js(p+'single-record-transition.json').items() >= proven.items()
                out.setdefault('translated',{})[side]=proven
            assert b'ohm-foreign-span-bytes'in rustc
            states[phase]={'dep':HASH(raw),'rustc_dep':HASH(rustc),'rmeta':rsmeta,'rlib':rslib,'cargo_dirty':len(dirty),'physical_rustcs':sorted((m,n,v)for(m,n),v in cls.items()),'native':len(outputs),'native_roster':sorted(rosters),'missing_literal_ron':missing_ron,'nonretained_literal_files':sorted(missing),'all_executables':{k:v['elf']['sha256'] for k,v in inv['executables'].items()},'local_stale_messages':js(p+'dirty-fingerprint-reasons.json.gz')}
            out['phases'].append(label)
        if len(states)==3:
            before,ab,rest=(states[k]for k in ('untouched','ablated','restored'))
            assert before['dep']==rest['dep'];assert len(before['all_executables'])==102
            assert before['native_roster']==rest['native_roster']
            out.setdefault('comparisons',{})[side]={'before_diagnostic_after':[q['native']for q in(before,ab,rest)],'ron_rmeta':[q['rmeta']for q in(before,ab,rest)],'ron_rlib':[q['rlib']for q in(before,ab,rest)],'ablation_survived':ab['dep']==out['translated'][side]['changed'],'diagnostic_mismatch':[k for k,v in before['all_executables'].items() if v!=ab['all_executables'][k]],'restored_mismatch':[k for k,v in before['all_executables'].items()if v!=rest['all_executables'][k]]}
        out['states'][side]=states
    if 'signed-ron-replay/actual.json'in names:
        actual=js('signed-ron-replay/actual.json');hits=js('signed-ron-replay/native-hits.json.gz');stored=js('signed-ron-replay/inputs.json')
        assert hits['exit_codes']==[0]and stored['driver']=='53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52'
        parts={Path(k).suffix:k for k in names if k.startswith('signed-ron-replay/replay-')}
        assert sig(parts['.rlib'])==actual['rlib_replayed']and sig(parts['.rmeta'])==actual['rmeta_replayed']
        assert stored['original_argv'][stored['original_argv'].index('--crate-name')+1]=='ron'
        assert hits['events']==actual['direct_observations'] and len(hits['actual_returns'])==actual['joined_returns'] and sum(d['would_independently_observe'] for d in hits['debugs'])==actual['debug_independently_observes']
        out['signed_observer']={'actual':actual,'arguments':stored,'entries':hits['entry_counts'],'join_sources':hits['join_sources'],'actual_returns':hits['actual_returns'],'later_matched_bridge_reads':hits['matched_input_registers'],'debugs':hits['debugs']}
    out['diagnostic_logs']={n:z.read(n)[-6000:].decode(errors='replace') for n in ('signed-ron-replay/stdout','signed-ron-replay/stderr') if n in names}
    out['native_verdicts']={}
    for tag,ok in [('old-verdict',True),('old-on-new',False),('new-verdict',True),('restored-verdict',True)]:
        if tag+'/stdout'not in names:continue
        data=z.read(tag+'/stdout');lt=z.read(tag+'/test-list');assert len([n for n in lt.splitlines()if n.endswith(b': test')])==200
        assert (b'1 passed;'if ok else b'1 failed;')in data
        if not ok:assert b'script_tag'in data and b'source_text'in data
        out['native_verdicts'][tag]=[HASH(lt),HASH(data)]
    return out


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True,type=Path);ap.add_argument('--qa',required=True,type=Path);ap.add_argument('--gh',required=True);args=ap.parse_args()
    args.root.mkdir(exist_ok=True,parents=True);base=args.root/str(RUN);base.mkdir(exist_ok=True)
    get=lambda s:json.loads(sp.check_output([args.gh,'api',OHM+s],cwd=args.qa))
    run=get('actions/runs/'+str(RUN));j,=get(f'actions/runs/{RUN}/attempts/1/jobs')['jobs']
    assert run['head_sha']==HEAD and run['run_attempt']==1 and j['id']==125867338745 and run['head_branch']=='charlie/qa-workspace-test-29697-ron-cause-20261103'
    dump(base/'intake.json',{'run':run['id'],'conclusion':run['conclusion'],'head':HEAD,'job':j['id'],'runner':j['runner_name'],'runner_id':j['runner_id']})
    if run['status']!='completed':print(run['status'],[s['name']for s in j['steps']if s['status']=='in_progress']);return
    a,=get(f'actions/runs/{RUN}/artifacts')['artifacts'];assert a['workflow_run']['head_sha']==HEAD and a['name']==f'workspace-ron-29697-cause-{RUN}'and a['size_in_bytes']<512*2**20
    assert (a['id'],a['size_in_bytes'],a['digest'])==(13224910006,110549169,'sha256:3a03693ece5de011544ab69a6e3393a96856ffd9960f9662fb3ef51a507d7ec9')
    dump(base/'artifact.json',a);f=base/'original.zip'
    if not f.exists():
        ram=int(re.search(r'^MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
        if ram<8*2**30+2**26 or shutil.disk_usage(base).free<15*2**30+a['size_in_bytes']:print('Local space/RAM guard',ram,a['id'],a['digest']);return
        t=f.with_suffix('.part')
        with t.open('wb')as dest:sp.run([args.gh,'api',OHM+f'actions/artifacts/{a["id"]}/zip'],cwd=args.qa,stdout=dest,check=True)
        assert t.stat().st_size==a['size_in_bytes']and 'sha256:'+hfile(t)==a['digest'];t.rename(f)
    assert f.stat().st_size==a['size_in_bytes']and 'sha256:'+hfile(f)==a['digest']
    raw=sp.check_output(['git','-C',args.qa,'show',HEAD+':scripts/ruff-original-ty-instructions/ron_causality.py'])
    ns={};exec(compile(raw,'ron_causality.py','exec'),ns)
    with zipfile.ZipFile(f)as z:out=unpack(z,ns['without_observation'])
    out.update(head=HEAD,run=RUN,conclusion=run['conclusion'],archive=a['digest'],artifact=a['id'],worker=j['runner_name'])
    dump(base/'decoded.json',out)
    print('terminal',run['conclusion'],a['id'],out.get('comparisons'),out.get('signed_observer',{}).get('actual'))

if __name__=='__main__':main()
