"""Reopen both source-only Git packs and the independently transplanted signed tree."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source import SOURCE, SIGNED, git, require


def audit(objects):
    feature = json.loads((SOURCE / 'product.json').read_text())
    previous = json.loads((SOURCE / 'legacy220.json').read_text())
    object_dir = Path(git(objects, 'rev-parse', '--path-format=absolute', '--git-path', 'objects').decode().strip())
    alt = str(object_dir) + (os.pathsep + os.environ['GIT_ALTERNATE_OBJECT_DIRECTORIES'] if os.environ.get('GIT_ALTERNATE_OBJECT_DIRECTORIES') else '')
    env = {**os.environ, 'GIT_NO_LAZY_FETCH':'1', 'GIT_ALTERNATE_OBJECT_DIRECTORIES':alt}
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / 'partner.git'; subprocess.run(['git', 'init', '--bare', '--template=', '-q', dest], check=True)
        inventories = {}
        for name, rev, base, count, digest, size in [('signed21',SIGNED['signed_rust'],SIGNED['prerequisite'],None,SIGNED['transport_sha256'],SIGNED['bytes']),('legacy220',previous['commit'],previous['prerequisite'],previous['changed_objects'],previous['sha256'],previous['bytes'])]:
            data = (SOURCE / (name + '.pack')).read_bytes()
            require(hashlib.sha256(data).hexdigest() == digest and len(data) == size,'damaged ' + name)
            key = git(dest,'index-pack','--stdin',data=data,environ=env).decode().split()[-1]
            index = dest / 'objects/pack' / ('pack-'+key+'.idx')
            contents = git(dest,'verify-pack','-v',index,environ=env).decode().splitlines()
            actual = {a.split()[0] for a in contents if re.match(r'^[0-9a-f]{40} (?:commit|tree|blob|tag)\s',a)}
            expected = {a.split()[0] for a in git(dest,'rev-list','--objects',rev,'^'+base,environ=env).decode().splitlines()}
            require(actual == expected and (count is None or len(expected) == count),name+': source transport is not the exact closure')
            inventories[name] = len(expected)
        patch = gzip.decompress((SOURCE/'product.patch.gz').read_bytes())
        require(hashlib.sha256(patch).hexdigest() == feature['patch_sha256'],'wrong source patch')
        index_env = {**env,'GIT_INDEX_FILE':str(Path(tmp)/'signed.index')}
        git(dest,'read-tree',feature['signed_parent'],environ=index_env)
        git(dest,'apply','--cached','--check','--binary','--whitespace=error','-',data=patch,environ=index_env)
        git(dest,'apply','--cached','--binary','--whitespace=error','-',data=patch,environ=index_env)
        tree = git(dest,'write-tree',environ=index_env).decode().strip(); require(tree == feature['tree'],'changed signed transplantation')
        for name, records in feature['files'].items():
            require(git(dest,'ls-tree',tree,'--',name,environ=env).decode().strip() == records['signed_patched'],name)
        print(json.dumps({'packs':inventories,'files':len(feature['files']),'tree':tree,'patch':feature['patch_sha256']},sort_keys=True))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('rust_git_objects',type=Path);audit(p.parse_args().rust_git_objects)
