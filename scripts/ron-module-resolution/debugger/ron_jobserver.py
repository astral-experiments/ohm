#!/usr/bin/python3
"""Restore the jobserver interface from the genuine recorded Cargo command for a private GDB replay."""
import fcntl
import json
import os
from pathlib import Path
import re
import sys

compiler = os.environ['OHM_LICENSED_RUSTC']
assert os.path.samefile(sys.argv[1], compiler)
flags = os.environ['CARGO_MAKEFLAGS']
pairs = [tuple(map(int, m.groups())) for word in flags.split()
         if (m := re.fullmatch(r'--jobserver-(?:fds|auth)=(\d+),(\d+)', word))]
assert pairs and len(set(pairs)) == 1 and '-j' in flags.split(), flags
rfd, wfd = pairs[0]
assert min(rfd, wfd) >= 3 and rfd != wfd and max(rfd, wfd) < 64
originals = os.pipe()
r, w = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 64) for fd in originals]
for fd in originals:
    os.close(fd)
# The top-level registered Cargo command has four jobs. The current execution owns one.
os.write(w, b'+++')
os.dup2(r, rfd, inheritable=True)
os.dup2(w, wfd, inheritable=True)
os.close(r)
os.close(w)
a, b = os.fstat(rfd), os.fstat(wfd)
assert (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
Path(os.environ['OHM_F_JOBSERVER_PROOF']).write_text(json.dumps(
    dict(flags=flags, abi_fds=[rfd,wfd], private_tokens=3, pipe_dev=a.st_dev, pipe_ino=a.st_ino))+'\n')
os.execv(compiler, [compiler, *sys.argv[2:]])
