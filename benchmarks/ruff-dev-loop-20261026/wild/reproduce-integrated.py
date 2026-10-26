#!/usr/bin/env python3
"""Reproduce the mixed whole-command comparison directly from a new native dependency snapshot."""
import argparse
import fcntl
import importlib.util
import os
from pathlib import Path
import shutil

p=Path(__file__).with_name('mixed-holdout.py');spec=importlib.util.spec_from_file_location('mixed',p)
mixed=importlib.util.module_from_spec(spec);spec.loader.exec_module(mixed)
dr=mixed.dr;n=mixed.n


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['bootstrap','measure']);ap.add_argument('mode',choices=['build','test'])
    for k in ('ruff','spec','state','output'):ap.add_argument(k,type=Path)
    ap.add_argument('--drrun',type=Path,required=True);ap.add_argument('--pidcounter',type=Path,required=True)
    args=ap.parse_args();args.style='prebuilt';dr.RUN=args.drrun.resolve(strict=True);dr.CLIENT=args.pidcounter.resolve(strict=True)
    s=mixed.Study(args)
    with (s.state.parent/(s.state.name+'.lock')).open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if args.action=='measure':
                s.measure();return
            # The mixed runner instruments only full observations. Every warmup in
            # freeze therefore runs native, so no rejected counter namespace exists.
            s.freeze();s.restore();shim=s.state/'dr-dispatch';(shim/'bin').mkdir(parents=True)
            for path in (s.runtime/'bin').iterdir():
                if path.name!='cargo':(shim/'bin'/path.name).symlink_to(path)
            (shim/'lib').symlink_to(s.runtime/'lib')
            cargo=shim/'bin/cargo';cargo.write_text(dr.bash_dispatch('cargo',s.runtime/'bin/cargo'));cargo.chmod(0o755)
            entry=s.rustup/'toolchains/ohm';assert entry.resolve()==s.runtime.resolve()
            tmp=entry.with_name('ohm.new');tmp.symlink_to(shim);tmp.replace(entry)
            wild=s.state/'wild-dispatch';wild.write_text(dr.bash_dispatch('ld.bfd',s.linker));wild.chmod(0o755)
            s.clang.write_text(dr.bash_dispatch('clang',Path(shutil.which('clang')),['--ld-path='+str(wild),'-Wl,--no-fork']));s.clang.chmod(0o755)
            s.setup_and_audit()
        finally:s.restore()

if __name__=='__main__':main()
