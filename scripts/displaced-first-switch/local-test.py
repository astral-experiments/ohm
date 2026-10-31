"""All filesystem effects from this synthetic smoke live in the freshly bound tmpfs."""
import hashlib, json, os, shutil, subprocess, sys
from pathlib import Path
here=Path(__file__).resolve().parent
work, sdk, registry=map(Path,sys.argv[1:])
assert work==here/'mount' and subprocess.check_output(['findmnt','--noheadings','--output','FSTYPE','--target',work],text=True).strip()=='tmpfs'
for name in ('rustup/toolchains','target','shared','home','cargo-home/registry/cache','cargo-home/registry/index','tmp'):(work/name).mkdir(parents=True,exist_ok=True)
(work/'rustup/toolchains/ohm').symlink_to(sdk)
reg='socket-firewall-registry.gateway.admin-0.internal.api.openai.org-42b3aaa0d2956984'
alias='index.crates.io-1949cf8c6b5b557f'
idx=work/'cargo-home/registry/index'/alias;idx.mkdir()
shutil.copy2(registry/'index'/reg/'config.json',idx/'config.json')
pins=json.loads((here/'codec/source.json').read_text())['crates']
for name,(version,digest) in pins.items():
    ent=Path('.cache')/name[:2]/name[2:4]/name
    (idx/ent).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(registry/'index'/reg/ent,idx/ent)
    with (registry/'cache'/reg/(name+'-'+version+'.crate')).open('rb') as f: assert hashlib.file_digest(f,'sha256').hexdigest()==digest
(work/'cargo-home/registry/index'/reg).symlink_to(alias)
for a in (alias,reg):(work/'cargo-home/registry/cache'/a).symlink_to(registry/'cache'/reg)
shutil.copytree(here/'codec',work/'codec')
env=dict(PATH='/home/dev-user/.cargo/bin:/usr/local/bin:/usr/bin:/bin',RUSTUP_HOME=str(work/'rustup'),RUSTUP_AUTO_INSTALL='0',CARGO_NET_OFFLINE='true',CARGO_HOME=str(work/'cargo-home'),CARGO_TARGET_DIR=str(work/'target'),CARGO_BUILD_BUILD_DIR=str(work/'shared'),HOME=str(work/'home'),TMPDIR=str(work/'tmp'),LC_ALL='C',CARGO_TERM_COLOR='never')
subprocess.run(['cargo','+ohm','build','--locked','--offline','--release'],check=True,cwd=work/'codec',env=env)
exe=work/'target/release/displaced-table-codec-qa'
subprocess.run([sys.executable,'-IB',here/'test_tables.py',str(exe),str(work/'synthetic')],check=True,env=env)
