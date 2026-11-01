"""Exercise the independent routes, paired thresholds."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import read
import run


def check_single():
    phases = []
    with TemporaryDirectory() as d, patch.object(run.p, 'OUT', Path(d)), \
         patch.object(run.p.subjects, 'activate', return_value={}) as activate, \
         patch.object(run.p.b, 'fresh_outputs') as fresh, patch.object(run.p.routes, 'begin') as begin, \
         patch.object(run.p, 'visit') as visit:
        def record(arm, lane, route, phase, env, where, refs, issues, observer):
            assert (arm, lane, route, env, where.parent.name, where.name, observer) == \
                   ('Con', 'measured', 'single', {}, 'measured-single-Con', phase, None)
            phases.append(phase)
            return {'phase': phase}
        visit.side_effect = record
        result = run.single_checkout('Con', {}, {}, [])
        assert list(result) == phases == list(read.SINGLE)
        fresh.assert_called_once_with()
        begin.assert_called_once_with(run.p.kit.TREE, run.p.kit.REVS, run.p.kit.NAMES)
        activate.assert_called_once()


def check_thresholds():
    def evaluate(counts):
        return read.assess([{'repair_instructions': {'single': {'Eon': 100, 'Con': n}}} for n in counts], 'single')

    assert evaluate([110, 200]) == 'at_least_ten_percent_more_on_both'
    assert evaluate([105, 49]) == 'at_most_five_percent_more_on_both'
    assert evaluate([120, 105]) == evaluate([106, 109]) == 'inconclusive'
    for absent in ([], [0, 250], [100]):
        try:
            evaluate(absent)
        except (ValueError, RuntimeError):
            continue
        raise AssertionError('unpaired or empty clock accepted')
    assert tuple(run.p.FULL) == ('Y-B', 'X-A', 'X-B', 'comment', 'unchanged', 'invalid', 'repair')
    assert set(run.OLD_BOOTS) == read.REJECTED and len(read.REJECTED) == 4
    assert tuple(run.p.ORDERS['01']) == tuple(reversed(run.p.ORDERS['02']))


if __name__ == '__main__':
    check_single()
    check_thresholds()
    print('Independent five-command repair path and paired decision boundaries passed.')
