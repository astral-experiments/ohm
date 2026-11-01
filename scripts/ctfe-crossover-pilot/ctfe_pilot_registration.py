"""Immutable past controls, fresh boot and official archive enrollment for the two schema-3 modes."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO = 'astral-experiments/ohm'
BRANCH = 'charlie/qa-ruff-same-revision-donor-full-20261101'
BASE = '5c651f1d38c629da2a75d5cac3588db0be8104d7'
OBSERVER = '19f9a67b032cce44cea1e3bb7e324558cd9abd0a'
OBSERVER_MANIFEST = 'dd9079b8bbe00593142dde1def8862a2d1f5d2cb04e6445e2f056f56dbff3292'
SOURCE = '3e859dbcd5456d8a1cac6fcd320dcff9540e07c9e5ccf766b5c43b4a7087ede1'
READER = '99ce628b4cd2e422857f9b4ac9dd59b135cd6c306848b09b0cbdfe7a6d856b41'
PROJECTOR = '5e91ed3974c0964a912fd38049946f647891dcb2'
SCREEN = 41285793847
SCREEN_HEAD = '28fe14afcf485bc99e7bd9036d9b4f4bb990ce86'
PREVIOUS = {
    41303656721: ('e2c543c2-6e4d-43f5-84b0-7818e04d9dca',),
    41301552076: ('b54107ac-1475-4a48-932c-e2248d479f5d',),

    41296950309: ('5589abc8-0aa8-4fb5-af09-41d799eb0139',),
    41295435433: ('67ec1c48-d4fc-4394-8cb1-b18026c44af7',),
    41291100905: ('c652a1a6-da1c-4698-b416-cd02e2b88e9a', '5d0531b9-cfc3-4e08-878a-6c03ee6d2b7f'),
    41289369980: ('453a4e51-5e63-4b02-8ef3-aed22a5656be',),
    41290140885: ('d9365602-cd3f-4d2b-8f31-db6e012cab0a', '6af97d29-b3f0-4134-907c-c1f970c0816a'),
    41289034546: ('464040f9-d0d7-4d3a-ba23-06a9a898b0f4', '66b96dca-6f95-4fde-aa78-ce2ebc5c959a'),
    41283234972: ('4f4d4a31-68c1-447b-9909-8f4c951d6d82', 'c9fb2eab-3d98-4154-b864-cfac6df82005'),
    SCREEN: ('61149494-93be-4462-8cec-12fa66623bc7', '364da3c4-7589-4095-b2e6-efeddb2cf64f'),
    41200174886: ('cf938e9c-a8d2-4a0d-8260-fb5f89d89d65', '3b0e4081-536a-4f6a-a945-674825be2329'),
    41204995845: ('3060b886-0ac1-46a3-a1c1-a3c34b9073b6', '701225ea-feee-4195-82a3-9a1f70d39c46'),
}
_machine_file = HERE/'enrollment/additional-machines.json'
if hashlib.sha256(_machine_file.read_bytes()).hexdigest() != "53c1885b102865c68461544cf4381d45ef9f94edbd1e07a8cf8aa7b06d8670c7":
    raise ValueError('additional boot ledger changed')
_machines = json.loads(_machine_file.read_bytes())
PREVIOUS.update({int(k):tuple(v['boots']) for k,v in _machines['originals'].items()})

STEP_SOURCE = 'Reconstruct both 81-file compiler installations using original source artifacts'
STEP_RUN = 'Run the enrolled ordinary Ruff visits'
STEP_INTAKE = 'Independently verify the official v3 contact'
SCREEN_FILES = {'independent.json':'fe8fbf97dcb1416069be2f02d3c593fa7dd99e37185c6bd41baafb1aba2ad2e4',
                'summary.json':'fef729df7be0705ffc5a105e7920cc8ed6aab74cf72cfbceb62fb52e04425a05'}

def require(value, reason):
    if not value:
        raise ValueError(reason)

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def previous_meter():
    for name, expected in SCREEN_FILES.items():
        require(sha(HERE/'enrollment'/name) == expected, 'wrong original hardware readback')
    report, summary = (json.loads((HERE/'enrollment'/name).read_bytes()) for name in SCREEN_FILES)
    require(report['valid_counter_screen'] is True and
            report['head'] == SCREEN_HEAD and report['run'] == SCREEN
            and summary['result_sha256'] == SCREEN_FILES['independent.json'] and
            tuple(w['boot'] for w in summary['workers']) == PREVIOUS[SCREEN], 'previous two independent hardware gates')
    return dict(run=SCREEN, head=SCREEN_HEAD, readbacks=SCREEN_FILES)

def hardware_gate():
    # A prior counter calibration validates the meter only; the structural result belongs to E and D.
    prior_meter = previous_meter()
    path = HERE / 'enrollment/donor-source.json'
    require(sha(path) == "97f7e95aea09f24822d4f71f3d77c7d934e7271635551e7f8fc205fd7c03a1d0", 'changed source/donor enrollment')
    data = json.loads(path.read_bytes())
    result = data['native_reader']
    require(result['source'] == ['393b4b05a4bfa3f531a36023846f86236a6b71a9', 'd95494a6a63c22222806c06e3d3aa0de504d8e8a']
            and result['qualified'] and result['workspace_cargo_commands'] == 36 and result['provider_cargo_commands'] == 22,
            'unqualified source or real donor controls')
    return dict(source_run=data['run'], source_head=data['head'], native=data['source_sha256'], meter=prior_meter)

def fresh(boot, excluded=()):
    require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot) and
            boot not in {b for boots in PREVIOUS.values() for b in boots} and boot not in excluded, 'reused or invalid boot')

def host(row):
    fresh(row['boot'])
    require(row['machine'] == 'x86_64' and re.fullmatch(r'7\.1\.4(?:[-+].*)?', row['release']) and
            len(row['affinity']) == 8 and row['affinity'] == sorted(set(row['affinity'])), 'wrong 7.1.4/x86_64 host')

def jobs(mode):
    require(mode in ('contact','full-pilot'), 'unknown study mode')
    return ('01',) if mode == 'contact' else ('01','02')

def official(directory, run, head, mode, files=None):
    """Match every job and file on attempt one, including every actual original ZIP when supplied."""
    run_info, js, ar = [json.loads((directory/name).read_bytes()) for name in ('run.json','jobs.json','artifacts.json')]
    positions = jobs(mode)
    require(re.fullmatch(r'[0-9a-f]{40}', head) and type(run) is int and run > 0 and
            (run_info['id'],run_info['run_attempt'],run_info['head_sha'],run_info['head_branch'],run_info['event'],
             run_info['path'],run_info['status'],run_info['conclusion']) ==
            (run,1,head,BRANCH,'workflow_dispatch','.github/workflows/ci.yml','completed','success') and
            run_info['repository']['full_name'] == run_info['head_repository']['full_name'] == REPO, 'wrong official attempt')
    require(js['total_count'] == len(js['jobs']) == ar['total_count'] == len(ar['artifacts']) == len(positions),
            'ambiguous original jobs or archives')
    if files is not None:
        require(len(files) == len(positions), 'incomplete supplied original archives')
    result = []
    for i, pos in enumerate(positions):
        j, = (x for x in js['jobs'] if x['name'] == f'GNU donor {mode} {pos}')
        a, = (x for x in ar['artifacts'] if x['name'] == f'gnu-donor-{mode}-{pos}')
        require(j['runner_id']>0 and j['runner_name'] and all(j['runner_id']!=v['id'] and j['runner_name']!=v['name']
                for v in _machines['source_jobs'].values()), 'reused source worker including the no-boot refusal')
        steps = {s['name']: (s['status'],s['conclusion']) for s in j['steps']}
        needed = [STEP_SOURCE,STEP_RUN] + ([STEP_INTAKE] if mode == 'full-pilot' else [])
        require((j['run_id'],j['head_sha'],j['run_attempt'],j['status'],j['conclusion']) ==
                (run,head,1,'completed','success') and all(steps[n] == ('completed','success') for n in needed) and
                j['labels'] == ['namespace-profile-ubuntu-24-04-16'] and
                (mode != 'contact' or steps[STEP_INTAKE] == ('completed','skipped')) and
                a['workflow_run']['id'] == run and a['workflow_run']['head_sha'] == head and not a['expired'] and
                0 < a['size_in_bytes'] < 2**30 and re.fullmatch(r'sha256:[0-9a-f]{64}',a['digest']), 'wrong job or ZIP')
        if files is not None:
            require(files[i].stat().st_size == a['size_in_bytes'] and sha(files[i]) == a['digest'][7:], 'different original ZIP')
        result.append(dict(position=pos, job=j['id'], artifact=a['id'], size=a['size_in_bytes'], sha256=a['digest'][7:]))
    require(all(len({x[k] for x in result}) == len(positions) for k in ('job','artifact')), 'duplicate original')
    return dict(repo=REPO, branch=BRANCH, workflow=run_info['path'], mode=mode, head=head, run=run, attempt=1, files=result)

def wild_helpers(raw, wild_rows):
    """Attribute only a sealed fork-group to an already projected stock Wild link image."""
    link = {r['event']: r for r in wild_rows}
    effective, forks, groups, peers = {}, {}, {}, {}
    for line in raw.splitlines():
        f = line.split(b'\t', 6)
        tag = f[0]
        if tag == b'R':
            effective[int(f[1])] = None
        elif tag == b'E':
            effective[int(f[2])] = int(f[1])
        elif tag == b'N':
            parent, kind, child = int(f[1]), int(f[3]), int(f[4])
            effective[child] = effective[parent]
            if kind == 1 and effective[parent] in link:
                forks[child] = (parent, effective[parent])
        elif tag == b'G':
            owner = int(f[1])
            if owner in forks and effective[owner] == forks[owner][1]:
                parent, event = forks[owner]
                r = link[event]
                require(r['lifetime'] != owner, 'Wild must fork a distinct helper')
                groups[owner] = dict(owner=owner, pid=int(f[2]), status=int(f[3]), parent=parent,
                                     wild_event=event, wild_lifetime=r['lifetime'], output=r['output'],
                                     rustc_event=r['rustc_event'], rustc_crate=r['rustc_crate'])
                peers[owner] = []
        elif tag == b'Q' and int(f[3]) in groups:
            peers[int(f[3])].append(int(f[1]))
        elif tag == b'V' and int(f[1]) in groups:
            owner = int(f[1])
            require(len(peers[owner]) == int(f[3]), 'uncounted Wild peer')
            groups[owner]['parked'] = sorted(peers[owner])
    # The process-family parser separately verifies the witnessed X/T of every owner and parked peer.
    return [g for g in groups.values() if g.get('parked')]


def compiler_groups(raw, rustcs):
    """Attribute fully stopped groups to the installed rustc in a previously closed raw ledger."""
    by_install = {(r['lifetime'], r['event']): r for r in rustcs}
    groups = {}
    for line in raw.splitlines():
        f = line.split(b'\t', 5)
        if f[0] == b'H':
            owner, pid, status, ordinal = map(int, f[1:])
            r = by_install.get((owner, ordinal))
            if r is not None:
                require(r['pid']==pid, 'different compiler group leader')
                groups[owner] = dict(owner=owner,pid=pid,event=ordinal,status=status,crate=r['crate'])
        elif f[0] == b'V' and int(f[1]) in groups:
            groups[int(f[1])]['workers'] = int(f[3])
    return [g for g in groups.values() if g['workers'] > 0]
