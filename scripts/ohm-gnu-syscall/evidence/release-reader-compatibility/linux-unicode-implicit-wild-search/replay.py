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
    for name in ('classic','aware','fd55'):
        cli.add_argument('--'+name+'-cargo',type=Path)
    cli.add_argument('--roles',nargs='+',choices=('signed','classic','aware','fd55'),default=['signed','classic','aware','fd55'])
    a=cli.parse_args(); supplied=a.signed_sdk.resolve(strict=True)
    inputs={}
    for role in ('classic','aware','fd55'):
        value=getattr(a,role+'_cargo')
        if role in a.roles and value is None:cli.error(f'--{role}-cargo is required when {role} is selected')
        inputs[role]=str(value.resolve(strict=True) if value else supplied/'bin/cargo')
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
             **inputs,roles=a.roles)
    f=private/'fixture-config.json';f.write_text(json.dumps(cfg,sort_keys=True,indent=2)+'\n')
    subprocess.run([sys.executable,'-IB',str(HERE/'capture.py'),str(f),'results'],check=True)
    data={r:json.loads((private/'results'/r/'complete.json').read_text()) for r in a.roles}
    for r,events in data.items():
        strict=r in ('classic','aware')
        for entry in events:
            p=entry['phase']; st=entry['state']; result=entry['result']
            strict_visit=strict or p.startswith('empty-')
            expected=101 if st=='bad' and strict_visit else 0
            assert result['status']==expected,(r,p,result['status'],expected)
            if expected==0:
                val=int(st) if st in ('83','47') and strict_visit else 0
                assert result['reader']==[f'Some({val})','Some(0)']
            l=len(result['physical']['ld'])
            assert l==(int(strict or p.startswith('empty-') or p=='warm-absent')),(r,p,l)
            if expected==0:
                label='absent' if val==0 else str(val)
                ref=next(row['result'] for row in events if row['phase']=='empty-'+label)
                assert result['reader_sha256']==ref['reader_sha256'] and result['generated']==ref['generated'],(r,p,'own empty artifacts')
        print(r,'passed ten ordinary commands, exact complete reader and three generated files against matching independent empty, and diagnostic gates')
if __name__=='__main__':main()
