"""Compare two physical compilers on the ordinary full Ruff CLI build after a branch return."""

import collections
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'branch-return-pmu'))
import worker as original
from bindings import OUT, ROOT, WORK, need, save, sha
from omission import publish
sys.path.insert(0, str(HERE))
import routes
import registration as reg

kit = original.kit
b = original.b


def component(name):
    # Historical helpers already use the names `subjects` and `trace`.
    spec = importlib.util.spec_from_file_location('ctfe_pilot_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


subjects = component('subjects')
ORDERS = {'01': ('Eon', 'Con'), '02': ('Con', 'Eon')}
REFS = ('clean-A', 'clean-B', 'clean-edited')
PREFIX = ('Y-B', 'X-A', 'X-B', 'comment', 'unchanged')
FULL = (*PREFIX, 'invalid', 'repair')
TRACED = {'return': {'X-B', 'comment', 'unchanged', 'invalid', 'repair'},
          'stay': {'comment', 'unchanged'}}
BRANCH = 'refs/heads/' + reg.BRANCH


def job():
    need(os.environ.get('GITHUB_REPOSITORY') == b.REPO and os.environ.get('GITHUB_REF') == BRANCH
         and os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
         and os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
         and b.git(HERE, 'rev-parse', 'HEAD') == os.environ['GITHUB_SHA'] == os.environ['REVIEWED_HEAD'],
         'different pilot enrollment')
    need(ROOT.resolve() == ROOT and (WORK / '.owned-by-packed-study').read_text() == str(ROOT),
         'unowned output directory')


def product_check(files, products, reference, where, issues):
    need(original.same_products(products, reference), ('native behavior differs from empty', where))
    for name, path in files.items():
        actual = products[name]
        wanted = reference[name]
        if actual['whole'] == wanted['whole']:
            original.native.same_file(path, actual, wanted, original.BODIES, where)
        else:
            original.native.preserve(path, actual, original.BODIES, original.BUNDLE)
            issues.append(dict(visit=str(where.relative_to(OUT)), product=name,
                               actual=actual['whole'], empty=wanted['whole']))


def visit(arm, lane, lineage, phase, env, where, refs, issues, observer):
    where.mkdir()
    need(shutil.disk_usage(WORK).free > 2 * 2**30 and shutil.disk_usage(OUT).free > 5 * 2**30,
         'insufficient space for an ordinary compilation or its original receipts')
    if phase == 'repair':
        old = json.loads((where.parent / 'invalid/failed.json').read_bytes())
        original.failed_session.before_repair(WORK, old, where / 'grace.json')
    routes.advance(kit.TREE, kit.NAMES, phase, lineage)
    source = routes.snapshot(kit.TREE, kit.REVS, kit.TREES, kit.NAMES, phase, lineage)
    save(where / 'source.json', source)
    if phase == 'unchanged':
        need(source == json.loads((where.parent / 'comment/source.json').read_bytes()),
             'a watched source changed before the unchanged call')
    rc = 101 if phase == 'invalid' else 0
    traced = lane == 'structural' and phase in TRACED[lineage]
    if traced:
        messages, instructions, physical = observer.invocation(where, env, rc, arm)
    else:
        capture = 'measured' if lane == 'measured' else 'ordinary'
        messages, instructions, physical = original.invocation(where, env, capture, rc, arm)
    abandoned = original.failed_session.observed(WORK)
    if rc:
        save(where / 'failed.json', abandoned)
    else:
        need(not abandoned, ('unfinished native compile', phase))
    storage = original.disk.allocated(WORK / 'target', WORK / 'build', where, failed_sessions=abandoned)
    need(min(storage['roots'].values()) > 0 and storage['all_inodes'] > 1000, 'incomplete storage census')
    observation = 'kernel' if traced else 'pmu' if lane == 'measured' else 'ordinary'
    result = dict(phase=phase, status=rc, observer=observation, instructions=instructions,
                  allocated=storage['allocated'])
    if physical is not None:
        result['compilers'] = sorted([r['crate'], r['mode']] for r in physical['rustcs'])
        result['links'] = physical['wild']
        if phase == 'comment':
            need(['ruff_python_ast', 'full'] in result['compilers'], 'comment did not compile the AST')
        if phase == 'X-B':
            need(['ruff_python_ast', 'full'] in result['compilers'] and physical['wild'] > 0,
                 'historical source failed to recompile and relink')
    if not rc:
        rows, dirty = original.historical.roster(messages)
        publish(where / 'roster.json.gz', dict(members=rows, dirty=dirty))
        result.update(graph=original.historical.commit(rows), dirty=original.historical.commit(dirty))
        if phase.startswith('clean-') or phase == 'Y-B':
            need(len(dirty) == len(rows) == 375 and storage['packed_files'] == 0,
                 'cold full-CLI build reused retained inputs')
        branch = source['branch']
        products, files = original.native.observed(messages, branch, kit.REVS[branch], env,
                                                   ROOT, kit.TREE, WORK, where)
        ref = phase if phase in REFS else ('clean-edited' if routes.NODES in source['modified']
                                            else 'clean-' + branch)
        if phase in REFS:
            for name, path in files.items():
                original.native.preserve(path, products[name], original.BODIES, original.BUNDLE)
            refs[arm, ref] = (rows, products)
        else:
            wanted_rows, wanted = refs[arm, ref]
            need(rows == wanted_rows, 'different complete target graph')
            product_check(files, products, wanted, where, issues)
        result.update(cli=products['cli']['whole'], reader=products['reader']['whole'])
    save(where / 'visit.json', result)
    print(arm, lane, lineage, phase, result.get('instructions'), flush=True)
    return result


def history(arm, lane, lineage, rows, refs, issues, observer, phases=None):
    where = OUT / (lane + '-' + lineage + '-' + arm)
    where.mkdir()
    env = subjects.activate(arm, rows, where)
    if lane == 'structural':
        observer.catalog(arm, rows, where, env)
    b.fresh_outputs()
    routes.begin(kit.TREE, kit.REVS, kit.NAMES)
    if phases is None:
        phases = REFS if lane == 'clean' else FULL if lineage == 'return' else PREFIX
    results = {}
    for phase in phases:
        if lane == 'clean' and phase != REFS[0]:
            b.fresh_outputs()
            routes.begin(kit.TREE, kit.REVS, kit.NAMES)
        results[phase] = visit(arm, lane, lineage, phase, env, where / phase, refs, issues, observer)
    return results


def cross_role(refs, issues):
    for phase in REFS:
        erows, e = refs['Eon', phase]
        crows, c = refs['Con', phase]
        need(erows == crows and original.same_products(c, e), ('different clean typed or native verdict', phase))
        for name in ('cli', 'reader'):
            if any(e[name][key] != c[name][key] for key in ('loads', 'executable')):
                issues.append(dict(reference=phase, different_executable_bytes=name,
                                   E=e[name]['whole'], C=c[name]['whole']))
    for arm in ORDERS['01']:
        need(refs[arm, 'clean-A'][1]['cli']['whole'] != refs[arm, 'clean-B'][1]['cli']['whole'],
             'the real Ruff history changes the executable')


def finish(position, order, records, issues):
    primary = {}
    for arm in order:
        ordinary = records['measured', 'return', arm]
        trace = records['structural', 'return', arm]
        for phase in FULL:
            for key in ('status', 'graph', 'dirty', 'cli', 'reader'):
                if ordinary[phase].get(key) != trace[phase].get(key):
                    issues.append(dict(arm=arm, phase=phase, structural_disagreement=key))
        primary[arm] = {key: ordinary['comment'][key] for key in ('instructions', 'allocated')}
        primary[arm].update(compilers=trace['comment']['compilers'], links=trace['comment']['links'])
    e, c = (primary[a] for a in ('Eon', 'Con'))
    e_full = collections.Counter(n for n, mode in e['compilers'] if mode == 'full')
    c_full = collections.Counter(n for n, mode in c['compilers'] if mode == 'full')
    ratio = e['instructions'] / c['instructions']
    save(OUT / 'pilot.json', dict(position=position, order=order, primary=primary, ratio=ratio,
                                  skipped_full=dict(e_full - c_full), added_full=dict(c_full - e_full),
                                  candidate_for_confirmation=bool(not issues and ratio >= 2 and e_full > c_full
                                                                  and c['links'] <= e['links']),
                                  qualification_issues=issues))
    need(not issues, 'one or more independent native product gates refused; see pilot.json')


def main(mode, position, calibrator, observers):
    job()
    need(position in reg.jobs(mode) and shutil.disk_usage(OUT).free > 20 * 2**30, 'mode, position or capacity')
    gate = reg.hardware_gate()
    prior = None
    if mode == 'full-pilot':
        prior = json.loads((OUT/'prior-v2-contact.json').read_bytes())
        need(prior['official']['run'] == int(os.environ['CONTACT_RUN']) and
             prior['official']['files'][0]['sha256'] == os.environ['CONTACT_SHA256'] and
             sha(OUT/'prior-v2-contact.json') == os.environ['CONTACT_READBACK_SHA256'] and
             prior['head'] == os.environ['GITHUB_SHA'] and prior['qualified'] is True,
             'missing independently replayed contact on this exact head')
        subprocess.run([sys.executable, '-IB', HERE.parent/'branch-return-pmu/meter.py', calibrator, observers], check=True)
        ready = json.loads((OUT/'meter-ready.json').read_bytes())
        os.sched_setaffinity(0, ready['affinity'])
    else:
        need(not os.environ.get('CONTACT_RUN') and not os.environ.get('CONTACT_SHA256') and not os.environ.get('CONTACT_READBACK_SHA256'), 'contact with prior supplied')
        # Apply the original host admission and CPU selection, without compiling or starting any PMU program.
        b.prepare_checkout(calibrator, b.CAL, 'scripts/gnu-renderer-pfc-hardware')
        b.prepare_checkout(observers, b.OBS, 'scripts/gnu-example-ceiling')
        import runpy
        cal = calibrator/'scripts/gnu-renderer-pfc-hardware'
        subprocess.run(['sha256sum','--strict','--check','--status','SHA256SUMS'], cwd=cal, check=True)
        check_host = runpy.run_path(str(cal/'calibration.py'))['host']
        ready = dict(boot=check_host(observers, OUT), affinity=sorted(os.sched_getaffinity(0)))
    need(len(ready['affinity']) == 8 and sorted(os.sched_getaffinity(0)) == ready['affinity'], 'affinity')
    host = dict(boot=ready['boot'], affinity=ready['affinity'], machine=os.uname().machine, release=os.uname().release)
    reg.host(host)
    if prior:
        reg.fresh(host['boot'], [prior['boot']])
    order = ('Eon',) if mode == 'contact' else ORDERS[position]
    save(OUT/'position.json', dict(mode=mode, position=position, host=host, boot=ready['boot'], order=order,
         run=os.environ['GITHUB_RUN_ID'], head=os.environ['GITHUB_SHA'], plan=sha(HERE/'PLAN.md'),
         command=original.CARGO, hardware_gate=gate))
    rows = {a: json.loads((OUT/'sdk'/(a+'.json')).read_bytes())['files'] for a in ('E','C')}
    start = OUT/'initial'
    start.mkdir()
    env = subjects.activate(order[0], rows, start)
    trace = component('trace')
    trace.prepare(mode, host, prior)
    b.fresh_outputs()
    b.prepare_inputs(kit, env)
    subprocess.run([sys.executable, '-IB', HERE / 'test_routes.py', kit.TREE], check=True)
    original.historical.calibration()
    refs, records, issues = {}, {}, []
    for arm in order:
        history(arm, 'clean', 'reference', rows, refs, issues, trace)
    if mode == 'contact':
        visits = history('Eon', 'structural', 'return', rows, refs, issues, trace, PREFIX[:4])
        traced = OUT/'structural-return-Eon'
        helpers = {phase: json.loads((traced/phase/'wild-helpers.json').read_bytes()) for phase in ('X-B','comment')}
        need(not issues and any(helpers.values()) and refs['Eon','clean-A'][1]['cli']['whole'] != refs['Eon','clean-B'][1]['cli']['whole'],
             'a native empty comparison, historical product, or inherited Wild fork-group witness failed')
        save(OUT/'contact.json', dict(qualified=True, mode=mode, boot=ready['boot'], scored_commands=0,
             visits=list(visits), helpers=helpers, schema=2, issues=issues))
        return
    cross_role(refs, issues)
    for lane, lineage in [('structural', 'stay'), ('structural', 'return'), ('measured', 'return')]:
        for arm in order:
            records[lane, lineage, arm] = history(arm, lane, lineage, rows, refs, issues, trace)
    finish(position, order, records, issues)


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'acquire':
            job()
            subjects.acquire(Path(sys.argv[2]))
        else:
            main(sys.argv[1], sys.argv[2], *map(Path, sys.argv[3:]))
    except BaseException:
        if OUT.is_dir():
            (OUT / 'failure.txt').write_text(traceback.format_exc())
        raise
