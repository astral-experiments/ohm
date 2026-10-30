"""Noncompiler controls for a same-PID/same-inode re-exec, real strace environment, plus argv and environment mutations."""
import copy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import zipfile
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
import kernel_env as k
PROG="""
from pathlib import Path
import os,sys,subprocess,time
if 'transition-first' in sys.argv:
    time.sleep(.20)
    os.execv(sys.executable,[sys.executable,*[v for v in sys.argv[1:] if v!='transition-first']])
if '--crate-name' in sys.argv:
    time.sleep(.60)
else:
    view=Path(sys.executable).parent
    subprocess.run([view/'rustc',__file__,'--crate-name','ruff_python_ast','--emit=link','--target','aarch64-unknown-linux-gnu','-C','incremental=/tmp/test','-C','lto=off'],check=True)
"""
class Files:
    def __init__(self,p):self.root=p
    def read(self,p):return (self.root/p).read_bytes()
def selftest():
  with tempfile.TemporaryDirectory() as tmp:
    d=Path(tmp);kit=d/'sdk';b=kit/'bin';b.mkdir(parents=True);src=d/'program.py';src.write_text(PROG)
    for name in ('cargo','rustc'):
        shutil.copyfile(Path(sys.executable).resolve(),b/name);(b/name).chmod(0o755)
    loc=d/'edit';loc.mkdir();k.rt.SDK=kit;k.rt.RUFF=d;k.q.COMMAND=[str(b/'cargo'),str(src),'build'];k.install()
    env={'PYTHONHOME':sys.base_prefix}
    _,result=k.observe(lambda:k.q.command(loc,env),loc/'native.json',kit)
    k.dump(loc/'real-cargo-and-AST-environment.json',result)
    z=Files(d);k.verify(z,'edit')
    real=loc/'real-cargo-and-AST-environment.json';orig=real.read_bytes()
    for kind in ('argv','physical','environment_keys','kernel_exec_sha256'):
        altered=copy.deepcopy(result);v=altered['ast']
        if kind=='argv':v[kind]=v[kind]+['--unexpected-extra-option']
        elif kind=='physical':v[kind]['ino']+=1
        elif kind=='environment_keys':v[kind].append('CI')
        else:v[kind]='0'*64
        real.write_text(json.dumps(altered))
        try:k.verify(z,'edit')
        except AssertionError:pass
        else:raise AssertionError(kind)
    real.write_bytes(orig);k.verify(z,'edit')
    # Preserve a valid extra stable observation representing a preceding program image; only a
    # simultaneous exact match to the kernel identity, argv and environment may be selected.
    record=loc/'raw-physical-environment-proof.json';hold=json.loads(record.read_bytes())
    first=copy.deepcopy(hold['live'][0]);first['argv'].append('transition-first')
    hold['live'].insert(0,first);record.write_text(json.dumps(hold));k.verify(z,'edit')
    # Two genuine execs of the same Cargo test image on one PID are a different roster,
    # even if the second exec has the originally registered argv and both return successfully.
    double=d/'double';double.mkdir();k.q.COMMAND.append('transition-first')
    try:k.observe(lambda:k.q.command(double,env),double/'native.json',kit)
    except RuntimeError as e:assert 'unobserved physical release Cargo' in str(e),e
    else:raise AssertionError('accepted two application entries on one pid')
    print('Real kernel+procfs matched; incorrect argv, physical inode, environment and raw exec SHA all rejected.')
if __name__=='__main__':selftest()
