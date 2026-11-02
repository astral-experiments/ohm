"""Verify a fixed-object Ruff replay, optionally re-executing the Rust helper on all original native members."""
import argparse
from collections import Counter
from contextlib import ExitStack
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
PACKET = '8bca19cebeeeb4cb460751e8f582d13bfd4ddf561482e49b18f4029b588111e6'
ZIP = '53ede61bc14ac8e524813b6cac9d1cfbbcd595b5380fae363e681406aa7b404b'
OLD_RLIB = '2e7b9912290964a811f1ab91935f7d4a6808bfc1be37d6791ff1e37788af1af8'
OLD_CHECKOUT = '/home/dev-user/code/oss/ohm-rust-source-coordinate-codegen-20261102/compiler/rustc_codegen_llvm/src/back/source_placement/mod.rs'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def members():
    compressed = (HERE / 'native-price.tar.gz').read_bytes()
    require(sha(compressed) == PACKET, 'compact evidence digest differs')
    with tarfile.open(fileobj=io.BytesIO(compressed), mode='r:gz') as t:
        records = t.getmembers()
        require(len(records) == len({m.name for m in records}), 'duplicate member')
        require(all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in records), 'unsafe archive member')
        require(sum(m.size for m in records) < 2_000_000, 'unexpected expanded evidence')
        result = {m.name: t.extractfile(m).read() for m in records}
    expected = json.loads(result.pop('contents.json'))
    require({k: sha(v) for k, v in result.items()} == expected, 'evidence member differs')
    return result


def count(raw):
    require(raw.splitlines().count(b'creator: callgrind-3.22.0') == 1, 'wrong profiler')
    require(raw.splitlines().count(b'events: Ir') == 1, 'unexpected counter events')
    totals = re.findall(rb'^totals: ([0-9]+)$', raw, re.MULTILINE)
    require(len(totals) == 1, 'missing or duplicate counter total')
    return int(totals[0])


def post_o1(raw, plan, fixed):
    after = json.loads(raw['post-o1/native-verdicts.json'])
    producer = json.loads(raw['post-o1/actual-producer.json'])
    entries = [line.split() for line in raw['post-o1/SHA256SUMS'].decode().splitlines()]
    digests = {name.lstrip('*'): digest for digest, name in entries}
    require(sha(raw['post-o1/actual-producer.json']) == after['independent_postopt_source'], 'post-O1 producer changed')
    require(sha(raw['post-o1/SHA256SUMS']) == after['actual_osp_manifest'] and len(digests) == len(entries) == 42, 'different post-O1 wire roster')
    native = json.loads(raw['post-o1/native-build.json'])
    require(sha(raw['post-o1/maps.rs']) == native['actual_rust']['maps.rs'] and native['binary'] == after['actor'], 'different post-O1 native implementation')
    for name in ('dwarf.rs', 'mod.rs'):
        require(sha(raw['product/' + name]) == native['actual_rust'][name], 'different post-O1 native source')
    wires = {}
    hits = set()
    for unit, (old, warm, clean) in plan['inputs'].items():
        observed = after['rows'][unit]
        pair = []
        for role in ('old', 'new'):
            digest = digests[f'wires/{role}/{unit}.wire']
            wire = raw['post-o1/osp/' + digest + '.wire']
            require(sha(wire) == digest == observed['actual_' + role + '_osp'], 'different post-O1 wire')
            require(wire[:4] == b'OSP\x01' and wire[4:36].hex() == producer['rows'][unit][role]['key'], 'different optimized module key')
            pair.append(wire)
        wires[unit] = pair
        same = pair[0][4:36] == pair[1][4:36]
        require(same == observed['key_equal'] == producer['rows'][unit]['equal'], 'different optimized admission')
        events = observed['events']
        require(events['old_identity']['out'] == old and events['new_identity']['out'] == warm == clean, 'different optimized identity control')
        require(events['forward']['out'] == (clean if same else None) and events['reverse']['out'] == (old if same else None), 'different optimized physical output')
        if same:
            hits.add(unit)
    require(len(hits) == 16 and after['mismatch'] is None, 'different optimized native scope')
    live = json.loads(raw['post-o1/live-original-control.json'])
    require(live['live_status'] and live['live'][2] != live['serialize_parse'][2] and live['live'][3] == live['serialize_parse'][3], 'live/reparsed control differs')
    return wires, sum(fixed[k]['machine_emission'] for k in hits)


