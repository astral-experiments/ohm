#!/usr/bin/env python3
"""Runtime/output guards for the three retained original-source executables."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import time
import bench

ROOT=bench.ROOT
OUT=bench.OUT/'runtime'
OUT.mkdir(exist_ok=True)
CACHE=ROOT/'runtime-uv-cache'
CORPUS=ROOT/'corpus/cpython-0b05ead877f909b7efe712db758012d9dbece7ce'
ENV={k:v for k,v in os.environ.items() if not k.startswith(('UV_','PIP_'))}
ENV.update(UV_DEFAULT_INDEX='https://pypi.org/simple',UV_PYTHON_DOWNLOADS='never',NO_COLOR='1')

def command(repo, variant, workload, offline=True):
    binary=bench.OUT/f'{repo}-{variant}-original'
    if repo=='ruff':
        if workload=='format':
            return [str(binary),'format','--isolated','--check','--no-cache','--target-version','py312','--exclude','**/test/**,**/tests/**',str(CORPUS/'Lib')]
        return [str(binary),'check','--isolated','--no-cache','--exit-zero',str(CORPUS)]
    result=OUT/f'uv-{workload}.txt'
    result.unlink(missing_ok=True)
    return [str(binary),'--no-config','--cache-dir',str(CACHE),'pip','compile',str(ROOT/'uv/test/requirements'/f'{workload}.in'),'--no-header','--exclude-newer','2026-10-01T00:00:00Z','--python-version','3.12','--output-file',str(result)]+(['--offline'] if offline else [])

def execute(repo,variant,workload,index,offline=True):
    args=command(repo,variant,workload,offline)
    stem=f'{repo}-{workload}-{index}-{variant}'
    with (OUT/(stem+'.stdout')).open('wb') as stdout,(OUT/(stem+'.stderr')).open('wb') as stderr:
        started=time.monotonic()
        proc=subprocess.Popen(args,env=ENV,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
        monitor=bench.CpuMonitor(proc.pid); monitor.start()
        _,status,usage=os.wait4(proc.pid,0)
        code=os.waitstatus_to_exitcode(status);proc.returncode=code
        elapsed=time.monotonic()-started
        monitor.stop_event.set();monitor.join()
    assert code in ([0,1] if workload=='format' else [0]),(args,code,stem)
    output=(OUT/f'uv-{workload}.txt').read_bytes() if repo=='uv' else (OUT/(stem+'.stdout')).read_bytes()
    # Formatter file messages are parallel results; preserve the summary and compare sorted paths.
    if workload=='format':
        lines=output.splitlines()
        positions=[i for i,line in enumerate(lines) if line.startswith(b'Would reformat: ')]
        for i,line in zip(positions,sorted(lines[i] for i in positions)):
            lines[i]=line
        output=b'\n'.join(lines)+b'\n'
    row=dict(repo=repo,variant=variant,workload=workload,index=index,exit_code=code,elapsed_s=elapsed,peak_rss_kib=usage.ru_maxrss,user_cpu_s=usage.ru_utime,system_cpu_s=usage.ru_stime,command=args,output_sha256=hashlib.sha256(output).hexdigest(),outside_cpu=monitor.rows)
    (OUT/(stem+'.json')).write_text(json.dumps(row,indent=2)+'\n')
    return row

rows=[]
for repo,workload in [('uv','jupyter'),('uv','trio'),('ruff','cpython'),('ruff','format')]:
    bench.wait_for_no_compilers()
    # Populate the public resolver cache outside the offline runtime measurements.
    if repo=='uv':execute(repo,'off',workload,'populate',offline=False)
    expected=None
    expected_code=None
    for variant in ['fat','off','on']:
        row=execute(repo,variant,workload,'warm')
        expected=expected or row['output_sha256']
        expected_code=row['exit_code'] if expected_code is None else expected_code
        assert row['exit_code']==expected_code,(repo,workload,row)
        assert row['output_sha256']==expected,(repo,workload,row)
    for index in range(1,21):
        for variant in (['fat','off','on'] if index%2 else ['on','off','fat']):
            row=execute(repo,variant,workload,index)
            assert row['output_sha256']==expected,(repo,workload,row)
            assert row['exit_code']==expected_code,(repo,workload,row)
            rows.append(row)
            print(json.dumps({k:row[k] for k in ['repo','variant','workload','index','elapsed_s']}),flush=True)
(OUT/'measurements.json').write_text(json.dumps(rows,indent=2)+'\n')

# Post hoc stderr equivalence, retaining every original stderr file unchanged.
def normalize_stderr(text):
    text=re.sub(r"(?m)^(Resolved \d+ packages in )[0-9.msh ]+$",r"\1<TIME>",text)
    lines=text.splitlines()
    indices=[i for i,line in enumerate(lines) if line.startswith('warning: ')]
    for i,line in zip(indices,sorted(lines[i] for i in indices)):
        lines[i]=line
    return '\n'.join(lines)+'\n'

stderr_hashes={}
for repo,workload in [('uv','jupyter'),('uv','trio'),('ruff','cpython'),('ruff','format')]:
    selected=[row for row in rows if row['repo']==repo and row['workload']==workload]
    hashes=set()
    for row in selected:
        stem=f"{repo}-{workload}-{row['index']}-{row['variant']}"
        normalized=normalize_stderr((OUT/(stem+'.stderr')).read_text())
        hashes.add(hashlib.sha256(normalized.encode()).hexdigest())
    assert len(hashes)==1,(repo,workload,hashes)
    stderr_hashes[f'{repo}-{workload}']=next(iter(hashes))
(OUT/'stderr-equivalence.json').write_text(json.dumps({'sha256':stderr_hashes,'normalizations':['Resolved N packages timing only','Order of single-line warning: messages only']},indent=2)+'\n')

