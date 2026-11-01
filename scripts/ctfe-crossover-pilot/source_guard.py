"""Reopen the entire reviewed component directly against its Git tree, including the checksum list."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys

def check(ok, error):
    if not ok:
        raise ValueError(error)

def tree(repo, head, prefix, extras=()):
    repo = repo.resolve(strict=True)
    def git(*args):
        return subprocess.check_output(['git','--no-optional-locks','-C',repo,*args])
    check(git('rev-parse','HEAD').decode().strip() == head, 'different checkout head')
    paths = (prefix,*extras)
    rows = git('ls-tree','-rz','--full-tree',head,'--',*paths).split(b'\0')
    got = set()
    for row in filter(None, rows):
        spec, rawname = row.split(b'\t',1)
        mode, kind, oid = spec.split()
        name = rawname.decode()
        file = repo/name
        check(kind == b'blob' and mode in (b'100644',b'100755') and file.resolve(strict=True) == file
              and file.is_file() and bool(file.stat().st_mode&0o111) == (mode == b'100755'), ('nonregular source',name))
        data = file.read_bytes()
        check(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest().encode() == oid,
              ('different committed bytes',name))
        got.add(name)
    actual = {str(p.relative_to(repo)) for p in (repo/prefix).rglob('*') if p.is_file() or p.is_symlink()} | set(extras)
    check(got == actual and len(got) > len(extras), ('unregistered/missing source files',got^actual))
    return got

def checksums(repo, files):
    prefix = 'scripts/ctfe-crossover-pilot'
    workflow = '.github/workflows/ci.yml'
    base = repo/prefix
    manifest = base/'SHA256SUMS'
    expected = {str(Path(name).relative_to(prefix)) for name in files if name.startswith(prefix+'/')} - {'SHA256SUMS'}
    expected.add('../../'+workflow)
    seen = set()
    for line in manifest.read_text().splitlines():
        digest, name = line.split('  ',1)
        check(name in expected and name not in seen and hashlib.sha256((base/name).read_bytes()).hexdigest() == digest,
              ('bad or duplicate checksum',name))
        seen.add(name)
    check(seen == expected, ('incomplete checksum manifest',expected-seen))
    return len(seen)

def pilot(repo, head):
    fields = tree(repo,head,'scripts/ctfe-crossover-pilot',('.github/workflows/ci.yml',))
    return checksums(repo,fields)

if __name__ == '__main__':
    opts=argparse.ArgumentParser(description=__doc__)
    opts.add_argument('repo',type=Path); opts.add_argument('head')
    args=opts.parse_args()
    print(pilot(args.repo.resolve(),args.head))
