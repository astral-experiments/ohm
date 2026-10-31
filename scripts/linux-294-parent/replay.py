"""Replay the four host-reader cases offline against an immutable signed SDK and a genuine Ruff checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
def hx(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('output',type=Path,help='new path with at least 3 GiB free')
    for name in ('signed-sdk','ruff','registry-home','rustup-bin'):
        cli.add_argument('--'+name,type=Path,required=True)
    cli.add_argument('--products',type=Path,required=True)
    a=cli.parse_args(); supplied=a.signed_sdk.resolve(strict=True)
    roles=json.loads(a.products.read_bytes());assert list(roles)==['parent','signed','matched294','combined','defaults-off','stock-cargo']
    a.output=a.output.resolve(); a.output.mkdir(); private=a.output/'host-unicode-wild-dir-v1';private.mkdir()
    if shutil.disk_usage(private).free<11*(1<<28)+300*(1<<20):
        raise SystemExit('private copy, native fixtures and standing 2.75 GiB physical reserve require another 300 MiB')
    s=private/'rustup/toolchains/ohm';s.mkdir(parents=True)
    wild_dir=Path('lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld')
    real_dirs={'bin','lib','lib/rustlib','lib/rustlib/x86_64-unknown-linux-gnu','lib/rustlib/x86_64-unknown-linux-gnu/bin',str(wild_dir)}
    def mirror(rel):
        for q in sorted((supplied/rel).iterdir()):
            tail=rel/q.name; dst=s/tail
            if str(tail) in real_dirs:
                dst.mkdir();mirror(tail)
            elif str(tail)=='bin/rustc' or (rel==Path('lib') and q.name.startswith('librustc_driver-')):
                shutil.copyfile(q,dst);shutil.copymode(q,dst)
            else:dst.symlink_to(q)
    mirror(Path('.'))
    assert not (supplied/wild_dir/'libutil.so').exists() and not (s/wild_dir/'libutil.so').exists()
    assert not (s/'bin/rustc').samefile(supplied/'bin/rustc')
    drv,=(s/'lib').glob('librustc_driver-*')
    assert not drv.samefile(supplied/'lib'/drv.name)
    # Only the real private root may acquire the experimental library.
    assert (s/wild_dir).resolve()==s/wild_dir
    n=private/'native';n.mkdir()
    shutil.copyfile(HERE/'provider.c',n/'generator-provider.c')
    for role,code in [('83','0053'),('47','002F')]:
        target=n/('observe-'+role+'.so')
        command=['/usr/bin/cc','-shared','-fPIC','-O2','-DREPLACE_CODE="'+code+'"',str(n/'generator-provider.c'),'-Wl,-soname,'+str(s/wild_dir/'libutil.so'),'-ldl','-o',str(target)]
        subprocess.run(command,check=True)
        dynamic=subprocess.check_output(['readelf','-dW',target],text=True)
        assert ('['+str(s/wild_dir/'libutil.so')+']') in dynamic
    assert (n/'observe-83.so').stat().st_size==(n/'observe-47.so').stat().st_size
    cfg=dict(private_state=str(private),signed_sdk=str(supplied),ruff=str(a.ruff.resolve(strict=True)),proxy=str(a.rustup_bin.resolve(strict=True)),registry_home=str(a.registry_home.resolve(strict=True)),effective_home=str(Path.home()),
             roles=roles,qa=os.environ['GITHUB_SHA'])
    f=private/'fixture-config.json';f.write_text(json.dumps(cfg,sort_keys=True,indent=2)+'\n')
    subprocess.run([sys.executable,'-IB',str(HERE/'capture.py'),str(f),'results'],check=True)
    completed=json.loads((private/'results/complete.json').read_bytes());assert set(completed)==set(roles)
if __name__=='__main__':main()
