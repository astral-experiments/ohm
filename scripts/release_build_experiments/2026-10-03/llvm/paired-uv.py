#!/usr/bin/env python3
import hashlib,json,os,subprocess,time
from pathlib import Path
root=Path('/tmp/ohm-release-campaign/llvm')
repo=root/'uv'
output=root/'evidence/paired-uv'
output.mkdir(exist_ok=True)
source=repo/'crates/uv/src/bin/uv.rs'
original=source.read_text()
needle='    unsafe { uv_main(std::env::args_os()) }'
assert original.count(needle)==1
assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
try:
 for pair in range(4):
  # A real entrypoint refactor with a unique local binding per pair. Runtime
  # semantics stay identical, while every pair has a new source fingerprint.
  edit=original.replace(needle,f'    let args_llvm_pair_{pair+1} = std::env::args_os();\n    unsafe {{ uv_main(args_llvm_pair_{pair+1}) }}')
  source.write_text(edit)
  order=['baseline','merge'] if pair%2==0 else ['merge','baseline']
  for variant in order:
   name=f'pair-{pair+1}-{variant}'
   subprocess.run(['python3',str(root/'harness/measure-v3.py'),'--output',str(output),'--name',name,'--cwd',str(repo),'--',str(root/'toolchain/bin/cargo'),'rustc','--locked','--offline','--release','-p','uv','--bin','uv','--',f'-Zllvm-plugins={root}/plugins/{variant}.so'],check=True)
   binary=Path(os.environ['CARGO_TARGET_DIR'])/'release/uv'
   data={'pair':pair+1,'variant':variant,'source_sha256':hashlib.sha256(edit.encode()).hexdigest(),'binary_bytes':binary.stat().st_size,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
   (output/f'{name}.provenance.json').write_text(json.dumps(data,indent=2)+'\n')
   assert __import__('shutil').disk_usage('/tmp').free>20*1024**3
  if pair == 1:
   (output/'scope-review-ready').touch()
   print('Two uv edit pairs complete; waiting for scope review.', flush=True)
   decision=output/'scope-decision.json'
   while not decision.exists():time.sleep(5)
   plan=json.loads(decision.read_text())
   assert plan['edit_pairs'] in (2,4) and plan['cold_pairs'] in (1,2)
   if plan['edit_pairs']==2:break
finally:
 source.write_text(original)
(output/'complete').touch()
