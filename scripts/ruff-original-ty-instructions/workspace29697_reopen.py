"""Receive an immutable ordinary workspace study, then reopen source, native ELF and process custody."""
from collections import Counter,defaultdict
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys
import tomllib
import zipfile
import tempfile

BOARD=Path(os.environ['RUNNER_TEMP'])/'workspace-receiver'
BOARD.mkdir(exist_ok=True)
QA=Path(__file__).resolve().parents[2]
SRC=Path(os.environ['GITHUB_WORKSPACE'])/'ruff'
assert os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD'] and os.environ['GITHUB_RUN_ATTEMPT']=='1'
GH='gh'; REPO='astral-experiments/ohm'
RUN='41617756983'; HEAD='50b22d77297be3cad8a8ba72620992c54a5683bc'; JOB=125855374228
ROOT=BOARD/RUN;ROOT.mkdir(exist_ok=True)
prefix='scripts/ruff-original-ty-instructions'
readgit=lambda repo,ref,path:sp.check_output(['git','-C',repo,'show',ref+':'+path])
spec=json.loads(readgit(QA,HEAD,prefix+'/workspace29697-registration.json'))
sdk=readgit(QA,HEAD,'scripts/ruff-foreign-span-observer/sdk.json')
api=lambda end:json.loads(sp.check_output([GH,'api','repos/'+REPO+'/'+end],cwd=QA))
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def hashfile(path):
    with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(path,j):path.write_text(json.dumps(j,indent=1,sort_keys=True)+'\n')


def acquisition():
    run=api('actions/runs/'+RUN);j,=api(f'actions/runs/{RUN}/attempts/1/jobs')['jobs']
    assert (run['head_sha'],run['run_attempt'],run['event'],run['head_branch'],j['id'])==(HEAD,1,'workflow_dispatch','charlie/qa-current-ruff-workspace-test-29697-20261103',JOB)
    if not (ROOT/'intake.json').exists():write(ROOT/'intake.json',{'run':RUN,'head':HEAD,'job':j['id'],'runner':j['runner_name'],'runner_id':j['runner_id'],'created':run['created_at']})
    if run['status']!='completed':print(run['status'],[(x['name'],x['status'])for x in j['steps']if x['status']=='in_progress']);return
    assert j['status']=='completed'
    write(ROOT/'run.json',run);write(ROOT/'job.json',j)
    assets=api('actions/runs/'+RUN+'/artifacts')['artifacts']
    if not assets:
        print('No original was uploaded',run['conclusion']);return
    a,=assets
    assert a['id']==13223081435 and a['size_in_bytes']==102158690 and a['digest']=='sha256:2ab6618f9f643f0c2ef9c192192c3b4955fe02f378432c8c28f01f8f8718f677'
    assert a['workflow_run']['head_sha']==HEAD and a['name']=='signed-workspace-test-29697-'+RUN and not a['expired'] and 0<a['size_in_bytes']<512*2**20
    write(ROOT/'artifact.json',a);p=ROOT/'original.zip'
    if not p.exists():
        mem=int(re.search(r'^MemAvailable:\s+(\d+)',Path('/proc/meminfo').read_text(),re.M)[1])*1024
        if mem<8*2**30+2**26 or shutil.disk_usage(ROOT).free<15*2**30+a['size_in_bytes']:print('Waiting on local reserve',mem);return
        f=ROOT/'original.partial'
        with f.open('wb')as dest:sp.run([GH,'api',f'repos/{REPO}/actions/artifacts/{a["id"]}/zip'],cwd=QA,stdout=dest,check=True)
        assert f.stat().st_size==a['size_in_bytes'] and 'sha256:'+hashfile(f)==a['digest'];f.rename(p)
    assert p.stat().st_size==a['size_in_bytes'] and 'sha256:'+hashfile(p)==a['digest']
    return p,run,j,a


def key(unit):return json.dumps(unit,separators=(',',':'))
def right(z,n):return json.loads(gzip.decompress(z.read(n))if n.endswith('.gz')else z.read(n))
def hashes(x):return {k:row['elf']['sha256']for k,row in x['executables'].items()}
def dirty(x):return sorted([key(u)for u,fresh in x['units']if not fresh])
def natural(path):
    return re.sub(r'-[0-9a-f]{16}$','',Path(path).name)
