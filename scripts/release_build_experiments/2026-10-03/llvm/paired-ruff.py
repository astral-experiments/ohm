#!/usr/bin/env python3
import hashlib,json,os,subprocess
from pathlib import Path
root=Path('/tmp/ohm-release-campaign/llvm')
repo=root/'ruff'
output=root/'evidence/paired-ruff'
output.mkdir(exist_ok=True)
source=repo/'crates/ruff/src/main.rs'
original=source.read_text()
needle='Failed to read CLI arguments from files'
assert original.count(needle)==1
assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
try:
 for pair in range(4):
  edit=original.replace(needle,needle+f' (LLVM pair {pair + 1})')
  source.write_text(edit)
  order=['baseline','merge'] if pair%2==0 else ['merge','baseline']
  for variant in order:
   name=f'pair-{pair+1}-{variant}'
   command=['python3',str(root/'harness/measure-v3.py'),'--output',str(output),'--name',name,'--cwd',str(repo),'--',str(root/'toolchain/bin/cargo'),'rustc','--locked','--offline','--release','-p','ruff','--bin','ruff','--',f'-Zllvm-plugins={root}/plugins/{variant}.so']
   subprocess.run(command,check=True)
   binary=Path(os.environ['CARGO_TARGET_DIR'])/'release/ruff'
   data={'pair':pair+1,'variant':variant,'source_sha256':hashlib.sha256(edit.encode()).hexdigest(),'binary_bytes':binary.stat().st_size,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
   (output/f'{name}.provenance.json').write_text(json.dumps(data,indent=2)+'\n')
finally:
 source.write_text(original)
(output/'complete').touch()