def verify(raw):
    plan, logged, evidence, fixed, compiler, stems = [json.loads(raw[k]) for k in ('registered.json', 'reported.json', 'native-verdicts.json', 'original-phases.json', 'llvm-reader-costs.json', 'wire-descriptions.json')]
    reopened = json.loads(raw['reopened.json'])
    roster = plan['ordinary_order']
    require(len(roster) == len(set(roster)) == 21 and set(roster) == set(fixed) == set(evidence['units']) == set(plan['inputs']) == set(stems), 'incomplete enrolled roster')
    require(sha(raw['registered.json']) == logged['context']['registered'], 'registration differs')
    require(sha(raw['native-verdicts.json']) == logged['context']['gate_packet'], 'off-clock admission changed')
    require(sha(raw['wire-descriptions.json']) == evidence['cpp_wire_manifest'], 'different actual C++ wires')
    for n, h in plan['actor_sources'].items():
        require(sha(raw['harness/' + n]) == h, 'counter actor source differs')
    for n, h in plan['product_sources'].items():
        require(sha(raw['product/' + n]) == h == evidence['compiler_files'][n], 'compiler helper source differs')
    callbacks = json.loads(raw['c1-literal-callbacks.json'])
    current_inputs = json.loads(raw['c1-bitcode-keys.json'])
    require(sha(raw['c1-literal-callbacks.json']) == plan['full_product_ffi'] == evidence['actual_product_ffi'], 'C++ producer custody differs')
    wires = {}
    accepted = set()
    for k in roster:
        proof = evidence['units'][k]
        trial = []
        for role, envelope in [('old', 'previous_envelope'), ('new', 'current_envelope')]:
            info = stems[k][role]
            produced = callbacks['wires'][k][role]
            osp = raw['c1-osp/' + produced + '.wire']
            require(sha(osp) == produced == proof[envelope], 'different literal C++ callback envelope')
            require(osp[:4] == b'OSP\x01' and osp[36:].startswith(b'CGU-GLOBAL-LINES\x01'), 'wrong placement protocol')
            module_key = current_inputs[k][role]['module_sha256']
            require(osp[4:36].hex() == module_key and module_key != info['key'], 'confused raw module and contextual hashes')
            require(sha(osp[36:]) == info['wire'] and len(osp) == 36 + info['bytes'], 'different typed C++ placements')
            trial.append(osp)
        wires[k] = tuple(trial)
        old, edited, clean = plan['inputs'][k]
        require([old, edited, clean] == [proof['old_native_sha'], proof['warm_native_sha'], proof['empty_native_sha']] and edited == clean, 'native oracle changed')
        require(proof['current_identity'] and proof['previous_identity'], 'failed an object identity control')
        if proof['admitted']:
            require(trial[0][4:36] == trial[1][4:36] and proof['forward_sha'] == edited and proof['inverse_sha'] == old and proof['forward_bytes'] > 0, 'admitted object differs')
            accepted.add(k)
        else:
            require(trial[0][4:36] != trial[1][4:36] and proof['forward_sha'] is None and proof['inverse_sha'] is None and proof['forward_bytes'] == 0, 'fallback emitted bytes')
    require(len(accepted) == evidence['actual'] == 15 and len(evidence['negative_controls']) == 43, 'changed native scope')
    primary = {}
    by_class = Counter()
    expected_order = [(None, 'empty-before'), *[(k, 'original') for k in roster], *[(k, 'reverse') for k in plan['reverse_size_controls']], (None, 'empty-after')]
    observations = logged['observations']
    require(len(observations) == len(expected_order) == 26, 'missing physical counter regions')
    for index, ((k, phase), info) in enumerate(zip(expected_order, observations)):
        name = f'{index:02}.cg.gz'
        compressed = raw['counter/' + name]
        data = gzip.decompress(compressed)
        require(sha(compressed) == info['profile_gzip'] == logged['profile_files'][name] and sha(data) == info['profile_raw'], 'raw counter digest differs')
        require((info['index'], info['key'], info['phase']) == (index, k, phase), 'raw region is out of order')
        n = count(data)
        require(n == info['guest_ir'] == reopened['actual_rust_rewriter'][str(index)]['total'], 'raw region cost differs')
        require(info['binary'] == evidence['helper'] == json.loads(raw['build.json'])['sha256'], 'wrong raw actor')
        if k is None:
            require(n == 23 and info['returncode'] == 0 and info['stdout_n'] == 0, 'empty control differs')
            continue
        require(info['returncode'] == (0 if k in accepted else 2) and info['stdout_sha'] == (plan['inputs'][k][1] if k in accepted else sha(b'')), 'scored native result differs')
        require(info['stdout_n'] == evidence['units'][k]['forward_bytes'], 'scored extent differs')
        if phase == 'original':
            primary[k] = n
            by_class[plan['expected_outcome'][k]] += n
        else:
            require(primary[k] == n, 'reverse raw region differs')
    for k, row in fixed.items():
        physical = reopened['physical_prior_backend'][k]
        require(physical['gzip_sha'] == row['original_gzip'] and physical['total'] == row['total'] == row['machine_emission'] + row['ir_pipeline'] + row['actor'], 'prior baseline or phase closure changed')
    normal = sum(row['total'] for row in fixed.values())
    saved = sum(fixed[k]['total'] for k in accepted)
    self_cost = sum(primary.values())
    key_cost = compiler['in_memory_policy_21_Ir']
    require(normal == compiler['all_21_fixed_parent_backend_Ir'] == plan['expected_baseline'] == 120906271208, 'wrong complete baseline')
    require(saved == compiler['measured_baseline_work_in_15_hits_Ir'] == 83908903279 and self_cost == logged['aggregate'] == 342971495 and key_cost == 7842462241, 'component costs differ')
    require(all(n == logged['groups'][c]['guest_ir'] for c, n in by_class.items()), 'classification cost differs')
    for n, result in json.loads(raw['width/receipt.json']).items():
        require(sha(raw[f'width/line-{n}.o']) == result['elf'], 'wrong signed width control')
        require(result['call_line'].encode() in raw[f'width/line-{n}.dump'], 'signed call-line form is missing')
    before = json.loads(raw['width/earlier.json'])['controls']
    require({k for k, row in before.items() if row['previous_emits_different']} == {'256-255', '65536-65535'}, 'prior width falsification differs')
    total = normal - saved + key_cost + self_cost
    earlier = json.loads(raw['older-context-counts.json'])
    require(earlier['aggregate'] == 342971484, 'earlier contextual-digest count differs')
    allocation = json.loads(raw['allocsize-native.json'])
    stale = {kind for kind, directions in allocation['rows'].items() if all(x['stale'] and x['projected'] == x['previous_object'] and x['projected_value'] == x['old_value'] != x['clean_value'] for x in directions.values())}
    require(stale == {'definition-and-call', 'definition-only'} and allocation['stale_directions'] == 4, 'observable stale executable control differs')
    require(all(x['identical'] and x['clean_value'] == 2**64 - 1 for x in allocation['rows']['no-allocsize'].values()), 'allocation control differs')
    after_wires, after_weight = post_o1(raw, plan, fixed)
    return plan, evidence, wires, after_wires, dict(observed_stale_allocsize_directions=4, reparsed_post_O1_native_hits=16, reparsed_post_O1_gross_machine_Ir=after_weight, prior_backend_Ir=normal, covered_backend_Ir=saved, current_module_Ir=key_cost, native_rewrite_all_21_Ir=self_cost, unsafe_preopt_fixed_backend_model_Ir=total, unsafe_preopt_fixed_backend_ratio=normal / total, emitted=len(accepted), scoped_observations=len(observations), old_packet_bytes=sum(len(s[0]) for s in wires.values()), new_packet_bytes=sum(len(s[1]) for s in wires.values()))


