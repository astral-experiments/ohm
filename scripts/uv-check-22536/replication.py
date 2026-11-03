"""Independent-machine admission for the signed −22 repeat of the original numerical protocol."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
REGISTRATION_SHA = 'ba7191380cddea0f25b7d9b64c5e4b02017b4bff4ff457beae71945c8003a11b'
raw = (HERE / 'replication.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == REGISTRATION_SHA
PLAN = json.loads(raw)
FIRST = json.loads((HERE / 'first-host.json').read_bytes())
assert all(FIRST[a] == PLAN['first'][b] for a,b in (
    ('run','run'), ('job','job'), ('runner_id','runner'), ('boot','boot')))
assert FIRST['final_artifact']['inner_sha256'] == PLAN['first']['inner']

def ordered(protocol, original_orders):
    assert PLAN['adjacent_protocol'] == protocol
    orders = PLAN['orders']
    assert orders == [s[::-1] for s in original_orders]
    assert len(orders) == 8 and all(sorted(half) == ['PT','PT','TP','TP'] for half in (orders[:4],orders[4:]))
    return orders

def excluded(prior):
    assert len(prior) == len(set(prior)) == 28 and FIRST['boot'] not in prior
    return [*prior,FIRST['boot']]

def release(raw,lock):
    assert raw['id'] == lock['release_id'] == PLAN['first']['release_id']
    assert raw['tag_name'] == lock['tag'] == 'ohm-1.99.0-22'
    assert raw['target_commitish'] == lock['coordinator'] == PLAN['first']['source']
    assert raw['immutable'] is True and raw['draft'] is False and raw['prerelease'] is False
    asset, = [a for a in raw['assets'] if a['id'] == lock['asset_id']]
    assert asset['size'] == lock['bytes'] and asset['digest'] == 'sha256:'+lock['sha256']

def native(root, *, reference=False):
    from basis import LOCK, filehash, read
    root = Path(root)
    cal = read(root/'calibration/accepted.json')
    prior = read(HERE/'dispatch-enrollment.json')['excluded_boots']
    if reference:
        assert cal['boot'] == FIRST['boot'] and cal['excluded'] == prior
        assert filehash(root/'calibration/accepted.json') == FIRST['boot_artifact']['member_sha256']
        return {'reference_run':FIRST['run']}
    assert cal['excluded'] == excluded(prior) and cal['boot'] not in cal['excluded']
    assert read(root/'qualification/accepted.json')['control'] == 'R'
    host = read(root/'replication-host.json')
    transport = read(root/'transport.json')
    assert host['registration'] == REGISTRATION_SHA and host['boot'] == cal['boot']
    job = host['job']
    assert job['head_sha'] == transport['new_head'] and str(job['run_id']) == str(transport['run_id'])
    assert job['id'] != FIRST['job'] and job['run_id'] != FIRST['run']
    assert job['runner_id'] > 0 and job['runner_id'] != FIRST['runner_id'] and job['runner_name'] != FIRST['runner_name']
    assert host['previous'] == FIRST
    for filename in ('fresh-publication.json','fresh-publication-after.json'):
        release(read(root/filename),LOCK['release'])
    rows = observed_order(root, cal['boot'], PLAN['orders'])
    return {'registration':REGISTRATION_SHA,'job':job,'orders':PLAN['orders'],'observed_clocks':rows}

def observed_order(root, boot, orders):
    from basis import read
    # Every role executes its B/C/D ordinary clocks consecutively on one boot. Their raw
    # monotonic timestamps independently witness the physical sequence of all sixteen arms.
    last = 0
    rows = []
    for i,order in enumerate(orders,1):
        for arm in order:
            for state in 'BCD':
                clock = read(root/'pairs'/str(i)/arm/('wall-'+state)/'ordinary.json')
                start,end = clock['start_ns'],clock['end_ns']
                assert last < start < end and clock['ns'] == end-start and clock['boot'] == boot
                rows.append([i,arm,state,start,end])
                last=end
    return rows
