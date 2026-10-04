"""One contextual off/on rebuild pair on the same rebuilt compiler."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
root=Path('/tmp/ohm-release-campaign/llvm');repo=root/'ruff';output=root/'evidence/flag-validation'
source=repo/'crates/ruff/src/main.rs';original=source.read_text();needle='Failed to read CLI arguments from files'
assert original.count(needle)==1
assert subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)==''
edit=original.replace(needle,needle+' (LLVM actual flag pair)')
artifacts={}
try:
 source.write_text(edit)
 for name,flag in [('unprofiled-off','no'),('unprofiled-on','yes')]:
  assert shutil.disk_usage(root).free>=20*1024**3
  subprocess.run(['python3',str(root/'harness/measure-v3.py'),'--output',str(output),'--name',name,'--cwd',str(repo),'--',str(root/'toolchain/bin/cargo'),'rustc','--locked','--offline','--release','-p','ruff','--bin','ruff','--',f'-Zearly-lto-merge-functions={flag}'],check=True)
  binary=Path(os.environ['CARGO_TARGET_DIR'])/'release/ruff'
  shutil.copy2(binary,output/f'{name}-ruff')
  record={'source_sha256':hashlib.sha256(edit.encode()).hexdigest(),'binary_bytes':binary.stat().st_size,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}
  (output/f'{name}.provenance.json').write_text(json.dumps(record,indent=2)+'\n');artifacts[name]=record
finally:source.write_text(original)
(output/'artifacts.json').write_text(json.dumps(artifacts,indent=2)+'\n')
(output/'complete').touch()