def owner(unit):
    return unit[0].split('#')[-1] if '@' in unit[0].split('#')[-1] else unit[0].split('#')[0].split('/')[-1]+'@'+unit[0].split('#')[-1]


def trace(z,tag):
    pre=tag+'/tasks/';orig=right(z,tag+'/owner-census.json.gz')
    records={r['epoch']:r for r in orig['roles']};children={};counts=defaultdict(lambda:[0,0,0]);eids=[];args={};outer=[]
    for raw in z.read(pre+'epochs.tsv').decode().splitlines():
        v=raw.split()
        if v[0]=='F':
            parent,caller,child,event=map(int,v[1:]);assert child not in children and event in (1,2,3);children[child]=parent
        elif v[0]=='C':
            idx,pid,tid,a,b,c=map(int,v[1:]);assert a>=0 and b>=c>=0
            for i,n in enumerate((a,b,c)):counts[idx][i]+=n
        elif v[0]=='I':
            _,idx,pid,tid,mono,why=v;idx,pid,tid=map(int,(idx,pid,tid));r=records[idx];eids.append(idx)
            assert [r[k]for k in ('pid','tid','trigger')]==[pid,tid,why]
            slab=z.read(pre+r['argv']);assert sha(slab)==r['argv_sha256']
            parts=slab.split(b'\0');assert parts[-1]==b'' and int(parts[0])==pid and list(map(int,parts[1:3]))==[r['dev'],r['ino']]and os.fsdecode(parts[3])==r['path']
            argv=list(map(os.fsdecode,parts[4:-1]));args[idx]=argv
            name=Path(r['path']).name
            if r['path'].endswith('/sdk/bin/rustc'):
                crate=argv[argv.index('--crate-name')+1] if '--crate-name'in argv else None
                only=any(a in ('-Zlink-only','-Zlink-only=yes')or i and argv[i-1]=='-Z' and a in ('link-only','link-only=yes')for i,a in enumerate(argv));target='link-only'if only else 'test'if '--test'in argv else 'config'if not crate else 'metadata'if any(a.startswith('--emit=')and 'link'not in a[7:].split(',')for a in argv)else 'full'
                assert r['mode']==target and (r['crate']==crate or only and r['rlink'])
            elif r['path'].endswith('/wild-ld/ld.bfd'):assert r['mode']=='Wild'
        elif v[0]=='W':outer.append(list(map(int,v[1:])))
    assert sorted(eids)==sorted(records) and len(children)==orig['logical_forks'] and outer==[orig['outer']]
    assert all(counts[idx]==r['counter']for idx,r in records.items())
    if any(r['trigger']=='exec'and r['mode'] in ('full','test','link-only')for r in records.values()):assert children
    actual=[];inherited=[];unpriced=[];images=defaultdict(int);reds=[];links=[];deps={}
    for idx,r in records.items():
        mode=r['mode'];cost,enabled,running=r['counter'];images[(r['trigger'],mode,r['crate']or Path(r['path']).name)]+=cost
        if mode not in ('full','test','link-only','metadata','Wild','config')and not mode.startswith('native-linker/'):continue
        o=[mode,r['crate'],r['pid'],idx,cost,enabled==running,r.get('source')]
        if r['trigger']=='first':inherited.append(o);continue
        actual.append(o)
        if enabled!=running:unpriced.append(o)
        if mode in ('full','test','link-only','metadata'):
            entries=[a for i,a in enumerate(args[idx])if i and args[idx][i-1]=='--extern'];deps[idx]=[e.split('=',1)if '='in e else [e,None]for e in entries]
            reds.append(o)
        elif mode=='Wild' or mode.startswith('native-linker/'):
            pid=r['pid'];seen=set();up=None
            while pid in children:
                assert pid not in seen;seen.add(pid);pid=children[pid]
                possible=[q for q in records.values()if q['pid']==pid and q['trigger']=='exec'and q['epoch']<=idx and q['mode']in('full','test','link-only','metadata')]
                if possible:up=max(possible,key=lambda q:q['epoch']);break
            assert r['owning_rustc_epoch']==(up['epoch']if up else None)
            links.append({'epoch':idx,'owner':up['crate']if up else None,'owner_mode':up['mode']if up else None,'output':r['output'],'instructions':cost,'unscaled':enabled==running})
    return dict(real_execs=actual,inherited=inherited,compilers=sorted(reds,key=lambda r:-r[4]),native_linkers=links,unequal_counters=unpriced,outer=orig['outer'],by_image=[[*k,v]for k,v in sorted(images.items(),key=lambda x:-x[1])],externs=deps)


