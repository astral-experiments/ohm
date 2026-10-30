"""Reuse #306's unchanged public private-target bind control in a fresh mount namespace."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'gc-mount-evidence'))
import compare as old

def main(role,root,inside):
    spec=json.loads((HERE/'sources'/role/'candidate-source/spec.json').read_bytes());cert=json.loads((root/'packet'/role/'build.json').read_bytes())
    assert cert['candidate']==spec['head'] and cert['qa']==os.environ.get('GITHUB_SHA',cert['qa'])
    runtime=root/'sdk-fixed';out=root/'packet'/'fixed'
    if not inside:
        runtime.symlink_to(root/('sdk-'+role),target_is_directory=True)
        out.mkdir(parents=True)
        w=Path(tempfile.mkdtemp(prefix='qa-fixed-',dir=root));nonce=str(uuid.uuid4());(w/'.owned').write_text(nonce)
        outer=old.o.ns();args=['sudo','-n','/usr/bin/env','-i','PATH=/usr/sbin:/usr/bin:/sbin:/bin','LANG=C','/usr/bin/unshare','--mount','--propagation','private','--fork','--','/usr/bin/python3','-IB',str(Path(__file__).resolve()),role,str(root),'inside',str(w),str(outer),str(os.getuid()),str(os.getgid()),nonce,shutil.which('rustup')]
        proc=subprocess.run(args,capture_output=True,timeout=180)
        (out/'worker.stdout').write_bytes(proc.stdout);(out/'worker.stderr').write_bytes(proc.stderr)
        assert proc.returncode==0,proc.stderr
        assert outer==old.o.ns() and not any(Path(v['path']).is_relative_to(w) for v in old.o.mounts().values())
        result=json.loads((out/'result.json').read_bytes());assert result['before']==result['after'] and result['healthy'] is False and result['exit']==0
        return
    work=Path(sys.argv[4]);ns,uid,gid=map(int,sys.argv[5:8]);nonce,proxy=sys.argv[8:10]
    f=old.Fixture('fixed',root,work,runtime,out,uid,gid,ns,nonce,proxy,spec['head'],cert['compiled'])
    result=old.private(f);old.o.save(out/'result.json',result)
if __name__=='__main__':main(sys.argv[1],Path(sys.argv[2]).resolve(),len(sys.argv)>3 and sys.argv[3]=='inside')
