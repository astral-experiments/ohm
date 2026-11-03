"""The installed Ubuntu perf sets environment variables. Re-enter the exact sampled command environment."""
import hashlib,json,os,sys
from pathlib import Path
capsule=json.loads(Path(sys.argv[1]).read_bytes());wanted=capsule['environment']
allowed={'HOME','PATH','LANG','USER','RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR','CARGO_NET_GIT_FETCH_WITH_CLI','CARGO_BUILD_JOBS','CARGO_NET_OFFLINE','CARGO_TERM_COLOR'}
assert set(wanted)<=allowed and {'PATH','RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR'}<=set(wanted)
def short(e):return{k:hashlib.sha256(os.fsencode(v)).hexdigest()for k,v in sorted(e.items())}
actual=os.environ.copy()
Path(sys.argv[2]).write_text(json.dumps({'incoming':short(actual),'restored':short(wanted),
    'changed_keys':sorted(k for k in set(actual)|set(wanted)if actual.get(k)!=wanted.get(k)),
    'cwd':os.getcwd(),'restored_cwd':capsule['cwd']},indent=2)+'\n')
os.chdir(capsule['cwd'])
command=capsule['command'];assert Path(command[0]).is_absolute()
os.execve(command[0],command,wanted)
