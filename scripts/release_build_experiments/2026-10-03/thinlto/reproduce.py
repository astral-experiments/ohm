#!/usr/bin/env python3
"""Run the recorded experiment with a complete candidate toolchain and clean pinned checkouts."""
import argparse
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import bench

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace',type=Path,required=True,help='Contains clean uv and ruff worktrees at the recorded pins')
parser.add_argument('--toolchain',type=Path,required=True,help='Complete candidate sysroot containing rustc and pinned Ohm Cargo')
parser.add_argument('--targets',type=Path,required=True,help='Empty isolated target root owned by this reproduction')
parser.add_argument('--output',type=Path,required=True,help='Empty output directory')
parser.add_argument('--runtime',action='store_true',help='Also run runtime guards; requires the pinned CPython corpus under workspace/corpus')
args=parser.parse_args()
for repo,(pin,_) in bench.CONFIG.items():
    checkout=args.workspace/repo
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout,text=True).strip()==pin
    assert not subprocess.check_output(['git','status','--porcelain'],cwd=checkout,text=True).strip(),checkout
for path in [args.targets,args.output]:
    assert not path.exists() or not any(path.iterdir()),f'{path} must be empty'
    path.mkdir(parents=True,exist_ok=True)
assert (args.toolchain/'bin/rustc').exists()
assert (args.toolchain/'bin/cargo').exists()
bench.ROOT=args.workspace.resolve()
bench.OUT=args.output.resolve()
bench.BOOT=args.toolchain.resolve()
rustup=Path(shutil.which('rustup')).resolve()
bench.SHIMS=Path(shutil.which('cargo')).parent
subprocess.run([str(rustup),'toolchain','link','ohm',str(bench.BOOT)],env=os.environ|{'RUSTUP_HOME':str(bench.ROOT/'rustup')},check=True)
original_environment=bench.environment

def environment(repo,variant):
    env=original_environment(repo,variant)
    env['CARGO_TARGET_DIR']=str(args.targets.resolve()/repo/variant)
    return env

bench.environment=environment
for repo in ['uv','ruff']:
    sys.argv=['bench.py',repo]
    bench.main()
runpy.run_path(str(Path(__file__).with_name('library-bench.py')),run_name='__main__')
if args.runtime:
    runpy.run_path(str(Path(__file__).with_name('runtime-bench.py')),run_name='__main__')

