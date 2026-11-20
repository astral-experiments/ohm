"""Count two full-package Codex edit commands from a pinned source checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

KIT = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def blob(path):
    data = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def run(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def verify(workspace, edit, phase):
    for name, hashes in edit['files'].items():
        if blob(workspace / name) != hashes[phase]:
            raise ValueError(f'{phase}: unexpected Git blob for {name}')


def apply(workspace, edit, forward=True):
    patch = KIT / edit['patch']
    if sha(patch) != edit['patch_sha256']:
        raise ValueError('diff hash mismatch: ' + str(patch))
    if forward:
        verify(workspace, edit, 'before')
        run('git', 'apply', patch, cwd=workspace)
        verify(workspace, edit, 'after')
    else:
        verify(workspace, edit, 'after')
        run('git', 'apply', '--reverse', patch, cwd=workspace)
        verify(workspace, edit, 'before')


def checkout(codex, path, history):
    # Local read-only object access. The scratch repository owns every checkout operation.
    repo = subprocess.check_output(['git', '-C', codex, 'rev-parse',
                                    '--path-format=absolute', '--git-common-dir']).decode().strip()
    run('git', 'init', '--quiet', path)
    alternates = path / '.git/objects/info/alternates'
    alternates.write_text(str(Path(repo) / 'objects') + '\n')
    run('git', '-c', 'core.autocrlf=false', 'checkout', '--quiet', '--detach',
        history['working_tree'], cwd=path)
    for edit in history['edits']:
        verify(path, edit, 'checkout')
        if all(v['checkout'] == v['after'] for v in edit['files'].values()):
            apply(path, edit, forward=False)
        verify(path, edit, 'before')


def compatibility(root):
    meta = read(KIT / 'compat/manifest.json')
    archive = KIT / 'compat/allocative-0.3.6.crate'
    delta = KIT / 'compat/allocative.patch'
    assert sha(archive) == meta['allocative_crate_sha256']
    assert sha(delta) == meta['diff_sha256']
    with tarfile.open(archive) as package:
        package.extractall(root, filter='data')
    local = root / 'allocative-0.3.6'
    run('patch', '--batch', '--silent', '-p1', '-i', delta, cwd=local)
    for path, digest in meta['allocative_updated_files'].items():
        assert sha(local/path) == digest
    config = root/'.cargo/config.toml'
    config.parent.mkdir()
    config.write_text('paths = ' + json.dumps([str(local)]) + '\n')



