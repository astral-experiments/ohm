"""Replay all 32 original blocking clocks and Linux resource records with Python's standard library."""
from collections import Counter
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from statistics import median
import argparse, csv, io, json, sys, tarfile, zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent));import kernel_records, linux_resources, table_resources

HERE=Path(__file__).resolve().parent
PREREG='3936b8c5031523f30435b1c16a21cf86249b94710ddaa6aaa36916d61892c675'
EARLIER='b5ad96d39f911a2af3934ca9ac596d3af0142c6729a76e1f9b0cde3c99bcd5bd'
HEAD='9d9e6e5e1531861efe9abc6ed867dd63b8ab0600';RUN=41484215521;JOB=125410155788
PT='callables_ctfe318_incoherent_domain_proc_derive';CT=PT+'_trait_origin';H=lambda b:sha256(b).hexdigest()
QUARANTINE={'RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','CARGO_LOG','RUSTC_LOG','LD_PRELOAD'}

def scoring(pairs):
    assert len(pairs)==16 and all(len(row)==2 and all(type(v)is int and v>0 for v in row)for row in pairs)
    rs=[Fraction(c,p)for p,c in pairs];blocks=[median(rs[start:start+4])for start in (0,4,8,12)];under=sum(5*c<6*p for p,c in pairs)
    def tails(vals):
        return {'over_1_5':[i for i,q in enumerate(vals)if q>Fraction(3,2)],'at_least_1_5':[i for i,q in enumerate(vals)if q>=Fraction(3,2)],'over_2':[i for i,q in enumerate(vals)if q>2],'at_least_2':[i for i,q in enumerate(vals)if q>=2]}
    ct=tails(rs);return {'raw_parent_candidate_ns':pairs,'candidate_over_parent':list(map(str,rs)),'paired_median_C_over_P':str(median(rs)),'block_medians_C_over_P':list(map(str,blocks)),'strictly_below_1_20':under,'candidate_slower':ct,'parent_slower':tails([1/q for q in rs]),'pass':all(x<Fraction(21,20)for x in blocks)and under>=15 and not ct['at_least_2']}

def check_clock(d,argv,boot,started_after=0):
    assert d['timer']=='CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog'and d['mode']=='native'and d['exit']==0 and d['deadline_fired'] is False
    assert d['argv']==d['invoked']==argv and not QUARANTINE.intersection(d['env'])and d['boot']==boot and d['pid']>0 and d['ns']==d['end_ns']-d['start_ns']>0 and d['start_ns']>started_after
    return d['ns']

