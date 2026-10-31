"""Give both private GC probes the exact executable built for the two other jobs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def digest(path):
    with path.open('rb') as data:return hashlib.file_digest(data,'sha256').hexdigest()

def main(product,sdk,protocol,root):
    repo=Path(__file__).resolve().parent
    spec=json.loads((repo/'candidate-source/spec.json').read_bytes());seal=json.loads((product/'build.json').read_bytes())
    assert not root.exists() and product.is_dir() and sdk.is_dir()
    assert spec['head']=='761ea115605c34f11a1cd29afd68812c1e1359dd' and spec['tree']=='19c379477ec24be16c82b952dc2e892c0563e2c7'
    assert seal['qa']==os.environ['GITHUB_SHA'] and seal['candidate']==seal['tree']['commit']==spec['head']
    assert seal['tree']['tree']==spec['tree'] and seal['tree']['mode_path_sha256_inventory']==spec['inventory']
    assert digest(product/'cargo')==seal['compiled']==seal['delivered']==os.environ['BUILT_CARGO_SHA256']
    assert digest(product/'build.json')==os.environ['ORIGINAL_BUILD_SHA256']
    assert digest(sdk/'bin/cargo')=='4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e'
    assert subprocess.check_output(['git','-C',protocol,'rev-parse','HEAD'],text=True).strip()=='786e5235c3faf04fcfde6beef6c2b91537d37696'
    (product/'cargo').chmod(0o755)
    assert subprocess.check_output([product/'cargo','-Vv'],text=True)==seal['version']
    root.mkdir(mode=0o700);records=root/'evidence';records.mkdir()
    registration={'source':spec['head'],'tree':spec['tree'],'inventory':spec['inventory'],'cargo_sha256':seal['compiled'],
                  'build_sha256':digest(product/'build.json'),'workflow_sha':seal['qa'],'workflow_run':int(os.environ['GITHUB_RUN_ID'])}
    (records/'registration.json').write_text(json.dumps(registration,sort_keys=True,indent=2)+'\n');shutil.copyfile(product/'build.json',records/'build.json')
    codes={}
    for role in ('stack','stack-enosys'):
        work=root/role;work.mkdir();(work/'product').symlink_to(product,target_is_directory=True);(work/'sdk-21').symlink_to(sdk,target_is_directory=True)
        shutil.copyfile(records/'registration.json',work/'stack-receipt.json')
        result=subprocess.run([sys.executable,'-IB',protocol/'scripts/private-gc-overlay/reattached.py',role,str(work)],capture_output=True,timeout=270)
        codes[role]=result.returncode
        if (work/'packet').exists():shutil.copytree(work/'packet',records/role)
        (records/(role+'.stdout')).write_bytes(result.stdout);(records/(role+'.stderr')).write_bytes(result.stderr)
        if result.returncode:print(result.stderr.decode(errors='replace')[-2200:],file=sys.stderr)
    (records/'terminal.json').write_text(json.dumps(codes,sort_keys=True)+'\n')
    assert all(v==0 for v in codes.values()),codes

if __name__=='__main__':main(*[Path(arg).resolve() for arg in sys.argv[1:]])
