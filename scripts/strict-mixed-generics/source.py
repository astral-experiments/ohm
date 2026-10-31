"""Apply the exact reviewed compiler diff to the signed parent and prove the resulting tree."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'source'
SIGNED = json.loads((SOURCE / 'signed21.json').read_text())
PUBLIC = 'b940084d7eb6a299eb4bfeb8e34901bc051e7ac4'
HEADER = 'compiler/rustc_incremental/src/persist/file_format.rs'


def git(repo, *args, data=None, environ=None):
    return subprocess.check_output(['git', '-C', str(repo), '-c', 'gc.auto=0', *args], input=data, env=environ)


def oid(repo, rev):
    return git(repo, 'rev-parse', rev).decode().strip()


def require(test, message):
    if not test:
        raise RuntimeError(message)


def sha(path):
    with path.open('rb') as fh:
        return hashlib.file_digest(fh, 'sha256').hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def subject(repo, parent, tree):
    """Deterministic QA commit. Its sole parent and tree are part of the receipt."""
    identity = 'Ohm QA <qa@example.invalid> 1793400000 +0000'
    raw = f'tree {tree}\nparent {parent}\nauthor {identity}\ncommitter {identity}\n\nApply the frozen mixed-profile patch to signed Rust -21\n'.encode()
    return git(repo, 'hash-object', '-t', 'commit', '-w', '--stdin', data=raw).decode().strip()


def register(product, scratch, child):
    parent = SIGNED['product_parent']
    signed = SIGNED['signed_rust']
    require(oid(product, 'HEAD') == child and git(product, 'merge-base', parent, child).decode().strip() == parent, 'unexpected feature commit or base')
    require(not git(product, 'status', '--porcelain=v1', '--untracked-files=normal'), 'feature checkout is dirty')
    names = git(product, 'diff', '--name-only', '-z', parent, child).decode().rstrip('\0').split('\0')
    fixture = 'tests/run-make/ohm-profile-aware-shared-generics/'
    require(len(names) == len(set(names)) and all(p.startswith(('compiler/', fixture)) for p in names), 'unexpected source files')
    require(any(p.startswith('compiler/') for p in names) and fixture + 'rmake.rs' in names, 'missing source or regression')
    feature_patch = git(product, 'diff', '--binary', '--full-index', '--no-ext-diff', parent, child)
    # The only divergent hunk is the already advanced incremental-format guard (4 on #251, 8 on signed -21).
    # All other feature hunks must apply without any conflict handling. Both header files must become identical.
    other_patch = git(product, 'diff', '--binary', '--full-index', '--no-ext-diff', parent, child, '--', '.', ':(exclude)' + HEADER)
    headers = {r: git(repo, 'show', r + ':' + HEADER) for r, repo in [(parent,product),(child,product),(signed,scratch)]}
    import re
    line = rb'// [^\n]+\nconst HEADER_FORMAT_VERSION: u16 = ([0-9]+);'
    matches = {r:re.search(line,b) for r,b in headers.items()}
    require(all(matches.values()) and [matches[r].group(1) for r in (parent,signed,child)] == [b'4',b'8',b'9'], 'unexpected incremental format generation')
    require(all(re.sub(line,matches[child].group(),b,count=1) == headers[child] for b in headers.values()), 'unregistered changes in incremental file header')
    header_patch = git(scratch,'diff','--binary','--full-index',signed,child,'--',HEADER)
    proofs = {}
    for name in names:
        proofs[name] = {key: git(repo, 'ls-tree', rev, '--', name).decode().strip() for key, repo, rev in [('pr_base', product, parent), ('pr_head', product, child), ('signed_base', scratch, signed)]}
    with tempfile.TemporaryDirectory() as temp:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(temp) / 'index')}
        git(scratch, 'read-tree', signed, environ=env)
        for patch in [other_patch,header_patch]:
            git(scratch, 'apply', '--cached', '--check', '--binary', '--whitespace=error', '-', environ=env, data=patch)
            git(scratch, 'apply', '--cached', '--binary', '--whitespace=error', '-', environ=env, data=patch)
        tree = git(scratch, 'write-tree', environ=env).decode().strip()
    port = subject(scratch, signed, tree)
    patch = git(scratch,'diff','--binary','--full-index',signed,port)
    for name, value in proofs.items():
        value['signed_patched'] = git(scratch, 'ls-tree', port, '--', name).decode().strip()
    data = {'feature_parent': parent, 'feature': child, 'signed_parent': signed, 'port': port, 'tree': tree,
            'patch_sha256': hashlib.sha256(patch).hexdigest(), 'feature_patch_sha256':hashlib.sha256(feature_patch).hexdigest(),
            'incremental_header':{'feature_parent':4,'signed_parent':8,'feature_and_signed_after':9,'same_final_blob':oid(scratch,port+':'+HEADER)},'files': proofs,
            'subtrees': {p: oid(scratch, port + ':' + p) for p in ['compiler', 'library', 'src/bootstrap', 'tests']}}
    (SOURCE / 'product.patch.gz').write_bytes(gzip.compress(patch, mtime=0))
    (SOURCE / 'feature.patch.gz').write_bytes(gzip.compress(feature_patch, mtime=0))
    fixture_copy = SOURCE / 'fixture'; fixture_copy.mkdir(exist_ok=True)
    for name in ('shared.rs', 'provider.rs', 'consumer.rs'):
        (fixture_copy / name).write_bytes(git(product, 'show', child + ':' + fixture + name))
    write_json(SOURCE / 'product.json', data)


def materialize(repo, role):
    require(not git(repo, 'status', '--porcelain=v1', '--ignore-submodules=none'), 'dirty initial checkout')
    require(oid(repo, SIGNED['prerequisite']) == SIGNED['prerequisite'], 'missing previous transport')
    pack = SOURCE / 'signed21.pack'
    require(sha(pack) == SIGNED['transport_sha256'] and pack.stat().st_size == SIGNED['bytes'], 'incorrect signed source pack')
    git(repo, 'index-pack', '--stdin', data=pack.read_bytes())
    signed = SIGNED['signed_rust']
    for suffix, field in [('^{tree}', 'signed_tree'), (':compiler', 'compiler_tree'), (':library', 'library_tree'), (':src/bootstrap', 'bootstrap_tree'), (':src/stage0', 'stage0_blob')]:
        require(oid(repo, signed + suffix) == SIGNED[field], field)
    git(repo, 'checkout', '--quiet', '--detach', signed)
    if role == 'legacy':
        legacy = json.loads((SOURCE / 'legacy220.json').read_text())
        transport = SOURCE / 'legacy220.pack'
        require(sha(transport) == legacy['sha256'] and transport.stat().st_size == legacy['bytes'], 'incorrect pre-epoch source pack')
        require(oid(repo, legacy['prerequisite']) == legacy['prerequisite'], 'missing pre-epoch history')
        git(repo, 'index-pack', '--stdin', data=transport.read_bytes())
        git(repo, 'checkout', '--quiet', '--detach', legacy['commit'])
        require(oid(repo, 'HEAD^{tree}') == legacy['tree'], 'pre-epoch tree changed')
    if role == 'candidate':
        recorded = json.loads((SOURCE / 'product.json').read_text())
        patch = gzip.decompress((SOURCE / 'product.patch.gz').read_bytes())
        require(hashlib.sha256(patch).hexdigest() == recorded['patch_sha256'] and recorded['signed_parent'] == signed, 'source patch changed')
        git(repo, 'apply', '--index', '--check', '--binary', '--whitespace=error', '-', data=patch)
        git(repo, 'apply', '--index', '--binary', '--whitespace=error', '-', data=patch)
        tree = git(repo, 'write-tree').decode().strip()
        require(tree == recorded['tree'], 'independent application changed tree')
        rev = subject(repo, signed, tree)
        require(rev == recorded['port'], 'independent application changed commit')
        git(repo, 'checkout', '--quiet', '--detach', rev)
    require(not git(repo, 'status', '--porcelain=v1', '--ignore-submodules=none'), 'dirty final source')
    print(role, oid(repo, 'HEAD'), oid(repo, 'HEAD^{tree}'))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    r = sub.add_parser('register'); r.add_argument('product', type=Path); r.add_argument('scratch', type=Path); r.add_argument('child')
    m = sub.add_parser('materialize'); m.add_argument('repo', type=Path); m.add_argument('role', choices=['parent', 'candidate', 'legacy'])
    args = p.parse_args()
    if args.action == 'register': register(args.product, args.scratch, args.child)
    else: materialize(args.repo, args.role)
