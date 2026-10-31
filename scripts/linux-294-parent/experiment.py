"""Populate the private registry once, then run only the registered offline Cargo and native reader."""
from pathlib import Path
import os,sys,shutil,subprocess
HERE=Path(__file__).resolve().parent
def enroll(root,ruff):
    assert subprocess.check_output(['git','-C',ruff,'rev-parse','HEAD']).decode().strip()=='93526150df078af7dd8fc4226cdcc469539d2001'
    sdk=root/'sdk-21'
    rustup=Path(shutil.which('rustup')).resolve(strict=True)
    shims=root/'shims';shims.mkdir()
    for n in ['cargo','rustc']:(shims/n).symlink_to(rustup)
    home=root/'home';home.mkdir()
    alias=root/'fetch-rustup/toolchains/ohm';alias.parent.mkdir(parents=True);alias.symlink_to(sdk)
    registry=root/'registry';env={'HOME':str(home),'RUSTUP_HOME':str(alias.parent.parent),'PATH':str(shims)+':/usr/local/bin:/usr/bin:/bin','CARGO_HOME':str(registry),'LANG':'C.UTF-8'}
    subprocess.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],env=env,cwd=ruff,check=True)
    assert shutil.disk_usage(root).free>4*(1<<30) and 'GH_TOKEN' not in os.environ
    subprocess.run([sys.executable,'-IB',HERE/'replay.py',root/'private','--signed-sdk',sdk,'--ruff',ruff,'--registry-home',registry,'--rustup-bin',shims,'--products',root/'input/products.json'],env={**env,'HOME':str(home),'GITHUB_SHA':os.environ['GITHUB_SHA']},cwd=ruff,check=True)
if __name__=='__main__':enroll(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
