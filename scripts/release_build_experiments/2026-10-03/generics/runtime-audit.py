#!/usr/bin/env python3
"""Audit complete runtime cohorts without changing their recorded raw streams."""
import argparse,collections,hashlib,json,pathlib,re
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('root',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
def digest(data):return hashlib.sha256(data).hexdigest()
reports=[]
for path in sorted(args.root.glob('**/results.json')):
    d=json.loads(path.read_text())
    if not {'name','samples','workloads'}.issubset(d):continue
    report={'source':str(path),'runtime_runner_sha256':d['runner_sha256'],'rows':[],'errors':[],'expected':{}}
    measured=[s for s in d['samples'] if s['kind']=='measure']
    if len(measured)!=120:
        report['status']='incomplete';reports.append(report);continue
    for index,row in enumerate(d['samples']):
        if row['kind']=='network-setup':continue
        stem=f"{index:04d}-{row['label']}-{row['workload']}-{row['kind']}"
        stdout=(path.parent/(stem+'.stdout')).read_bytes()
        stderr=(path.parent/(stem+'.stderr')).read_bytes()
        errors=[]
        normalized=stderr
        expected_exit=2 if d['name']=='ruff' and row['workload']=='format' else 0
        if row['returncode']!=expected_exit:errors.append(f"Unexpected status {row['returncode']}; expected {expected_exit}")
        if d['name']=='ruff':
            if digest(stdout)!=row['output_sha256']:errors.append('Recorded stdout digest differs from raw file')
            if row['workload']=='check':
                expected=[b'warning: Docstring at Lib/test/test_getpath.py:390:9 contains implicit string concatenation; ignoring...',b'warning: Unexpected `# ruff: noqa` directive at Lib/test/test_with.py:177. File-level suppression comments must appear on their own line. For line-level suppression, omit the `ruff:` prefix.']
                if collections.Counter(stderr.splitlines())!=collections.Counter(expected):errors.append('Unexpected Ruff warning line multiset')
                normalized=b'\n'.join(sorted(stderr.splitlines()))
            elif stderr!=b'':errors.append('Unexpected formatter stderr')
        else:
            normalized,count=re.subn(rb'(?m)^(Resolved \d+ packages? in )\d+(?:\.\d+)?(?:ms|s)$',rb'\1<TIME>',stderr)
            if count!=1:errors.append(f'Expected one anchored resolution elapsed-time line, got {count}')
        signature={'returncode':row['returncode'],'stdout_sha256':digest(stdout),'output_sha256':row['output_sha256'],'normalized_stderr_sha256':digest(normalized)}
        reference=report['expected'].setdefault(row['workload'],signature)
        if signature!=reference:errors.append('Status, output, or normalized diagnostics differ within workload')
        receipt={'index':index,'label':row['label'],'workload':row['workload'],'kind':row['kind'],'pair':row.get('pair'),'returncode':row['returncode'],'stdout_sha256':digest(stdout),'stderr_sha256':digest(stderr),'normalized_stderr_sha256':digest(normalized),'errors':errors}
        report['rows'].append(receipt)
        report['errors'].extend({'index':index,'error':error} for error in errors)
    report['status']='passed' if not report['errors'] else 'failed'
    reports.append(report)
args.output.write_text(json.dumps(reports,indent=2)+'\n')
for report in reports:print(report['source'],report['status'],len(report['errors']))
if any(report['status']=='failed' for report in reports):raise SystemExit(1)
