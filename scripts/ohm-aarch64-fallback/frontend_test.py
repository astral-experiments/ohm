"""Exercise real same-UID process attribution and reject altered incremental options using two tiny Python executables."""
from pathlib import Path
import json,os,shutil,subprocess,sys,tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from frontend import flags,with_live_environment
source="""
from pathlib import Path
import json,os,subprocess,sys
target=Path(sys.argv[1]);record=Path(sys.argv[2])
av=[str(target),'-c','import time; time.sleep(.35)','--crate-name','ruff_python_ast','--target','aarch64-unknown-linux-gnu','-C','lto=off','-C','incremental=/tmp/test-only']
p=subprocess.Popen(av);args=Path('/proc/self/cmdline').read_bytes().rstrip(b'\\0').split(b'\\0')
record.write_text(json.dumps({'cargo':[{'pid':os.getpid(),'argv':list(map(os.fsdecode,args)),'terminal':[0]}],
 'rustcs':[{'pid':p.pid,'crate':'ruff_python_ast','argv':av,'terminal':[0]}]}))
assert p.wait()==0
"""
with tempfile.TemporaryDirectory() as tmp:
 b=Path(tmp);(b/'bin').mkdir()
 for n in ('cargo','rustc'):
  shutil.copyfile(Path(sys.executable).resolve(),b/'bin'/n);(b/'bin'/n).chmod(0o755)
 report=b/'roster.json'
 def visit():
  subprocess.run([b/'bin/cargo','-c',source,b/'bin/rustc',report,'build'],env={'PYTHONHOME':sys.base_prefix},check=True)
 _,out=with_live_environment(visit,report,b)
 assert set(out)=={'ast','cargo'} and out['ast']['flags']['lto']=='off'
 av=out['ast']['argv']
 for mutant in (['-C','incremental=/tmp/unregistered'],['-C','lto=thin'],['-C','linker-plugin-lto=yes']):
  try:flags(av+mutant)
  except AssertionError:pass
  else:raise AssertionError(mutant)
 assert out['ast']['physical']['ino']!=(b/'bin/cargo').stat().st_ino
 print('Physical process, real argv and missing/duplicate option guards passed')
