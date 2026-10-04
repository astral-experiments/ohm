#!/usr/bin/env python3
"""Summarize paired build/runtime records without dropping unfavorable samples."""
import argparse,collections,hashlib,json,math,pathlib,random,re,statistics

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def metrics(values):
    return {'n':len(values),'geomean':statistics.geometric_mean(values),'median':statistics.median(values),'min':min(values),'max':max(values)}

def rejection(sample):
    reasons=[]
    if sample.get('returncode') != 0: reasons.append('incomplete or failed')
    if sample.get('lock_wait_detected'): reasons.append('Cargo lock wait')
    if sample.get('monitor',{}).get('foreign_compiler_observations'): reasons.append('foreign compiler observed')
    return reasons

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
parser.add_argument('--raw-root',type=pathlib.Path,help='Verified extracted host archives; defaults to sibling raw directory')
args=parser.parse_args()
raw_root=args.raw_root or args.root.parent/'raw'

def gnu_time(path):
    if not path.exists():return None
    text=path.read_text()
    fields={}
    for key,label,kind in [('user_seconds','User time (seconds)',float),('system_seconds','System time (seconds)',float),('maximum_rss_kib','Maximum resident set size (kbytes)',int),('major_page_faults','Major (requiring I/O) page faults',int),('minor_page_faults','Minor (reclaiming a frame) page faults',int)]:
        matches=re.findall(r'(?m)^[ \t]*'+re.escape(label)+r': ([0-9.]+)$',text)
        if len(matches)!=1:raise ValueError(f'{path}: expected exactly one {label}, got {matches}')
        fields[key]=kind(matches[0])
    wall=re.findall(r'(?m)^[ \t]*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([0-9:.]+)$',text)
    if len(wall)!=1:raise ValueError(f'{path}: missing or ambiguous GNU wall time')
    fields['wall_seconds']=sum(float(part)*60**index for index,part in enumerate(reversed(wall[0].split(':'))))
    fields['source_log_sha256']=sha(path)
    try:
        fields['source_log']=str(path.relative_to(raw_root))
    except ValueError:
        fields['source_log']='results/'+str(path.relative_to(args.root))
    return fields
result={'candidate_cargo_commit':'cbec67aa6ad824fdb8550d033bfd0aee0787b1b5','base_cargo_commit':'018a2b93409433dc5bc05c5fce838ae69e9bc396','builds':[],'rejected_preflights':[],'pairs':[],'aggregates':[], 'runtime':[], 'runtime_pairs':[], 'runtime_aggregates':[], 'provenance':{}, 'limitations':['Cold means fresh isolated Cargo target and build directories; registry and OS file caches are warm.', 'Default concurrency, existing security/system services retained; outside-process CPU and steal time are recorded.', 'GNU time maximum RSS is its process/child high-water figure, not peak aggregate memory across concurrent compiler processes.', 'Initial global-RUSTFLAGS screen and actual graph-scoped Cargo policy are separate cohorts.', 'Entry edit inserts a black_box string at main. Library edit changes a generic deserializer error message on top of that entry edit.', 'Runtime uses unedited cold binaries; Ruff checks/formats pinned CPython with no cache; uv resolves two pinned inputs offline against a warmed public PyPI cache.']}
for path in sorted(args.root.glob('**/result.json')):
    d=json.loads(path.read_text())
    host,cohort=path.relative_to(args.root).parts[:2]
    name,lto,variant,index=d['id'].split('-')
    info_id=f'{host}/{cohort}/{d["id"]}'
    result['provenance'][info_id]={key:d.get(key) for key in ['source_sha','source_status','command','environment','rustc','cargo','rustc_path','rustc_sha256','cargo_path','cargo_sha256','runner_sha256','uname','host_limits','edit','library_edit','resume_history']}
    result['provenance'][info_id]['raw_result_sha256']=sha(path)
    result['provenance'][info_id]['resume_checkpoints']=[{'file':checkpoint.name,'sha256':sha(checkpoint)} for checkpoint in sorted(path.parent.glob('result-before-resume-*.json'))]
    for preflight in d.get('rejected_preflights',[]):
        result['rejected_preflights'].append({'provenance':info_id, 'kind':preflight['kind'], 'idle_fraction_before':preflight.get('idle_fraction_before'), 'iowait_fraction_before':preflight.get('iowait_fraction_before'), 'time':preflight.get('before',{}).get('time'), 'runner_sha256':preflight.get('runner_sha256',d['runner_sha256'])})
    for sample in d['samples']:
        row={key:sample.get(key) for key in ['kind','elapsed','returncode','binary_size','binary_sha256','idle_fraction_before','iowait_fraction_before','lock_wait_detected','monitor']}
        row.update(host=host,cohort=cohort,name=name,lto=lto,variant=variant,pair=int(index),provenance=info_id,rejection_reasons=rejection(sample))
        row['runner_sha256']=sample.get('runner_sha256',d['runner_sha256'])
        raw_relative=pathlib.Path('policy')/d['id'] if cohort=='policy' else pathlib.Path(d['id'])
        raw_log=raw_root/host/'results'/raw_relative/(sample['kind']+'.log')
        if not raw_log.exists():raw_log=path.parent/(sample['kind']+'.log')
        row['gnu_time']=gnu_time(raw_log) if sample.get('returncode')==0 else None
        row['started_utc_epoch']=sample.get('before',{}).get('time')
        row['finished_utc_epoch']=sample.get('after',{}).get('time')
        result['builds'].append(row)
groups=collections.defaultdict(dict)
for row in result['builds']:
    groups[tuple(row[k] for k in ['host','cohort','name','lto','pair','kind'])][row['variant']]=row
