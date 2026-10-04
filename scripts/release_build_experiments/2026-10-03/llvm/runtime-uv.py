#!/usr/bin/env python3
"""Measure pinned offline dependency resolution with exact output guards."""
from pathlib import Path
import hashlib,json,os,re,statistics,subprocess,time
root=Path('/tmp/ohm-release-campaign/llvm')
output=root/'evidence/runtime-uv'
output.mkdir(exist_ok=True)
variants=['baseline','merge']
cache=root/'uv-runtime-cache'
rows=[]
for workload in ['trio','jupyter']:
 requirements=root/f'uv/test/requirements/{workload}.in'
 destination=output/f'{workload}.txt'
 common=['pip','compile',str(requirements),'--index-url','https://pypi.org/simple','--exclude-newer','2026-10-01T00:00:00Z','--python-version','3.12','--cache-dir',str(cache),'--no-header','--output-file',str(destination)]
 warm=subprocess.run([str(root/'evidence/binaries/baseline-uv'),*common],cwd=root/'uv',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 (output/f'{workload}-warm.stdout').write_bytes(warm.stdout)
 (output/f'{workload}-warm.stderr').write_bytes(warm.stderr)
 assert warm.returncode==0,warm.stderr.decode(errors='replace')
 expected=destination.read_bytes()
 assert len(expected)>100
 for repetition in range(6):
  order=variants if repetition%2==0 else list(reversed(variants))
  for variant in order:
   destination.unlink(missing_ok=True)
   started=time.perf_counter()
   result=subprocess.run([str(root/f'evidence/binaries/{variant}-uv'),*common,'--offline'],cwd=root/'uv',stdout=subprocess.PIPE,stderr=subprocess.PIPE)
   elapsed=time.perf_counter()-started
   stem=f'{workload}-{repetition}-{variant}'
   for stream in ['stdout','stderr']:(output/f'{stem}.{stream}').write_bytes(getattr(result,stream))
   assert result.returncode==0,result.stderr.decode(errors='replace')
   lock=destination.read_bytes()
   assert lock==expected,stem
   stderr=re.sub(rb'(Resolved [0-9]+ packages? in )[0-9.]+(?:ms|s|m)(?=\n|\r|$)',rb'\1<TIME>',result.stderr)
   row={'workload':workload,'variant':variant,'repetition':repetition,'wall_seconds':elapsed,'returncode':result.returncode,'lock_sha256':hashlib.sha256(lock).hexdigest(),'stdout_sha256':hashlib.sha256(result.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(result.stderr).hexdigest(),'stderr_normalized_sha256':hashlib.sha256(stderr).hexdigest()}
   rows.append(row)
   (output/'samples.json').write_text(json.dumps(rows,indent=2)+'\n')
for workload in ['trio','jupyter']:
 selected=[r for r in rows if r['workload']==workload]
 assert len({(r['returncode'],r['lock_sha256'],r['stdout_sha256'],r['stderr_normalized_sha256']) for r in selected})==1,workload
 print(workload,{v:statistics.median(r['wall_seconds'] for r in selected if r['variant']==v) for v in variants},flush=True)
(output/'complete').touch()
