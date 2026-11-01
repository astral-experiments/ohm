"""Run ordinary full CLI histories without interposing on their process lifecycle."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ctfe-crossover-pilot'))
import pilot as p

BRANCH = 'refs/heads/charlie/qa-ctfe-repair-scope-20261101'
OLD_BOOTS = {'4f4d4a31-68c1-447b-9909-8f4c951d6d82', 'c9fb2eab-3d98-4154-b864-cfac6df82005',
             '61149494-93be-4462-8cec-12fa66623bc7', '364da3c4-7589-4095-b2e6-efeddb2cf64f'}


def single_checkout(arm, rows, refs, issues):
    """Build, edit, break and repair one B checkout with independently empty Cargo roots."""
    where = p.OUT / ('measured-single-' + arm)
    where.mkdir()
    env = p.subjects.activate(arm, rows, where)
    p.b.fresh_outputs()
    p.routes.begin(p.kit.TREE, p.kit.REVS, p.kit.NAMES)
    visits = {}
    for phase in ('Y-B', 'comment', 'unchanged', 'invalid', 'repair'):
        visits[phase] = p.visit(arm, 'measured', 'single', phase, env, where / phase, refs, issues, None)
    return visits


def enrolled():
    env = os.environ
    p.need(env['GITHUB_REPOSITORY'] == p.b.REPO and env['GITHUB_REF'] == BRANCH
           and env['GITHUB_RUN_ATTEMPT'] == '1' and env['GITHUB_SHA'] == env['REVIEWED_HEAD']
           and p.b.git(HERE, 'rev-parse', 'HEAD') == env['REVIEWED_HEAD'], 'wrong screen enrollment')
    p.need(p.ROOT.resolve() == p.ROOT and (p.WORK / '.owned-by-packed-study').read_text() == str(p.ROOT),
           'unowned output directory')


def measure(position, calibrator, observers):
    p.need(position in p.ORDERS and shutil.disk_usage(p.OUT).free > 20 * 2**30, 'position or capacity')
    subprocess.run([sys.executable, '-IB', p.HERE.parent / 'branch-return-pmu/meter.py', calibrator, observers], check=True)
    meter = json.loads((p.OUT / 'meter-ready.json').read_bytes())
    os.sched_setaffinity(0, meter['affinity'])
    p.need(len(meter['affinity']) == 8 and sorted(os.sched_getaffinity(0)) == meter['affinity']
           and meter['boot'] not in OLD_BOOTS, 'reused boot or changed affinity')
    order = p.ORDERS[position]
    p.save(p.OUT / 'position.json', dict(position=position, boot=meter['boot'], order=order,
           run=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], plan=p.sha(HERE / 'PLAN.md'),
           prior=p.sha(p.HERE / 'PLAN.md'), command=p.original.CARGO))
    rows = {r: json.loads((p.OUT / 'sdk' / (r + '.json')).read_bytes())['files'] for r in ('E', 'C')}
    start = p.OUT / 'initial'
    start.mkdir()
    env = p.subjects.activate(order[0], rows, start)
    p.b.fresh_outputs()
    p.b.prepare_inputs(p.kit, env)
    subprocess.run([sys.executable, '-IB', p.HERE / 'test_routes.py', p.kit.TREE], check=True)
    p.original.historical.calibration()
    refs, issues, repairs = {}, [], {'return': {}, 'single': {}}
    for arm in order:
        p.history(arm, 'clean', 'reference', rows, refs, issues, None)
    p.cross_role(refs, issues)
    for arm in order:
        visits = p.history(arm, 'measured', 'return', rows, refs, issues, None)
        repairs['return'][arm] = visits['repair']['instructions']
    for arm in order:
        visits = single_checkout(arm, rows, refs, issues)
        repairs['single'][arm] = visits['repair']['instructions']
    p.save(p.OUT / 'screen.json', dict(repairs=repairs, issues=issues, process_counts='unobserved'))
    p.need(not issues, 'native comparison refused; see screen.json')


if __name__ == '__main__':
    try:
        enrolled()
        if sys.argv[1] == 'acquire':
            p.subjects.acquire(Path(sys.argv[2]))
        else:
            measure(sys.argv[1], *map(Path, sys.argv[2:]))
    except BaseException:
        if p.OUT.is_dir():
            (p.OUT / 'failure.txt').write_text(traceback.format_exc())
        raise
