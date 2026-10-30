#!/usr/bin/env python3
"""Off-clock only. Preserve Cargo's stdin, stdout, diagnostic stream and jobserver."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
real=sys.argv[1];args=sys.argv[2:]
if '--crate-name' not in args or args[args.index('--crate-name')+1]!='ron' or '--out-dir' not in args:
    os.execv(real,[real,*args])
assert any('/ron-0.12.0/src/lib.rs' in a for a in args) and '--emit=dep-info,metadata' in args
dest=Path(os.environ['QA_RON_PROFILE'])/str(os.getpid());dest.mkdir()
actual=[real,*args,'-Zself-profile='+str(dest),'-Ztime-passes','-Ztime-passes-format=json']
(dest/'invocation.json').write_text(json.dumps({'args':actual,'cwd':os.getcwd(),'driver':hashlib.sha256(Path(real).resolve().read_bytes()).hexdigest()})+'\n')
with (dest/'timings.stderr').open('xb') as log:
    p=subprocess.Popen(actual,stderr=subprocess.PIPE,close_fds=False)
    for raw in p.stderr:
        log.write(raw);sys.stderr.buffer.write(raw);sys.stderr.buffer.flush()
status=p.wait();sys.exit(status if status>=0 else 128-status)
