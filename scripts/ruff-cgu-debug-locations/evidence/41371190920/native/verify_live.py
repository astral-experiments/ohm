"""Reopen all 21 live post-O1 Ruff records, 26 native profiles and the hostile placement board."""
import argparse
from collections import Counter
import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('native_control', HERE / 'verify.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
require, sha = base.require, base.sha
PACKET = 'eec83c957091ac1ce76ab929364e983e89788f7b51054976250d1e630e9094c5'


def members():
    data = (HERE / 'post-o1-live.tar.gz').read_bytes()
    require(sha(data) == PACKET, 'live proof differs')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
        entries = tar.getmembers()
        require(len(entries) == len({e.name for e in entries}), 'duplicate live proof member')
        require(all(e.isfile() and not Path(e.name).is_absolute() and '..' not in Path(e.name).parts for e in entries), 'unsafe proof member')
        require(sum(e.size for e in entries) < 2_000_000, 'oversized proof')
        raw = {e.name: tar.extractfile(e).read() for e in entries}
    expected = json.loads(raw.pop('contents.json'))
    require({k: sha(v) for k, v in raw.items()} == expected, 'changed live proof member')
    return raw


def hostile(raw):
    before, after = [json.loads(raw[n]) for n in ('hostile-v1.json', 'hostile-v2.json')]
    require(len(before['receipt_sha']) == len(after['receipts']) == 36, 'changed hostile enrollment')
    matrix = Counter()
    sources, kinds = set(), Counter()
    different, accepted_changed, added = 0, 0, []
    for name, digest in after['receipts'].items():
        old, new = [raw[f'hostile/{label}/{name}'] for label in ('first', 'post')]
        a, b = json.loads(old), json.loads(new)
        require(sha(old) == before['receipt_sha'][name] == b['previous_case'] and sha(new) == digest, 'changed hostile case')
        require(b['registration'] == sha(raw['hostile-c2-inputs.json']) and a['unit'] == b['unit'] and a['case'] == b['case'], 'changed hostile input')
        sources.add(a['unit'])
        kinds[a['case']] += 1
        if b['status'] != 'complete':
            require(a['status'] != 'complete', 'lost an earlier hostile case')
            matrix['absent'] += 1
            continue
        require(b['live_domain_amendment'] == sha(raw['hostile-live-amendment.json']), 'changed callback domain')
        require(a['old_input'] == b['old_source'] and a['mutated_input'] == b['changed_source'], 'different adverse LLVM input')
        require(a['old_fresh']['elf'] == b['old_elf'] and a['new_fresh']['elf'] == b['new_elf'], 'independent unchanged backend gave another object')
        require(b['nondebug_same'] and all(a['old_fresh'][key] == a['new_fresh'][key] for key in ('nondebug', 'allocated', 'relocations', 'symbol_registry')), 'native code, data or link effect changed')
        require(b['old_placement_equal'] and b['new_placement_equal'] and b['c2_keys_equal'] == b['c2_reparsed_keys_equal'], 'hostile input domains disagree')
        reference = {'old_identity': b['old_elf'], 'new_identity': b['new_elf'], 'forward': b['new_elf'], 'reverse': b['old_elf'], 'reparsed_forward': b['new_elf'], 'reparsed_reverse': b['old_elf']}
        for direction, expected in reference.items():
            event = b['events'][direction]
            require(event['status'] in ('byte exact', 'refused') and event['actual'] == (expected if event['status'] == 'byte exact' else None), 'wrong hostile object')
            matrix[direction, event['status']] += 1
        require(all(b['events'][d]['status'] == b['events']['reparsed_' + d]['status'] for d in ('forward', 'reverse')), 'hostile directions differ by domain')
        hit = b['events']['forward']['status'] == 'byte exact'
        if hit:
            require(b['independently_clean_replicated'], 'fresh repetition missing on an admission')
        different += b['old_elf'] != b['new_elf']
        accepted_changed += hit and b['old_elf'] != b['new_elf']
        if b['c1_decisions']['forward'] != b['events']['forward']['status']:
            added.append(name)
    require(len(sources) == 3 and len(kinds) == 12 and set(kinds.values()) == {3} and matrix['absent'] == 2, 'wrong hostile source or case census')
    hits = sum(matrix[d, 'byte exact'] for d in ('forward', 'reverse'))
    misses = sum(matrix[d, 'refused'] for d in ('forward', 'reverse'))
    require(hits == 40 and misses == 28 and accepted_changed == 10 and len(added) == 3, 'wrong hostile verdict census')
    require(matrix['old_identity', 'byte exact'] == matrix['new_identity', 'byte exact'] == 34, 'failed a hostile identity')
    return dict(source=36, realized=34, independently_matching_directions=hits, declined_directions=misses, matching_changed_native_pairs=accepted_changed, total_changed_native_pairs=different, new_admissions=added)


def verify(raw, prior, parent_plan, reparsed):
    plan, logged, native, acquired, llvm, build = [json.loads(raw[k]) for k in ('registration.json', 'reported.json', 'native.json', 'live-inputs.json', 'producer-price.json', 'helper-build.json')]
    order = plan['ordinary_order']
    require(plan['inputs'] == parent_plan['inputs'] and order == parent_plan['ordinary_order'], 'changed input roster')
    require(plan['full_product_ffi'] == native['actual_product_ffi'] == sha(raw['live-inputs.json']), 'different continuous-live FFI')
    require(plan['actual_live_manifest'] == native['cpp_wire_manifest'] == sha(raw['wire-digests']), 'wrong 42 live wires')
    require(logged['context']['registered'] == sha(raw['registration.json']) and logged['context']['gate_packet'] == sha(raw['native.json']), 'different prospectively enrolled count or native gate')
    require(plan['previous_registration'] == sha(raw['first-registration.json']) and base.count(gzip.decompress(raw['original-empty.cg.gz'])) == 23, 'changed refused collector scope')
    require(plan['price_driver'] == sha(raw['source/native/product_price6.py']), 'native counter source differs')
    require(native['helper'] == build['sha256'] == json.loads(prior['post-o1/native-build.json'])['binary'], 'different product actor')
    require(build['product_sources'] == json.loads(prior['post-o1/native-build.json'])['actual_rust'], 'different product source')
    require(len(native['negative_controls']) == 43, 'missing malformed or incompatible native inputs')
    slots = {path.lstrip('*'): h for h, path in (l.split() for l in raw['wire-digests'].decode().splitlines())}
    fixed = json.loads(prior['original-phases.json'])
    require(len(slots) == 42 and len(order) == 21, 'wrong live roster')
    wires, hits = {}, set()
    for k in order:
        n = native['units'][k]
        old, warm, clean = plan['inputs'][k]
        pair = []
        for index, (role, record) in enumerate((('old', 'previous_envelope'), ('new', 'current_envelope'))):
            digest = slots[f'wires/{role}/{k}.wire']
            body = raw['wires/' + digest + '.osp']
            require(sha(body) == digest == n[record] and body[:4] == b'OSP\x01' and body[4:36].hex() == acquired['rows'][k][role]['key'], 'wrong live semantic module binding')
            require(body[4:36] != reparsed[k][index][4:36] and body[36:] == reparsed[k][index][36:], 'unexpected live/reparsed domain relation')
            pair.append(body)
        hit = pair[0][4:36] == pair[1][4:36]
        require(hit == acquired['rows'][k]['equal'] == n['admitted'] and n['previous_identity'] and n['current_identity'], 'wrong live admission')
        require([n['old_native_sha'], n['warm_native_sha'], n['empty_native_sha']] == [old, warm, clean] and warm == clean, 'wrong physical oracle')
        require(n['forward_sha'] == (clean if hit else None) and n['inverse_sha'] == (old if hit else None), 'wrong live complete native output')
        if hit:
            hits.add(k)
        wires[k] = pair
    require(len(hits) == 16, 'wrong number of continuous live hits')
    visits = [None, *order, *plan['reverse_size_controls'], None]
    primary = {}
    for i, (k, row) in enumerate(zip(visits, logged['observations'], strict=True)):
        name = f'{i:02}.cg.gz'
        packed = raw['counter/' + name]
        body = gzip.decompress(packed)
        count = base.count(body)
        require(sha(packed) == row['profile_gzip'] == logged['profile_files'][name] and sha(body) == row['profile_raw'], 'wrong raw count')
        require(row['index'] == i and row['key'] == k and count == row['guest_ir'] and row['binary'] == native['helper'], 'wrong measured actor, input or total')
        allowed = k is None or k in hits
        require(row['returncode'] == (0 if allowed else 2) and row['stdout_sha'] == (plan['inputs'][k][1] if k in hits else sha(b'')), 'wrong measured physical output')
        require(row['stdout_n'] == (native['units'][k]['forward_bytes'] if k else 0), 'wrong output extent')
        if k is None:
            require(count == 23, 'empty region changed')
        elif k in primary:
            require(primary[k] == count, 'inverse repeat differs')
        else:
            primary[k] = count
    cost = sum(primary.values())
    misses = sum(primary[k] for k in order if k not in hits)
    regular = sum(fixed[k]['total'] for k in order)
    gross = sum(fixed[k]['machine_emission'] for k in hits)
    key_cost = llvm['policy_cost_all_21_guest_Ir']
    require(cost == logged['aggregate'] == 373925640 and misses == 22243 and gross == llvm['gross_matched_machine_Ir'] == 60436240766, 'component costs changed')
    require(sha(raw['producer-price.json']) == 'd88a8a1c2eeee6561956a970676f2e2ccb0ab759171495350fc93254a0ad249f' and key_cost == 8909198327, 'different first live LLVM price')
    residual = regular - gross + key_cost + cost
    return visits, wires, hits, dict(live_definitely_matched_ordinary_objects=len(hits), native_fallbacks=21-len(hits), emitted_bytes=sum(native['units'][k]['forward_bytes'] for k in hits), live_21_guest_native_Ir=cost, live_5_fallback_Ir=misses, all_contextual_keys_different_from_reparsed=42, gross_machine_Ir=gross, live_current_LLVM_component_Ir=key_cost, original_backend_Ir=regular, fixed_input_estimate_Ir=residual, fixed_input_ratio=regular / residual, hostile=hostile(raw))


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--original', type=Path, help='ordinary GitHub artifact ZIP 13109144871')
    a.add_argument('--actor', type=Path, help='compiled product C2 Rust helper')
    a.add_argument('--recount', action='store_true', help='repeat all 26 native guest regions')
    args = a.parse_args()
    require(not args.actor or args.original, '--actor requires the original ZIP')
    require(not args.recount or args.actor, '--recount requires the native actor')
    raw, prior = members(), base.members()
    plan, native, _, reparsed, _ = base.verify(prior)
    visits, wires, hits, result = verify(raw, prior, plan, reparsed)
    if args.original:
        old, warm, clean = base.originals(args.original, plan['ordinary_order'], native)
        for k, digests in plan['inputs'].items():
            require([sha(a[k]) for a in (old, warm, clean)] == digests and warm[k] == clean[k], 'original source object changed')
        result['original_native_members_reopened'] = 63
    if args.actor:
        for k, (a, b) in wires.items():
            for src, left, right, want in ((old[k], a, a, old[k]), (warm[k], b, b, clean[k]), (old[k], a, b, clean[k] if k in hits else None), (warm[k], b, a, old[k] if k in hits else None)):
                base.execute(args.actor, [src, left, right], want)
        result['native_roles_reexecuted'] = 84
    if args.recount:
        require(subprocess.check_output(['valgrind', '--version'], text=True).strip() == 'valgrind-3.22.0', 'use the enrolled counter engine')
        with tempfile.TemporaryDirectory() as td:
            costs = [base.execute(args.actor, [old[k], *wires[k]] if k else [], (clean[k] if k in hits else None) if k else b'', Path(td) / f'{i:02}.cg') for i, k in enumerate(visits)]
        result['fresh_21_guest_native_Ir'] = sum(costs[1:22])
        result['fresh_raw_regions_match'] = costs == [row['guest_ir'] for row in json.loads(raw['reported.json'])['observations']]
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
