"""Replay the two Ruff branches in a disposable, authenticated study checkout."""

import behavior
import hashlib
import subprocess
from pathlib import Path

NODES = 'crates/ruff_python_ast/src/nodes.rs'
PARSER = 'crates/ruff_python_parser/src/lib.rs'
BEFORE = '299c122da4caf5214b15cb4d36dba18ca7855beb31ea50f9050d9a0cc816275c'
AFTER = 'dbda1ba0b8c4a8ae98c62da763c9128260db17fc0c3911e2a377073a5284e937'
INVALID = b'\nconst ohm_branch_switch_invalid: () = 1u32;\n'


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '--no-optional-locks', '-C', repo, *args])


def edit_comment(file):
    source = file.read_bytes()
    updated = source.replace(b'dead code warning', b'dead-code warning')
    require(sha(source) == BEFORE and sha(updated) == AFTER, 'different historical Ruff comment')
    file.write_bytes(updated)


def begin(repo, revs, names):
    """Reset only the known private comment between independent empty histories."""
    changed = [p.decode() for p in git(repo, 'diff', '--name-only', '-z').split(b'\0') if p]
    allowed = {NODES: AFTER, behavior.cases.AST: behavior.cases.AFTER}
    require(all(p in allowed and sha((repo/p).read_bytes())==allowed[p] for p in changed), 'unexpected prior edit')
    if changed:
        git(repo, 'restore', '--worktree', '--', *changed)
    require(not git(repo, 'status', '--porcelain'), 'unclean owned source')
    git(repo, 'switch', '--quiet', names['B'])
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == revs['B'], 'Y changed')
    git(repo, 'branch', '--force', names['A'], revs['A'])


def advance(repo, names, phase, lineage):
    if phase in ('clean-A', 'X-A'):
        git(repo, 'switch', '--quiet', names['A'])
    elif phase == 'X-B':
        git(repo, 'merge', '--ff-only', '--no-edit', names['B'])
        if lineage == 'dirty':
            f=repo/behavior.cases.AST
            f.write_bytes(behavior.cases.altered(f.read_bytes()))
    elif phase in ('comment', 'clean-edited'):
        if phase == 'comment' and lineage in ('return','dirty'):
            if lineage == 'dirty':
                f=repo/behavior.cases.AST
                require(sha(f.read_bytes())==behavior.cases.AFTER, 'lost the changed donor source')
                git(repo, 'restore', '--worktree', '--', behavior.cases.AST)
            git(repo, 'switch', '--quiet', names['B'])
        edit_comment(repo / NODES)
    elif phase == 'clean-semantic':
        f=repo/behavior.cases.AST
        f.write_bytes(behavior.cases.altered(f.read_bytes()))
    elif phase == 'invalid':
        parser = repo / PARSER
        body = parser.read_bytes()
        require(body == git(repo, 'show', 'HEAD:' + PARSER), 'different parser before diagnostic')
        parser.write_bytes(body + INVALID)
    elif phase == 'repair':
        require((repo / PARSER).read_bytes() == git(repo, 'show', 'HEAD:' + PARSER) + INVALID,
                'different invalid source')
        git(repo, 'restore', '--worktree', '--', PARSER)
    else:
        require(phase in ('clean-B', 'Y-B', 'unchanged'), 'unknown history phase')


def snapshot(repo, revs, trees, names, phase, lineage):
    branch = 'A' if phase in ('clean-A', 'X-A') else 'B'
    ref = names['A'] if (branch == 'A' or phase == 'X-B' or
                          lineage == 'stay' and phase in ('comment', 'unchanged')) else names['B']
    changed = [NODES] if phase in ('clean-edited', 'comment', 'unchanged', 'invalid', 'repair') else []
    semantic = phase == 'clean-semantic' or lineage == 'dirty' and phase == 'X-B'
    lib = (repo/behavior.cases.AST).read_bytes()
    if semantic:
        changed.append(behavior.cases.AST)
    expected = git(repo,'show','HEAD:'+behavior.cases.AST)
    require(lib == (behavior.cases.altered(expected) if semantic else expected), 'wrong private function body')
    if phase == 'invalid':
        changed.append(PARSER)
    require(git(repo, 'rev-parse', 'HEAD').decode().strip() == revs[branch]
            and git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip() == trees[branch]
            and git(repo, 'symbolic-ref', '--short', 'HEAD').decode().strip() == ref,
            ('wrong Git history', phase, ref))
    expected_status = ''.join(' M ' + path + '\n' for path in sorted(changed)).encode()
    require(git(repo, 'status', '--porcelain=v1') == expected_status, ('unexpected tracked state', phase))
    nodes = sha((repo / NODES).read_bytes())
    if branch == 'B':
        require(nodes == (AFTER if NODES in changed else BEFORE), 'wrong private edit')
    parser = (repo / PARSER).read_bytes()
    require(parser == git(repo, 'show', 'HEAD:' + PARSER) + (INVALID if phase == 'invalid' else b''),
            'wrong parser bytes')
    head = 'refs/heads/' + ref
    watched = {}
    for name in ('HEAD', head):
        path = Path(repo, '.git', name)
        s = path.lstat()
        require(path.is_file() and not path.is_symlink(), 'missing Ruff build-script input')
        watched[name] = [s.st_dev, s.st_ino, s.st_ctime_ns, s.st_mtime_ns, sha(path.read_bytes())]
    return dict(branch=branch, ref=ref, revision=revs[branch], tree=trees[branch],
                modified=sorted(changed), lib=sha(lib), nodes=nodes, parser=sha(parser), watched=watched)
