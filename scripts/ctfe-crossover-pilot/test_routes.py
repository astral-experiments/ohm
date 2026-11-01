"""Exercise both ordinary histories against authentic, read-only Git source objects."""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import routes

A = 'b5dba861cc38e3f7fb4524c9ceba3e01a474ea13'
B = '7b13f01ba1569887a25670820764b24c206da8e5'
REVS = {'A': A, 'B': B}
TREES = {'A': '2b61306d708a211b3725c8d920e7590be6da41ad', 'B': '97ca36909f1ae8fa028b2c1f48f452fbdcdbbd4c'}
NAMES = {'A': 'historical-parent', 'B': 'historical-feature'}


def exercise(original):
    common = Path(routes.git(original, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip())
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        subprocess.run(['git', 'init', '-q', '--template=', repo], check=True)
        (repo / '.git/objects/info/alternates').write_text(str(common / 'objects') + '\n')
        if (common / 'shallow').is_file():
            (repo / '.git/shallow').write_bytes((common / 'shallow').read_bytes())
        routes.git(repo, 'config', 'core.sparseCheckout', 'true')
        (repo / '.git/info').mkdir(exist_ok=True)
        (repo / '.git/info/sparse-checkout').write_text('/' + routes.NODES + '\n/' + routes.PARSER + '\n/' + routes.behavior.cases.AST + '\n')
        routes.git(repo, 'branch', NAMES['A'], A)
        routes.git(repo, 'branch', NAMES['B'], B)
        routes.git(repo, 'switch', '--quiet', NAMES['B'])
        phases = ('Y-B', 'X-A', 'X-B', 'comment', 'unchanged')
        for history, steps in [('return', (*phases, 'invalid', 'repair')), ('stay', phases), ('dirty', phases)]:
            routes.begin(repo, REVS, NAMES)
            seen = {}
            for phase in steps:
                routes.advance(repo, NAMES, phase, history)
                seen[phase] = routes.snapshot(repo, REVS, TREES, NAMES, phase, history)
            routes.require(seen['comment'] == seen['unchanged'], 'unchanged probe mutated Git input')
            routes.require(seen['X-B']['ref'] == NAMES['A'] and seen['X-B']['revision'] == B,
                           'did not fast-forward the real parent')
        for phase in ('clean-A', 'clean-B', 'clean-edited', 'clean-semantic'):
            routes.begin(repo, REVS, NAMES)
            routes.advance(repo, NAMES, phase, 'reference')
            routes.snapshot(repo, REVS, TREES, NAMES, phase, 'reference')
        (repo / routes.NODES).write_bytes(b'unexpected source')
        try:
            routes.begin(repo, REVS, NAMES)
        except ValueError:
            routes.require((repo / routes.NODES).read_bytes() == b'unexpected source', 'overwrote unknown edit')
        else:
            raise AssertionError('accepted unrelated source edit')


if __name__ == '__main__':
    exercise(Path(sys.argv[1]))
