#!/usr/bin/env python3
"""Counterbalanced target-cold builds, retaining receipts before target reuse."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
root=Path('/tmp/ohm-release-campaign/llvm')
workload=sys.argv[1]
assert workload in ('uv','ruff')
repo=root/workload
output=root/f'evidence/cold-{workload}'
output.mkdir(exist_ok=True)
bounded=Path(f'/tmp/codex-cargo-targets/{workload}/isolated/release-llvm')
assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
repeats=json.loads((root/'evidence/paired-uv/scope-decision.json').read_text())['cold_pairs'] if workload == 'uv' else 3
for pair in range(repeats):
 order=['baseline','merge'] if pair%2==0 else ['merge','baseline']
 for variant in order:
  target=bounded/'cold'
  marker=target/'.llvm-release-benchmark-owned'
  if target.exists():
   assert target.parent==bounded and target.is_dir() and not target.is_symlink()
   assert marker.read_text()=='llvm-release-target-cold\n'
   # Only this serialized harness uses this task-owned target. The prior
   # command has exited and its logs/receipts are outside the target directory.
   shutil.rmtree(target)
  target.mkdir(parents=True)
  marker.write_text('llvm-release-target-cold\n')
  name=f'pair-{pair+1}-{variant}'
  env=os.environ.copy();env['CARGO_TARGET_DIR']=str(target)
  subprocess.run(['python3',str(root/'harness/measure-v3.py'),'--output',str(output),'--name',name,'--cwd',str(repo),'--',str(root/'toolchain/bin/cargo'),'rustc','--locked','--offline','--release','-p',workload,'--bin',workload,'--',f'-Zllvm-plugins={root}/plugins/{variant}.so'],env=env,check=True)
  compiled=(output/f'{name}.stderr').read_text().count('Compiling ')
  assert compiled>150,(name,compiled)
  binary=target/f'release/{workload}'
  data={'pair':pair+1,'variant':variant,'compiled_packages':compiled,'binary_bytes':binary.stat().st_size,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'source_pin':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()}
  (output/f'{name}.provenance.json').write_text(json.dumps(data,indent=2)+'\n')
  assert shutil.disk_usage('/tmp').free>20*1024**3
(output/'complete').touch()
