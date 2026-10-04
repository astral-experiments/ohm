#!/usr/bin/env python3
"""Untimed direct-rustc cache mechanism trace, after all timing completes."""
import hashlib,json,os,re,subprocess,time
from pathlib import Path
import bench

root=bench.ROOT
capture=json.loads((bench.OUT/'captured-root-on.json').read_text())
assert capture['variant']=='on'
args=capture['args']+['-Ztime-passes']
env=bench.environment('uv','on')
env.update(capture['env']);env['RUSTC_LOG']='rustc_codegen_llvm::back::lto=info'
binary=Path(args[args.index('--out-dir')+1])/'uv'
rows=[]
for index in [1,2]:
    log=bench.OUT/f'uv-mechanism-{index}.log'
    with log.open('wb') as stream:
        code=subprocess.call(args,cwd=capture['cwd'],env=env,stdout=stream,stderr=subprocess.STDOUT)
    assert code==0,log
    text=log.read_text()
    upstream=set(re.findall(r'upstream module "([^"]+)"',text))
    reused=set(re.findall(r' - (.*): re-used',text))
    compiled=set(re.findall(r' - (.*): re-compiled',text))
    rows.append({'index':index,'upstream_modules':len(upstream),'reused_upstream_modules':len(upstream&reused),'compiled_upstream_modules':len(upstream&compiled),'reused_total':len(reused),'compiled_total':len(compiled),'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()})
assert rows[0]['binary_sha256']==rows[1]['binary_sha256'],rows
(bench.OUT/'mechanism.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))