for key,rows in sorted(groups.items()):
    candidate=rows.get('policy') or rows.get('yes')
    baseline=rows.get('default')
    if not baseline or not candidate: continue
    reasons=baseline['rejection_reasons']+candidate['rejection_reasons']
    result['pairs'].append({**dict(zip(['host','cohort','name','lto','pair','kind'],key)),'baseline_seconds':baseline['elapsed'],'candidate_seconds':candidate['elapsed'],'candidate_over_baseline':candidate['elapsed']/baseline['elapsed'] if not reasons else None,'order':'AB' if baseline['started_utc_epoch']<candidate['started_utc_epoch'] else 'BA','rejection_reasons':reasons})
groups=collections.defaultdict(list)
for row in result['pairs']:
    if not row['rejection_reasons']: groups[tuple(row[k] for k in ['host','cohort','name','lto','kind'])].append(row['candidate_over_baseline'])
for key,values in sorted(groups.items()):
    result['aggregates'].append({**dict(zip(['host','cohort','name','lto','kind'],key)),**metrics(values)})
runtime_audits={}
for audit_path in sorted(args.root.glob('*/runtime-audit.json')):
    for audit in json.loads(audit_path.read_text()):
        key=(audit_path.parent.name,pathlib.Path(audit['source']).parent.name)
        runtime_audits[key]=audit
result['runtime_correctness_audits']=[{'host':host,'cohort':cohort,**audit} for (host,cohort),audit in sorted(runtime_audits.items())]
for path in sorted(args.root.glob('**/results.json')):
    d=json.loads(path.read_text())
    host,cohort=path.relative_to(args.root).parts[:2]
    info_id=f'{host}/{cohort}/{path.parent.name}'
    result['provenance'][info_id]={key:d.get(key) for key in ['source_sha','binaries','runner_sha256','host_limits']}
    result['provenance'][info_id]['raw_result_sha256']=sha(path)
    result['provenance'][info_id]['commands']=[list(command) for command in sorted({tuple(sample['command']) for sample in d['samples']})]
    audit=runtime_audits.get((host,path.parent.name),{})
    for sample in d['samples']:
        row={key:sample.get(key) for key in ['label','workload','kind','pair','elapsed','returncode','output_sha256']}
        row.update(host=host,cohort=cohort,name=d['name'],lto='thin' if '-thin-' in path.parent.name else 'fat',provenance=info_id,correctness_audit_passed=audit.get('status')=='passed')
        row['foreign_compiler_observations']=[item for item in sample['monitor'] if any(p['name'] in {'rustc','cargo','cc','cc1','clang','ld','ld.lld','mold','ninja'} for p in item['outside'])]
        row['outside_cpu_seconds']=sum(item['seconds']*item['outside_cpu_cores'] for item in sample['monitor'])
        result['runtime'].append(row)
groups=collections.defaultdict(dict)
for row in result['runtime']:
    if row['kind']=='measure': groups[tuple(row[k] for k in ['host','cohort','name','lto','workload','pair'])][row['label']]=row
for key,rows in sorted(groups.items()):
    if 'baseline' not in rows or 'candidate' not in rows: continue
    a,b=rows['baseline'],rows['candidate']
    result['runtime_pairs'].append({**dict(zip(['host','cohort','name','lto','workload','pair'],key)),'baseline_seconds':a['elapsed'],'candidate_seconds':b['elapsed'],'candidate_over_baseline':b['elapsed']/a['elapsed'],'outputs_match':a['output_sha256']==b['output_sha256'],'exit_codes_match':a['returncode']==b['returncode'],'correctness_audit_passed':a['correctness_audit_passed'] and b['correctness_audit_passed'],'foreign_compiler_observed':bool(a['foreign_compiler_observations'] or b['foreign_compiler_observations'])})
groups=collections.defaultdict(list)
for row in result['runtime_pairs']:
    if not row['foreign_compiler_observed'] and row['outputs_match'] and row['exit_codes_match'] and row['correctness_audit_passed']: groups[tuple(row[k] for k in ['host','cohort','name','lto','workload'])].append(row['candidate_over_baseline'])
for key,values in sorted(groups.items()):
    rng=random.Random(19375)
    boot=sorted(statistics.geometric_mean(rng.choices(values,k=len(values))) for _ in range(10000))
    result['runtime_aggregates'].append({**dict(zip(['host','cohort','name','lto','workload'],key)),**metrics(values),'bootstrap_95_percent_interval':[boot[250],boot[9749]]})
result['skipped']=[json.loads(path.read_text()) for path in args.root.glob('*/uv-global-share-yes-skipped.json')]
result['cache_layout']={path.parent.name:json.loads(path.read_text()) for path in args.root.glob('*/cache-layout.json')}
result['infrastructure_events']={path.parent.name:json.loads(path.read_text()) for path in args.root.glob('*/setup-events.json')}
result['archives']={path.parent.name:json.loads(path.read_text()) for path in args.root.glob('*/archive.json')}
result['runtime_transitions']={path.parent.name:json.loads(path.read_text()) for path in args.root.glob('*/runtime-transition.json')}
result['build_runner_transitions']={path.parent.name:json.loads(path.read_text()) for path in args.root.glob('*/runner-transition.json')}
result['compiler_scope_audits']=[]
for audit_path in args.root.glob('*/scope-audit.json'):
    for audit in json.loads(audit_path.read_text()):
        result['compiler_scope_audits'].append({'host':audit_path.parent.name,'log':audit['log'],'counts':audit['counts'],'violations':audit['violations'],'original_audit_sha256':sha(audit_path)})

args.output.write_text(json.dumps(result,indent=2)+'\n')
for row in result['aggregates']+result['runtime_aggregates']: print(json.dumps(row))