def main():
    got=acquisition()
    if not got:return 75
    pack,r,j,a=got;result={'run':int(RUN),'head':HEAD,'job':JOB,'archive':{k:a[k]for k in('id','name','digest','size_in_bytes')},'conclusion':r['conclusion']}
    with zipfile.ZipFile(pack)as z:
        ns=set(z.namelist());assert len(ns)==len(z.namelist()) and all(not Path(n).is_absolute()and '..'not in Path(n).parts for n in ns)
        reg=right(z,'registration.json');assert reg['head']==HEAD and reg['run']==RUN and reg['runner']==j['runner_name'] and reg['study']==spec and sha(sdk)==spec['sdk_manifest']
        result.update(boot=reg['boot'],runner=j['runner_name'])
        original_sdk=right(z,'sdk-proof.json')
        assert original_sdk['archive']==json.loads(sdk)['asset']['digest'][7:] and original_sdk['files']==79 and 'd57fd1515986dccecdcece8da85e651bfb4b81f9' in original_sdk['rustc'] and '7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed' in original_sdk['cargo']
        result['signed_sdk']=original_sdk
        for rev,src in spec['source'].items():assert all(sha(readgit(SRC,rev,p))==h for p,h in src.items())
        if 'locked-registry.json.gz'in ns:
            locked=tomllib.loads(readgit(SRC,spec['new'],'Cargo.lock').decode());cache={p['name']+'-'+p['version']+'.crate':p['checksum']for p in locked['package']if p.get('source','').startswith('registry+')}
            assert right(z,'locked-registry.json.gz')==cache and len(cache)==502
            g=right(z,'cargo-metadata.json.gz')
            assert sorted(g['workspace_default_members'])==sorted(g['workspace_members']) and sorted(p['name']for p in g['packages']if p['id']in g['workspace_default_members'])==spec['default_members']
            ug=right(z,'unit-graph.json.gz');result['graph']={'members':len(g['workspace_default_members']),'units':len(ug['units']),'roots':len(ug['roots']),'root_modes':dict(Counter(ug['units'][i]['mode']for i in ug['roots']))}
        inv={};timers={};journals={};verdict={}
        for name in sorted(ns):
            if name.endswith('/inventory.json.gz'):
                tag=name.split('/')[0];inv[tag]=right(z,name)
                out=inv[tag];report={};units=[]
                for line in z.read(tag+'/stdout.jsonl').splitlines():
                    x=json.loads(line)
                    if x['reason']!='compiler-artifact':continue
                    u=[x['package_id'],x['target']['name'],x['target']['kind'],sorted(x['features']),x['profile']['test']]
                    units.append([u,x['fresh']])
                    if x['executable']:report[x['executable'].split('/ohm-foreign-join/',1)[1]]=u
                assert sorted(units,key=repr)==out['units'] and report=={p:v['unit']for p,v in out['executables'].items()}
            elif name.endswith('/hardware.json'):
                q=right(z,name);assert q['status']==0 and q['running']==q['enabled']>0 and q['instructions']>0;timers[name.split('/')[0]]=q
            elif name.endswith('/owner-census.json.gz'):journals[name.split('/')[0]]=trace(z,name.split('/')[0])
            elif name.endswith('/test-list'):
                pre=name.split('/')[0];listing=z.read(name);n=[s for s in listing.splitlines()if s.endswith(b': test')];assert len(n)==len(set(n)) and len([n for n in n if n.endswith(b'::debug_command: test')])==1
                out=z.read(pre+'/stdout')
                if pre=='old-on-new':assert b'1 failed;'in out and b'source_text'in out and b'script_tag'in out
                else:assert b'1 passed;'in out
                verdict[pre]=[sha(listing),len(n),sha(out)]
        native={}
        for n in ns:
            if not n.endswith('.elf.zst'):continue
            with tempfile.TemporaryFile()as compressed:
                with z.open(n)as src:shutil.copyfileobj(src,compressed)
                compressed.seek(0)
                proc=sp.Popen(['zstd','-dqc'],stdin=compressed,stdout=sp.PIPE)
                stream=proc.stdout
                first=stream.read(64);assert first[:4]==b'\x7fELF';h=hashlib.sha256(first);nr=len(first)
                while b:=stream.read(2**20):h.update(b);nr+=len(b)
                assert proc.wait()==0
            assert n==h.hexdigest()+'.elf.zst';native[h.hexdigest()]=nr
        result.update(timers=timers,traces=journals,verdicts=verdict,full_e2e=native,completed_stages=sorted(inv))
        if not 'decision.json'in ns:
            result['last_artifact_members']=[n for n in sorted(ns)if n.endswith(('resources.json','stderr'))];write(ROOT/'refused.json',result);print('Refused',result['completed_stages'],result.get('graph'));return 2
        decision=right(z,'decision.json');old,edit,cl=(inv[t]for t in('ordinary-old','ordinary-edit','independent-NEW'));k=cl['binary']
        assert len(set(v[0]for v in verdict.values()))==1 and all(hashdict['sha256'] in native and native[hashdict['sha256']]==hashdict['bytes']for t,v in inv.items()for hashdict in [v['executables'][v['binary']]['elf']])
        assert b'E0308' in z.read('invalid/stdout.jsonl') and right(z,'invalid/resources.json')['exit']==101
        diff=lambda x,y:sorted(k for k,h in hashes(x).items()if h!=hashes(y)[k])
        for key0,a0,b0 in [('old_to_rebuilt_new','ordinary-old','ordinary-edit'),('edited_to_clean','ordinary-edit','independent-NEW'),('edited_to_first','ordinary-edit','first-unchanged'),('first_to_repeat','first-unchanged','repeat-unchanged'),('first_to_observed','first-unchanged','unchanged-observed'),('repaired_to_clean','repair','independent-NEW'),('reverse_to_original','reverse-observed','ordinary-old'),('again_to_clean','edit-observed','independent-NEW')]:
            assert decision[key0]==diff(inv[a0],inv[b0])
        result['decision']=decision;result['native_inventory']={p:v['unit'] for p,v in cl['executables'].items()};result['published_by_type']={repr(k):v for k,v in Counter((tuple(row['unit'][2]),row['unit'][-1])for row in cl['executables'].values()).items()}
        deltas={}
        for p in decision['edited_to_clean']:
            a,b=edit['executables'][p]['elf'],cl['executables'][p]['elf']
            di=[i for i in range(min(len(a['sections']),len(b['sections'])))if a['sections'][i]!=b['sections'][i]]
            deltas[p]={'names':[a['sections'][i][0]for i in di],'old_length':a['bytes'],'new_length':b['bytes'],'old_sha256':a['sha256'],'clean_sha256':b['sha256']}
        result['clean_section_diffs']=deltas
        files=lambda cat,cat2:{p:[v,cat2.get(p)]for p,v in cat.items()if cat2.get(p)!=v}
        prod=old['workspace_artifacts_and_ron'];new=edit['workspace_artifacts_and_ron']
        result['changed_workspace_libraries']=files(prod,new)
        result['dirty_units']={n:dirty(v)for n,v in inv.items() if n not in ('ordinary-old','independent-NEW')}
        assert r['conclusion']=='success' and decision['e2e_raw_equal_clean'] and decision['e2e_old_differs']
        write(ROOT/'reopened.json',result)
    print('accepted discovery',hashfile(ROOT/'reopened.json'),'graph',result.get('graph'),'executables',decision['executables'],'changed',len(decision['old_to_rebuilt_new']),'clean mismatches',len(decision['edited_to_clean']))
    for k,v in timers.items():print('ordinary',k,v['instructions'])
    for k,v in journals.items():print('traced',k,'typed',len(v['compilers']),'link-only',sum(x[0]=='link-only'for x in v['compilers']),'links',len(v['native_linkers']),'largest',v['compilers'][:4])
    return 0

if __name__=='__main__':raise SystemExit(main())