def old_records(get,raw,plan):
    reg=plan['old_ordinary_clocks'];assert reg['source_sha256']==EARLIER;observed={};result=[]
    for r in reg['rows']:
        i=r['pair_zero_based'];role=PT if r['arm']=='parent'else CT;path=f'prior/uv-client/pair-{i}-{role}/wall';d=get(path+'/ordinary.json');b=raw(path+'/cargo.stderr');lines=[v.strip()for v in b.decode().splitlines()if 'Finished 'in v];assert check_clock(d,plan['command'],get('prior/fresh-boot.json')['boot'])==r['blocking_ns'] and H(b)==r['stderr_sha256']and lines==[r['cargo_report']]
        assert (i,role)not in observed;observed[i,role]=d['ns'];result.append({'pair':i+1,'role':r['arm'],'ns':d['ns'],'cargo_finished':lines[0]})
    assert len(observed)==16 and [i+1 for i in range(8)if observed[i,CT]>=2*observed[i,PT]]==[3,6];return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--original',type=Path,help='Additionally hash and byte-compare every retained original member for the new job');parser.add_argument('--prior-original',type=Path,help='Same check against the preceding eight-pair job');a=parser.parse_args();index=json.loads((HERE/'index.json').read_bytes());m=index['service'];assert m['current']['run']==RUN and m['current']['job']==JOB and m['current']['head']==HEAD and m['prior']['sha256']==EARLIER
    sources={}
    for line in (HERE/'SHA256SUMS').read_text().splitlines():
        h,name=line.split('  ');assert '/'not in name and h==H((HERE/name).read_bytes())and name not in sources;sources[name]=h
    assert {'records.tar.gz','index.json','replay.py','linux_resources.py','kernel_records.py','table_resources.py','all-32-wall-resources.csv'}<=set(sources)
    with tarfile.open(HERE/'records.tar.gz',mode='r:gz')as t:
        ids=set();blobs={}
        for x in t:
            assert x.isfile()and len(x.name)==64 and x.name not in ids;ids.add(x.name);v=t.extractfile(x).read();assert len(v)==x.size and H(v)==x.name;blobs[x.name]=v
    cells=index['members'];assert set(blobs)=={r['sha256']for r in cells.values()};assert all(len(blobs[r['sha256']])==r['bytes']for r in cells.values());raw=lambda p:blobs[cells[p]['sha256']];get=lambda p:json.loads(raw(p));plan=get('protocol/registration.json');study=get('protocol/study.json');assert H(raw('protocol/registration.json'))==PREREG;assert H(raw('protocol/decision.json'))==plan['prior_decision_file_sha256'];boot=get('current/wall-tail-boot.json');assert boot['run']==str(RUN)and boot['head']==HEAD and boot['registration']==PREREG and len(boot['prior_boots'])==24 and boot['boot']not in boot['prior_boots'];assert get('service/boot-origin.json')['entry_sha256']==H(raw('current/wall-tail-boot.json'));r=get('service/run.json');jobs=get('service/jobs.json')['jobs'];assert r['id']==RUN and r['head_sha']==HEAD and r['run_attempt']==1 and r['conclusion']=='success'and len(jobs)==1 and jobs[0]['id']==JOB and jobs[0]['conclusion']=='success';art,=[x for x in get('service/artifacts.json')['artifacts']if x['id']==m['current']['artifact_id']];assert art['size_in_bytes']==m['current']['bytes']and art['digest']=='sha256:'+m['current']['sha256'];assert get('current/blocking-clock/passed.json')['machine']==get('current/blocking-clock-post/passed.json')['machine'];ready=get('current/calibration.json')['ready'];assert ready['boot']==boot['boot'];assert get('current/intake/domain-native/accepted.json')['modes']==10
    for name,source in [('current',a.original),('prior',a.prior_original)]:
        if source is None:continue
        h=sha256();n=0
        with source.open('rb')as f:
            for b in iter(lambda:f.read(1<<20),b''):h.update(b);n+=len(b)
        assert h.hexdigest()==m[name]['sha256'] and n==m[name]['bytes'];prefix=name+'/'
        with zipfile.ZipFile(source)as z:
            for k in cells:
                if k.startswith(prefix):assert raw(k)==z.read(k.removeprefix(prefix))
    prior=old_records(get,raw,plan);reported=get('current/uv-client/wall-tail-score.json');rr=get('current/uv-client/raw-pairs.json');pairs=[];obs=[];seeds=set();last=0;known_compilers=set()
    for i,row in enumerate(rr):
        order=plan['order'][i];assert row['pair']==i and i//4==row['block']==plan['blocks'][i] and row['order']==order and set(order)=={PT,CT};values={}
        for role in order:
            root=f'current/uv-client/opening-{i}-{role}';p=root+'/warm-B';q=root+'/edited-kernel-B';d=get(p+'/ordinary.json');state=get(p+'/source.json');cp=get(root+'/checkpoint.json');assert cp['role']==role and cp['hold']==i and cp['count']>0 and len(cp['sha256'])==64 and cp['sha256'] not in seeds;seeds.add(cp['sha256']);t=check_clock(d,plan['command'],boot['boot'],last);last=d['end_ns'];assert d['cpus']==ready['affinity'] and row['values'][role]['wall_ns']==t and row['values'][role]['checkpoint']==cp['sha256']
            assert state['head']==study['A']and state['index']==study['A_tree']and state['working_tree']==study['B_tree']and state['source']==study['B_file']and state['lock']==study['lock_sha256']and state['patch_sha256']==study['edit_sha256'];resource=get(p+'/resources.json');b,c=resource['before'],resource['after'];assert b['end_ns']<=d['start_ns']<d['end_ns']<=c['start_ns'] and b['affinity']==c['affinity']==d['cpus'];assert linux_resources.delta(b,c)==resource['delta']and row['values'][role]['resources_sha256']==H(raw(p+'/resources.json'));child=resource['delta']['children'];assert sum(child[k]for k in ('utime_us','stime_us'))>0 and min(child[k]for k in ('minflt','majflt','nvcsw','nivcsw'))>=0
            forms=get(root+'/typed-B/roster.json')['commands'];stored=H(json.dumps(sorted(forms),sort_keys=True,separators=(',',':')).encode());assert len(forms)==8 and stored==study['prior_actual_argv_sha256'];ev=get(q+'/kernel-events.json');en=get(q+'/enrollment.json');cert=kernel_records.kernel_receipt(ev,en,forms,plan['command'],kernel_records.decode);assert cert==get(q+'/actual-rustcs.json')and en['cargo_sha256']=='3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871'and en['compiler_sha256']==get('current/intake.json')['installed'][role]['runtime']['bin/rustc'];assert H(raw(q+'/kernel-events.json'))==row['values'][role]['kernel_sha256'] and len(cert['rustcs'])==len(set(cert['rustcs'].values()))==8;assert not known_compilers or known_compilers==set(cert['rustcs']);known_compilers=set(cert['rustcs']);es=raw(p+'/cargo.stderr');fin=[v.strip()for v in es.decode().splitlines()if 'Finished 'in v];assert len(fin)==1;values[role]=t;obs.append({'pair':i+1,'block':i//4+1,'role':'parent'if role==PT else'candidate','start_ns':d['start_ns'],'end_ns':d['end_ns'],'pid':d['pid'],'ns':t,'cargo_finished':fin[0],'child':child,'resource_record':cells[p+'/resources.json']['sha256']})
        pairs.append([values[PT],values[CT]])
    assert len(rr)==16 and len(seeds)==len(obs)==32 and len(known_compilers)==8;result=scoring(pairs);assert all(result[k]==reported[k]for k in result);csv_rows=list(csv.DictReader(io.StringIO((HERE/'all-32-wall-resources.csv').read_text())));assert len(csv_rows)==len(obs)
    for item,v in zip(csv_rows,obs):
        rv=json.loads(blobs[v['resource_record']]);details=table_resources.short(rv);assert all(item[k]==(''if x is None else str(x))for k,x in details.items());assert int(item['clock_start_ns'])==v['start_ns'] and int(item['clock_end_ns'])==v['end_ns'];assert int(item['pair'])==v['pair']and item['arm']==v['role']and int(item['wall_ns'])==v['ns']and int(item['actual_cargo_pid'])==v['pid']and item['cargo_finished']==v['cargo_finished']and int(item['total_cpu_us'])==v['child']['utime_us']+v['child']['stime_us']
    assert index['decision']==result and index['visit_table']==obs and len(prior)==16;print(json.dumps({'study':result,'absolute_clocks':obs,'prior_all':prior,'original':m,'separate_kernel_observations':32*8,'boot':boot['boot'],'resource_csv':'all-32-wall-resources.csv','qualification':index['native_admission']},indent=2,sort_keys=True))
if __name__=='__main__':main()