def extract(raw, dest, post_o1_version=False):
    if dest.exists():
        require(dest.is_dir() and not any(dest.iterdir()), 'requested harness directory is not empty')
    dest.mkdir(parents=True, exist_ok=True)
    for k, body in raw.items():
        if k.startswith('product/'):
            target = dest / 'src/source_placement' / k.removeprefix('product/')
        elif k.startswith('harness/'):
            target = dest / k.removeprefix('harness/')
        else:
            continue
        if k == 'harness/src/main.rs':
            require(body.count(b'source_placement/mod.rs') == 1, 'unexpected frozen actor source path')
        if post_o1_version and k == 'product/maps.rs':
            body = raw['post-o1/maps.rs']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def originals(path, roster, evidence):
    with path.open('rb') as f:
        require(hashlib.file_digest(f, 'sha256').hexdigest() == ZIP, 'wrong complete GitHub artifact')
    spec = importlib.util.spec_from_file_location('old_archive_reader', HERE.parent / 'verify.py')
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    with zipfile.ZipFile(path) as z:
        return [base.original_members(z, prefix, set(roster), digest) for prefix, digest in [('capture/old', OLD_RLIB), ('capture/new', evidence['warm_native']), ('capture-empty/new', evidence['clean_native'])]]


def execute(exe, buffers, expected, profile=None):
    import fcntl
    fds = []
    with ExitStack() as stack:
        for data in buffers:
            fd = os.memfd_create('ohm-native-qa', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            stack.callback(os.close, fd)
            require(os.write(fd, data) == len(data), 'short write')
            os.lseek(fd, 0, os.SEEK_SET)
            # Linux UAPI values for ADD/GET_SEALS, available even when the Python build omits their names.
            fcntl.fcntl(fd, 1033, 15)
            require(fcntl.fcntl(fd, 1034) & 15 == 15, 'input file descriptor is not sealed')
            fds.append(fd)
        if profile is None:
            cmd = [str(exe), 'rebase']
        else:
            cmd = ['valgrind', '--tool=callgrind', '--instr-atstart=no', '--cache-sim=no', '--branch-sim=no', '--error-exitcode=83', '--callgrind-out-file=' + str(profile), '--log-file=' + str(profile.with_suffix('.log')), str(exe), 'meter']
        r = subprocess.run([*cmd, *[f'/proc/self/fd/{fd}' for fd in fds]], capture_output=True, pass_fds=fds, timeout=120)
    require((r.returncode, r.stdout) == ((2, b'') if expected is None else (0, expected)), 'actor output or correctness verdict differs')
    return count(profile.read_bytes()) if profile is not None else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extract-harness', type=Path, help='write a standalone Cargo QA crate into an empty directory')
    parser.add_argument('--post-o1-harness', type=Path, help='export the exact post-O1 Rust source actor')
    parser.add_argument('--post-o1-actor', type=Path, help='execute the second actor on all optimized-module records')
    parser.add_argument('--original', type=Path, help='full original GitHub artifact 13109144871 ZIP')
    parser.add_argument('--actor', type=Path, help='execute a built QA binary on the original members and signed width controls')
    parser.add_argument('--recount', action='store_true', help='repeat 26 counter regions on this machine with the supplied actor')
    options = parser.parse_args()
    require(not (options.actor or options.post_o1_actor) or options.original, '--actor needs the original artifact')
    require(not options.recount or options.actor, '--recount needs the actor and original artifact')
    raw = members()
    plan, evidence, wires, after_wires, result = verify(raw)
    if options.extract_harness:
        extract(raw, options.extract_harness)
    if options.post_o1_harness:
        extract(raw, options.post_o1_harness, post_o1_version=True)
    if options.original:
        old, warm, clean = originals(options.original, plan['ordinary_order'], evidence)
        for k, hashes in plan['inputs'].items():
            require([sha(objects[k]) for objects in (old, warm, clean)] == hashes and warm[k] == clean[k], 'original native member differs')
        result['original_members_reopened'] = 63
    if options.actor:
        exe = options.actor.resolve(strict=True)
        for k, (a, b) in wires.items():
            hit = evidence['units'][k]['admitted']
            for source, left, right, expected in [(old[k], a, a, old[k]), (warm[k], b, b, clean[k]), (old[k], a, b, clean[k] if hit else None), (warm[k], b, a, old[k] if hit else None)]:
                execute(exe, [source, left, right], expected)
        for a, b, compatible in [(254, 255, True), (255, 254, True), (256, 257, True), (257, 256, True), (255, 256, False), (256, 255, False), (65535, 65536, False), (65536, 65535, False)]:
            execute(exe, [raw[f'width/line-{a}.o'], raw[f'width/line-{a}.osp'], raw[f'width/line-{b}.osp']], raw[f'width/line-{b}.o'] if compatible else None)
        result['native_responses_reexecuted'] = 92
    if options.post_o1_actor:
        second = options.post_o1_actor.resolve(strict=True)
        for k, (a, b) in after_wires.items():
            hit = a[4:36] == b[4:36]
            for source, left, right, wanted in [(old[k], a, a, old[k]), (warm[k], b, b, clean[k]), (old[k], a, b, clean[k] if hit else None), (warm[k], b, a, old[k] if hit else None)]:
                execute(second, [source, left, right], wanted)
        result['post_O1_native_responses_reexecuted'] = 84
    if options.recount:
        require(subprocess.check_output(['valgrind', '--version'], text=True).strip() == 'valgrind-3.22.0', 'use the declared counter version')
        order = [None, *plan['ordinary_order'], *plan['reverse_size_controls'], None]
        with tempfile.TemporaryDirectory() as temp:
            counts = []
            for i, k in enumerate(order):
                args = [old[k], *wires[k]] if k else []
                expected = (clean[k] if evidence['units'][k]['admitted'] else None) if k else b''
                counts.append(execute(exe, args, expected, Path(temp) / f'{i:02}.cg'))
        exact = [v['guest_ir'] for v in json.loads(raw['reported.json'])['observations']]
        result.update(recount_guest_Ir=counts, recount_21_Ir=sum(counts[1:22]), recount_matches_original=counts == exact)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
