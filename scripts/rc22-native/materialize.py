"""Restore the two previous same-repository source kits and their small exact Git overlays."""
import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import *

def apply(repo,kind):
    m=read(HERE/'source'/(kind+'.json'));pack=HERE/'source'/(kind+'.pack')
    require(m['sha256']==sha(pack) and m['bytes']==pack.stat().st_size,'overlay digest')
    require(git(repo,'rev-parse','HEAD')==m['base'],'wrong existing donor')
    with pack.open('rb') as f:subprocess.run(['git','-C',repo,'index-pack','--strict','--stdin'],stdin=f,check=True)
    for rev,tree in m['tips'].items():
        require(git(repo,'rev-parse',rev+'^{tree}')==tree,('tree',rev))
        subprocess.run(['git','-C',repo,'merge-base','--is-ancestor',m['base'],rev],check=True)
    return m

def source(root):
    root.mkdir(exist_ok=True);repo=root/'rust'
    old=seed('public-seed')/'scripts/ohm-apple-zmij/source-transport'
    subprocess.run([sys.executable,'-IB',old/'prepare.py',repo],check=True)
    signed=seed('signed-rust')/'scripts/strict-mixed-generics/source.py'
    subprocess.run([sys.executable,'-IB',signed,'materialize',repo,'parent'],check=True)
    base=apply(repo,'rust');git(repo,'checkout','--detach','-q',RUST)
    expected={'compiler':'fe04efe2bcbf28820e9c3361d62b299d273e9a24','library':'4f7a8f755164dc68fff80790db8a844ae030fd03',
              'tests':'76f8c0ecd0eed35042848dfa7036dc546bd1ad6f','src/bootstrap':'1dcf3e6b142ba5c132f7a2370dffa6ba090b15e1','src/tools/cargo':ROLES['pinned'][0]}
    require(git(repo,'rev-parse','HEAD^{tree}')==RTREE and not git(repo,'status','--porcelain','--ignore-submodules=none'),'incorrect Rust checkout')
    for path,oid in expected.items():require(git(repo,'rev-parse','HEAD:'+path)==oid,path)
    cargo(root)
    save(root/'reports/rust-source.json',{'commit':RUST,'tree':RTREE,'subtrees':expected,'overlay':base,'source_seed':SEEDS['signed-rust']})

def cargo(root):
    ci=seed('cargo-seed')/'scripts'
    spec=importlib.util.spec_from_file_location('signed_cargo_source',ci/'cargo-diagnostic-fix/materialize.py');old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    repo=root/'cargo-source'
    parent=old.tree(repo,ci/'ohm-apple-zmij/cargo293/source.pack')
    require(parent['mode_path_sha256_inventory']=='da5d8cde02be6fcd82b87b490b937224dcd46f8e72841343d9fe00ce16d253d1','Cargo seed inventory')
    overlay=apply(repo,'cargo');roles={}
    for role,(rev,tree) in ROLES.items():
        git(repo,'checkout','--detach','-q',rev)
        require(not git(repo,'status','--porcelain') and git(repo,'rev-parse','HEAD^{tree}')==tree,role)
        roles[role]={'commit':rev,'tree':tree,'lock_sha256':sha(repo/'Cargo.lock'),**old.hash_files(repo,rev)}
    require(git(repo,'rev-parse',ROLES['fourfix'][0]+'^1')=='010b760433999227e39a26b3d86e0db2f9bc2375' and git(repo,'rev-parse',ROLES['fourfix'][0]+'^2')=='8269d772aa1ef02e5efaa331dfb40eb55d71f719','incorrect merge')
    require(set(git(repo,'diff','--name-only',ROLES['fourfix'][0]+'^1',ROLES['fourfix'][0]).splitlines())=={'src/compiler/fingerprint/dep_info.rs','src/compiler/fingerprint/mod.rs','tests/testsuite/freshness.rs'},'unexpected fourth fix')
    save(root/'reports/cargo-source.json',{'base':parent,'overlay':overlay,'roles':roles,'source_seed':SEEDS['cargo-seed']})
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('root',type=Path);ns=a.parse_args();source(ns.root.resolve())
