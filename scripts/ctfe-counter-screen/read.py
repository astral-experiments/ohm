"""Reopen both untraced instruction screens from their original job artifacts."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ctfe-crossover-pilot'))
import reopen as old

PRIOR = '18d265bca52c9907b9e53275f80064446c9bd7ccd28431e20450e0e4f11f1efc'
GRAPH = 'f5909e1cbd4832369f783bdbd733e54562bcce15e44592b8ec15793e9996c660'
REJECTED = {'4f4d4a31-68c1-447b-9909-8f4c951d6d82', 'c9fb2eab-3d98-4154-b864-cfac6df82005'}
require = old.require


def media(official, run, head, archives):
    data, jobs, assets = [json.loads((official / (key + '.json')).read_bytes()) for key in ('run', 'jobs', 'artifacts')]
    require((data['id'], data['head_sha'], data['head_branch'], data['event'], data['path'], data['run_attempt'], data['status']) ==
            (run, head, 'charlie/qa-ctfe-counter-screen-20261101', 'workflow_dispatch', '.github/workflows/ci.yml', 1, 'completed')
            and data['repository']['full_name'] == data['head_repository']['full_name'] == 'astral-experiments/ohm', 'wrong run')
    require(jobs['total_count'] == len(jobs['jobs']) == assets['total_count'] == len(assets['artifacts']) == 2, 'incomplete media')
    seen_jobs, seen_assets = set(), set()
    for pos, path in zip(('01', '02'), archives, strict=True):
        job, = [v for v in jobs['jobs'] if v['name'] == 'Count Ruff build instructions ' + pos]
        asset, = [v for v in assets['artifacts'] if v['name'] == 'ctfe-full-cli-counter-' + pos]
        require((job['run_id'], job['head_sha'], job['run_attempt'], job['status'], job['labels']) ==
                (run, head, 1, 'completed', ['namespace-profile-ubuntu-24-04-16']), 'unexpected hardware job')
        require((asset['workflow_run']['id'], asset['workflow_run']['head_sha'], asset['size_in_bytes'], asset['expired']) ==
                (run, head, path.stat().st_size, False), 'wrong archive identity')
        with path.open('rb') as f:
            require(asset['digest'] == 'sha256:' + hashlib.file_digest(f, 'sha256').hexdigest(), 'wrong official ZIP bytes')
        seen_jobs.add(job['id'])
        seen_assets.add(asset['id'])
    require(len(seen_jobs) == len(seen_assets) == 2, 'duplicate original worker')
    return data['conclusion'] == 'success' and all(j['conclusion'] == 'success' and all(any(
        s['name'] == name and s['status'] == 'completed' and s['conclusion'] == 'success' for s in j['steps']) for name in
        ('Reconstruct both 81-file compiler installations using original source artifacts', 'Count both untraced Ruff histories'))
        for j in jobs['jobs'])


def read_one(path, pos, run, head):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        require(len(set(names)) == len(names) and all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in names)
                and not any('kernel.tsv' in n or n.endswith('native-execs.json.gz') for n in names), 'ambiguous or traced screen')
        record = old.dataset(z, 'position.json')
        order = tuple(old.ROLES if pos == '01' else reversed(old.ROLES))
        meter = old.dataset(z, 'meter-ready.json')
        boot = record['boot']
        require(boot == meter['boot'] and boot not in REJECTED and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot)
                and (record['position'], tuple(record['order']), int(record['run']), record['head'], record['command'], record['prior'], record['plan']) ==
                (pos, order, run, head, old.CARGO, PRIOR, old.digest((HERE / 'PLAN.md').read_bytes())), 'wrong boot or screen')
        cal = old.replay_controls.calibration(z, boot)
        hardware = old.hardware.verify(z, cal, meter)
        require(meter['affinity'] == cal['affinity'] and meter['observer'] == old.replay_controls.OBS
                and meter['calibrator'] == old.replay_controls.CAL, 'different meter')
        sdks = old.sdk_pair(z)
        bodies, envs, rows, refs, issues, clocks = {}, {}, {}, {}, [], set()
        last_stop = 0
        for lane, route, phases in (('clean', 'reference', old.REFS), ('measured', 'return', old.PHASES),
                                    ('measured', 'stay', old.PHASES[:5])):
            for arm in order:
                top = '-'.join((lane, route, arm))
                cert, root = old.active(z, top, arm, sdks[arm[0]]['files'])
                require(envs.setdefault(arm, cert['env']) == cert['env'] and meter['plain'] == str(root / 'logs/observers/plain'), 'changed environment')
                for phase in phases:
                    prefix = top + '/' + phase
                    obs = old.read_phase(z, prefix, phase, lane, route, arm, cert, root, bodies)
                    require(obs['status'] != 0 or obs['graph'] == GRAPH, 'different complete historical Ruff graph')
                    if lane == 'clean':
                        refs[arm, phase] = obs
                    else:
                        clocks.add(prefix + '/clock.json')
                        require(last_stop < obs['start'], 'overlapping or reordered paired clock')
                        last_stop = obs['stop']
                        if phase == 'unchanged':
                            require(obs['source'] == old.dataset(z, top + '/comment/source.json'), 'changed source before repeat')
                        if phase != 'invalid':
                            wanted = refs[arm, obs['reference']]
                            require(obs['graph'] == wanted['graph'] and old.behavior(obs['native']) == old.behavior(wanted['native']),
                                    'behavior or 375-unit graph differs from independently empty source')
                            for product in ('cli', 'reader'):
                                if obs[product] != wanted[product]:
                                    issues.append(dict(visit=prefix, product=product, actual=obs[product], empty=wanted[product]))
                    rows[prefix] = {k:v for k,v in obs.items() if k not in ('source','native','start','stop')}
        require(envs['Eon'] == envs['Con'] and len(clocks) == 24 and len(rows) == 30 and
                {n for n in names if n.startswith(('clean-reference-', 'measured-')) and n.endswith('/clock.json')} == clocks,
                'missing or extra ordinary clock/visit')
        for state in old.REFS:
            e, c = (refs[a, state] for a in old.ROLES)
            require(e['graph'] == c['graph'] and old.behavior(e['native']) == old.behavior(c['native']), 'cross-compiler behavior')
            for k in ('cli', 'reader'):
                if any(e['native'][k][f] != c['native'][k][f] for f in ('executable','loads')):
                    issues.append(dict(reference=state, different_executable_bytes=k, E=e[k], C=c[k]))
        require(all(refs[a,'clean-A']['cli'] != refs[a,'clean-B']['cli'] for a in order), 'real A/B edit failed to change the program')
        score = old.dataset(z, 'screen.json')
        primary = {a:rows['measured-return-'+a+'/comment']['instructions'] for a in order}
        require(score['primary'] == primary and score['process_counts'] == 'unobserved' and
                Counter(map(old.metrics.canonical, score['issues'])) == Counter(map(old.metrics.canonical, issues)), 'wrong reported outcome')
        return dict(boot=boot, position=pos, instructions=primary, ratio=primary['Eon']/primary['Con'], visits=rows,
                    issues=issues, native_bodies=len(bodies), hardware=hardware, finished_cleanly='failure.txt' not in names)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official', required=True, type=Path)
    parser.add_argument('--run', required=True, type=int)
    parser.add_argument('--head', required=True)
    parser.add_argument('archives', nargs=2, type=Path)
    args = parser.parse_args()
    success = media(args.official, args.run, args.head, args.archives)
    workers = [read_one(p, pos, args.run, args.head) for pos,p in zip(('01','02'),args.archives,strict=True)]
    require(workers[0]['boot'] != workers[1]['boot'], 'reused hardware boot')
    qualifies = success and all(not r['issues'] and r['finished_cleanly'] for r in workers)
    print(json.dumps(dict(run=args.run, head=args.head, workers=workers, valid_counter_screen=qualifies,
            meets_two_per_boot=qualifies and all(r['instructions']['Eon'] >= 2*r['instructions']['Con'] for r in workers),
            process_counts='unobserved', sufficient_for_pr=False), sort_keys=True, indent=2))
