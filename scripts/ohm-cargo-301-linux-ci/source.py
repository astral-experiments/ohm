"""Materialize and verify the exact Cargo PR head before one upstream Linux CI job."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys


HEAD = 'c18e91b514b2c4e4966c9ab03232c804af3e1b57'
PARENT = '735e1528ed741015c57676dccf05dbdc0ff7bed1'
TREE = 'bf643fa158734642bfee4a2aa8eff4d98bd8a09c'
WORKFLOW = '616691a60b4f0865afc8478d7276016f938b53af431252738b9542fce494003b'
INVENTORY = '8ade5307b84bf5b3bb02f5a85095a778e256b21759b6e57487a59e7e022cba3b'
SCRIPTS = Path(__file__).resolve().parent.parent


def materialize(subject):
    base = runpy.run_path(str(SCRIPTS / 'ohm-apple-zmij/receipt_cargo.py'))
    parent = base['materialize'](subject)
    assert parent['commit'] == PARENT
    transport = runpy.run_path(str(SCRIPTS / 'ohm-aarch64-versioned/transport.py'))
    child = transport['apply']('cargo', subject)
    assert (child['parent'], child['source'], child['tree']) == (PARENT, HEAD, TREE)

    def git(*args):
        return subprocess.check_output(['git', '-C', str(subject), *args])

    git('checkout', '--quiet', '--detach', HEAD)
    assert git('rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines() == [HEAD, TREE]
    assert git('status', '--porcelain=v1') == b''
    git('fsck', '--full', '--strict', '--no-progress')
    assert hashlib.sha256((subject / '.github/workflows/ci.yml').read_bytes()).hexdigest() == WORKFLOW

    inventory = hashlib.sha256()
    rows = git('ls-tree', '-rz', '--full-tree', 'HEAD').split(b'\0')[:-1]
    assert len(rows) == 3114
    for row in rows:
        info, name = row.split(b'\t', 1)
        mode, kind, blob = info.split()
        assert kind == b'blob'
        path = subject / os.fsdecode(name)
        st = path.lstat()
        if mode == b'120000':
            assert stat.S_ISLNK(st.st_mode)
            data = os.fsencode(os.readlink(path))
        else:
            assert stat.S_ISREG(st.st_mode) and mode in (b'100644', b'100755')
            assert bool(st.st_mode & 0o111) == (mode == b'100755')
            data = path.read_bytes()
        assert hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest().encode() == blob, name
        inventory.update(mode + b' ' + hashlib.sha256(data).hexdigest().encode() + b'\t' + name + b'\0')
    assert inventory.hexdigest() == INVENTORY
    return {'source': HEAD, 'tree': TREE, 'parent': PARENT, 'entries': len(rows),
            'mode_path_sha256_inventory': inventory.hexdigest(), 'upstream_ci_sha256': WORKFLOW,
            'namespace_runner_mapping_source': '709b058bb6b7da657ba05895bae5608490294beb'}


if __name__ == '__main__':
    print(json.dumps(materialize(Path(sys.argv[1]).resolve()), sort_keys=True))
