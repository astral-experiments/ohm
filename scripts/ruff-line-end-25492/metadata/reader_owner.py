#!/usr/bin/python3 -IB
"""Attach query recording to one physically authenticated, real host rustc."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def freeze(src, dest):
    before = src.stat()
    with src.open('rb') as f, gzip.open(dest, 'xb', compresslevel=2) as z:
        shutil.copyfileobj(f, z, length=1 << 20)
    after = src.stat()
    assert (before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns)
    return {'bytes':before.st_size,'sha256':sha(src),'gzip_sha256':sha(dest)}

def main():
    rustc,*argv=sys.argv[1:]
    if '--crate-name' not in argv or argv[argv.index('--crate-name')+1]!='ruff_python_trivia':
        os.execv(rustc,[rustc,*argv])
    here=Path(os.environ['OHM_READ_RECEIPT'])
    signed=Path(os.environ['OHM_READ_SIGNED'])
    assert Path(rustc).samefile(signed) and sha(signed)==os.environ['OHM_READ_SIGNED_SHA']
    assert '--crate-type' in argv and argv[argv.index('--crate-type')+1]=='lib' and any(s.startswith('--emit=') and 'link' in s[7:].split(',') for s in argv)
    inputs=[Path(s.partition('=')[2]) for s in argv if s.startswith('ruff_source_file=')]
    assert len(inputs)==1 and inputs[0].is_file()
    state=Path(os.environ['OHM_READ_STATE'])
    inc,=[Path(s.split('incremental=',1)[1]) for s in argv if s.startswith(('incremental=','-Cincremental='))]
    assert inc.is_absolute() and inc.is_relative_to(state) and not any('self-profile' in s for s in argv)
    assert not (here/'original.json').exists()
    def graphs():
        return {p:p.stat().st_ino for p in inc.glob('ruff_python_trivia-*/s-*/dep-graph.bin') if not p.parent.name.endswith('-working')}
    before=graphs()
    (here/'original.json').write_text(json.dumps({'argv':[rustc,*argv],'provider_path':str(inputs[0]),'provider_sha256':sha(inputs[0]),'previous':{str(k):v for k,v in before.items()}},indent=2))
    profile_dir=here/'self-profile';profile_dir.mkdir()
    opts=['-Zself-profile='+str(profile_dir),'-Zself-profile-events=default,query-keys']
    cmd=[rustc,*argv,*opts]
    child=subprocess.Popen(cmd)
    status=child.wait()
    assert status==0,(child.pid,status)
    graph,=[p for p,i in graphs().items() if before.get(p)!=i]
    profile,=profile_dir.glob('*.mm_profdata')
    assert profile.stem.rsplit('-',1)[1].isdigit() and int(profile.stem.rsplit('-',1)[1])==child.pid
    alias=graph.with_name('ohm-build-dep-graph.bin')
    assert not alias.exists() or sha(graph)==sha(alias)
    record={'pid':child.pid,'argv':cmd,'graph_path':str(graph),'profile_path':str(profile),'alias':alias.exists(),'rustc':sha(signed),'cwd':str(Path.cwd())}
    for label,path in [('graph',graph),('profile',profile),('provider',inputs[0])]:
        record[label]=freeze(path,here/(label+'.gz'))
    with (here/'process.json').open('x') as out:
        json.dump(record,out,sort_keys=True,indent=2)
    # Retain the identical compressed profile once.
    profile.unlink()
if __name__=='__main__':main()
