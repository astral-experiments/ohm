"""Recalculate the native wall clocks, two sign tests and direct Cargo chronology."""
from fractions import Fraction
from itertools import permutations
from math import comb
from pathlib import Path
from statistics import median
import hashlib,io,json,re,shlex,sys,tarfile,zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import causal
sha=lambda b:hashlib.sha256(b).hexdigest()
def rustcs(stderr):
    commands=[];pending=[]
    for line in stderr.decode().splitlines():
        if not pending:
            m=re.match(r"^\s*Running "+chr(96)+r"(.*)",line)
            if m is None:continue
            pending=[m.group(1)]
        else:pending.append(line)
        if pending[-1].endswith(chr(96)):
            pending[-1]=pending[-1][:-1];args=shlex.split(' '.join(pending));pending=[]
            path='/tmp/uv-workflow-search/sdk/bin/rustc'
            if path in args and '--crate-name'in args:commands.append(args[args.index(path):])
    assert not pending
    return sorted(commands)


def run(original=None):
    manifest=json.loads((HERE/'manifest.json').read_bytes());archive=(HERE/'records.tar.xz').read_bytes()
    assert sha(archive)==manifest['packet_sha256']
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:xz')as t:
        entries=t.getmembers();assert all(i.isreg()for i in entries)
        assert len({i.name for i in entries})==len(entries)==len(manifest['members'])
        saved={i.name:t.extractfile(i).read() for i in entries}
    assert {k:sha(b)for k,b in saved.items()}==manifest['members']
    if original is not None:
        source=Path(original)
        with source.open('rb')as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest['service']['archive_sha256']
        assert source.stat().st_size==manifest['service']['bytes']
        with zipfile.ZipFile(source)as raw:
            for name,b in saved.items():
                if name not in {'registration.json','plan.json','sdk-lock.json','service.json'}:assert raw.read(name)==b
    f=lambda name:json.loads(saved[name]);plan=f('plan.json');reg=f('registration.json');boot=f('boot.json')
    assert sha(saved['plan.json'])==reg['plan']==boot['plan'] and boot['head']==reg['source']
    assert boot['calibration']==sha(saved['clock-pre/passed.json'])
    installed=f('intake.json');sdk=f('sdk-lock.json');service=f('service.json')
    assert sdk['roles']==plan['roles'] and sha(saved['sdk-lock.json'])==reg['sdk_lock']==installed['sdk_lock_sha256']
    assert service['artifact']['digest']=='sha256:'+manifest['service']['archive_sha256'] and service['run']['head_sha']==reg['source'] and service['run']['conclusion']==service['job']['conclusion']=='success'
    assert service['boot_receipt']['receipt_sha256']==sha(saved['boot.json']) and boot['run']==manifest['service']['run']==service['job']['run_id']
    for role in sdk['roles']:
        src=sdk['arms'][role];arm=installed['installed'][role]
        assert arm['server']==src['artifact'] and src['source']==plan['source'][role] and arm['producer_job_id']==src['service']['job']
        assert arm['runtime']['bin/cargo']==installed['signed_cargo_sha256']==plan['signed_cargo']
        assert [digest for filename,digest in arm['runtime'].items()if 'librustc_driver-'in filename]==[src['driver']]
    for label in ('clock-pre','clock-post'):
        r=f(label+'/passed.json');assert r['machine']==boot['machine']
        samples=[]
        for i in range(5):
            for ms in (0,3,13,31,53):
                p=f'{label}/probe-{i}-{ms}/';a,b=map(int,saved[p+'cargo.stdout'].split());o=f(p+'ordinary.json')
                assert o['start_ns']<=a<=b<=o['end_ns'] and o['exit']==0 and not o['deadline_fired']
                dt=o['end_ns']-o['start_ns'];extra=dt-(b-a)
                assert dt==o['ns'] and 0<=extra<=12_000_000 and b-a>=ms*1_000_000
                samples.append(extra)
        assert median(samples)<=4_000_000 and f(label+'/nonzero/ordinary.json')['exit']==17
        dead=f(label+'/deadline/ordinary.json');assert dead['exit']==-9 and dead['deadline_fired'] and 60_000_000<=dead['ns']<1_000_000_000
    roles=plan['roles'];orders=plan['orders'];assert len(roles)==3 and all(set(map(tuple,orders[n:n+6]))==set(permutations(roles))for n in (0,6))
    for r in roles:assert f(f'uv-client/hold-0-{r}/checkpoint.json')['sha256']!=f(f'uv-client/hold-1-{r}/checkpoint.json')['sha256']
    settled={}
    for h in (0,1):
        for role in roles:
            at=f'uv-client/hold-{h}-{role}/';assert not f(at+'typed-fresh-B/roster.json')['commands']
            val,=re.findall(rb'Finished .* target\(s\) in ([0-9]+\.[0-9]{2})s',saved[at+'settled-B/cargo.stderr'])
            settled[f'{h}/{role}']={'Cargo_display_s':float(val),'outer_wait_upper_s':f(at+'settled-B/ordinary.json')['ns']/1e9}
    rows=[];inner=[];previous=0;stored=f('uv-client/raw-trios.json')
    for i,order in enumerate(orders):
        times={};cargo={};record=stored[i];hold=plan['holds'][i]
        assert record['trio']==i and record['hold']==hold and record['order']==order and set(record['values'])==set(roles)
        for r in order:
            pre=f'uv-client/trio-{i}-{r}/wall/';x=f(pre+'ordinary.json');s=f(pre+'source.json')
            assert x['argv']==x['invoked']==['/tmp/uv-workflow-search/sdk/bin/cargo',*plan['command']] and x['mode']=='native-blocking'
            assert x['timer']=='CLOCK_MONOTONIC; waitpid blocking; ITIMER_REAL watchdog' and not x['deadline_fired'] and x['exit']==0
            assert 'RUSTC_WRAPPER'not in x['env'] and 'CARGO_BUILD_ANALYSIS_ENABLED'not in x['env']
            assert previous<x['start_ns']<x['end_ns'] and x['ns']==x['end_ns']-x['start_ns'] and x['boot']==boot['machine']['boot'] and x['cpus']==boot['machine']['cpus']
            assert s['head']=='a2a02424dcba3c3f37cf6b8de5484497dd48651e' and s['source']=='3d91d5195930020a6740f68341549629681eb8654048962cc618fe02e7130360'
            assert f(pre+'same-seed-equivalence.json')['passed']
            seed=f(f'uv-client/hold-{hold}-{r}/checkpoint.json')['sha256']
            assert record['values'][r]=={'ns':x['ns'],'checkpoint_sha256':seed,'receipt_sha256':sha(saved[pre+'ordinary.json'])}
            previous=x['end_ns'];times[r]=x['ns']
            matches=re.findall(rb'Finished .* target\(s\) in ([0-9]+)\.([0-9]{2})s',saved[pre+'cargo.stderr'])
            assert len(matches)==1
            sec,centis=matches[0];cargo[r]=(int(sec)*100+int(centis))*10_000_000
        rows.append(times);inner.append(cargo)
    def family(source):
        results=[]
        for control,candidate,threshold in plan['hypotheses']:
            ratios=[Fraction(row[control],row[candidate])for row in source];count=sum(v>threshold for v in ratios)
            upper=sum(comb(12,i)for i in range(count,13))/4096
            results.append({'control':control,'candidate':candidate,'threshold':threshold,'median':float(median(ratios)),
                'range':[float(min(ratios)),float(max(ratios))],'hold_medians':[float(median(ratios[:6])),float(median(ratios[6:]))],'above_2':sum(v>2 for v in ratios),'above_threshold':count,'one_sided_sign_p':upper})
        last=0
        for idx,k in enumerate(sorted(range(2),key=lambda k:results[k]['one_sided_sign_p'])):
            last=max(last,min(1,(2-idx)*results[k]['one_sided_sign_p']));results[k]['holm_p']=last
        return results
    direct=family(rows);original=f('uv-client/trio-score.json')
    for a,b in zip(direct,original['paired_metrics']):
        assert (a['median'],a['above_2'],a['one_sided_sign_p'],a['holm_p'])==(b['median_paired_ratio'],b['above_double'],b['one_sided_sign_p'],b['holm_p'])
    other=[Fraction(x[roles[0]],x[roles[1]])for x in rows]
    descriptive={'control':roles[0],'treatment':roles[1],'median':float(median(other)),'hold_medians':[float(median(other[:6])),float(median(other[6:]))],
                 'range':[float(min(other)),float(max(other))],'above_parity':sum(v>1 for v in other),'above_2':sum(v>2 for v in other),
                 'paired_ratios':[float(v)for v in other],'status':'descriptive; outside the two registered tests'}
    diagnostics={}
    for hold in (0,1):
        base=f'uv-client/hold-{hold}-{roles[2]}/';argv=f(base+'typed-B/roster.json')['commands'];assert sorted(argv)==rustcs(saved[base+'typed-B/cargo.stderr'])
        before=f(base+'ordinary-A/products.json');after=f(base+'warm-B/products.json');assert len(before['raw'])==len(after['raw'])==37 and len(before['public_sidecars'])==len(after['public_sidecars'])==415
        diagnostics[str(hold)]={}
        for phase in ('plain-B','typed-B'):
            r=base+'build-analysis/'+phase+'/';logs=saved[r+'cargo-analysis.jsonl'];d=f(r+'timeline.json')
            raw=[json.loads(l)for l in logs.splitlines()];units={i['index']:i['target']['name']for i in raw if i['reason']=='unit-registered'}
            def event(kind):return {units[e['index']]:e['elapsed']for e in raw if e['reason']==kind}
            starts=event('unit-started');finishes=event('unit-finished');assert starts.keys()==finishes.keys()==d['units'].keys() and len(starts)==8
            for n in starts:assert (starts[n],finishes[n])==(d['units'][n]['start'],d['units'][n]['finish'])
            diagnostics[str(hold)][phase]=causal.analyze(logs,d,argv,before,after)
            if phase=='typed-B':
                assert rustcs(saved[r+'cargo.stderr'])==sorted(argv)
                records=[json.loads(line)for line in saved[r+'cargo.stdout'].splitlines()];assert records[0]=={'reason':'build-started','run_id':d['run_id']} and records[-1]['success']
                assert sum(m['reason']=='compiler-artifact'for m in records)==486
            assert f(r+'same-seed-equivalence.json')['passed']
        settled_base=base+'build-analysis/settled-B/';assert not f(settled_base+'timeline.json')['units'] and not rustcs(saved[settled_base+'cargo.stderr'])
        lines=[json.loads(line)for line in saved[settled_base+'cargo.stdout'].splitlines()];assert lines[-1]['success'] and len([m for m in lines if m['reason']=='compiler-artifact'and m['fresh']])==486 and f(settled_base+'same-seed-equivalence.json')['passed']
        raw=[json.loads(l)for l in saved[settled_base+'cargo-analysis.jsonl'].splitlines()]
        assert not any(row['reason'] in ('unit-started','unit-rmeta-finished','unit-finished') for row in raw)
        assert lines[0]=={'reason':'build-started','run_id':raw[0]['run_id']}
        diagnostics[str(hold)]['settled-B']={'actual_compiler_argv':[],'registered_cargo_artifacts':486,'scheduled_units':0,'run_id':raw[0]['run_id']}
    return {'original':manifest['service'],'roles':roles,'physical_boot':boot['machine']['boot'],'all_trios_ns':rows,'descriptive_mature_vs_stock':descriptive,'unchanged_B':settled,'bare':direct,'cargo_display_only':family(inner),'diagnostic':diagnostics}
if __name__=='__main__':
    if sys.argv[1:]:
        assert len(sys.argv)==3 and sys.argv[1]=='--original'
    print(json.dumps(run(sys.argv[2] if len(sys.argv)==3 else None),sort_keys=True,indent=2))
