"""Audit the released private-target layout without counting shared registry artifacts."""
import os
from pathlib import Path


def private_inode_audit(mount, label):
    seen = {}
    duplicates = []
    namespaces = set()
    count = 0
    root = mount / 'targets'
    if label == 'ohm':
        assert not (mount / 'shared-build/debug/build/workspaces').exists(), 'Private workspace state escaped to the shared cache'
    for parent, dirs, files in os.walk(root, followlinks=False):
        relative = Path(parent).relative_to(root).parts
        if not relative:
            continue
        owner = relative[0]
        namespaces.add('target/' + owner)
        if 'workspaces' in relative:
            index = relative.index('workspaces')
            if len(relative) > index + 1:
                namespaces.add('workspace/' + owner + '/' + relative[index + 1])
        for name in files:
            path = Path(parent) / name
            if path.is_symlink():
                continue
            stat = path.stat()
            count += 1
            previous = seen.setdefault((stat.st_dev, stat.st_ino), (owner, str(path)))
            if previous[0] != owner:
                duplicates.append([previous[1], str(path)])
    if duplicates:
        raise RuntimeError('Workspace targets share private inodes: ' + repr(duplicates[:5]))
    return {'namespaces': sorted(namespaces), 'files_inspected': count, 'cross_workspace_shared_inodes': duplicates}


def binary_scope(target, binary):
    """Require an executable to belong to its recipient target tree."""
    number = target.name
    assert binary.resolve().is_relative_to(target.resolve()), (target, binary)
    if binary.parent == target / 'debug/deps':
        return 'target/' + number
    parts = binary.relative_to(target / 'debug/build/workspaces').parts
    assert len(parts) == 6 and parts[2] == 'uv' and parts[4] == 'out', parts
    return 'workspace/' + number + '/' + parts[0]
