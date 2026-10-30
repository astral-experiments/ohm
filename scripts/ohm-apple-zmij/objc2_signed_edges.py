"""Compare exactly the public -20 Cargo's native outcomes for both frame-marker compilers."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import provider_edges as edge
from dyld import check as dyld
from execs import ExecTrace
from fixed_crc import INPLACE, same_stamp
from measure import select
from prepare import role_files
from study import CARGO_SOURCE, CHILD, PARENT, env_for, load, need, physical, save, sha


def main(root):
    logs = root / 'receipts'
    matrix = logs / 'provider-matrix'
    matrix.mkdir()
    for name in ('edge-images', 'edge-markers'):
        (logs / name).mkdir()
    pair = load(logs / 'pair.json')
    signed = load(logs / 'release.json')['cargo']
    need(CARGO_SOURCE == '2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c' and
         [pair['products'][r]['source'] for r in 'PC'] == [PARENT, CHILD], 'unbound sources')
    need('asm!("mov fp, fp", options(nomem, nostack, preserves_flags))' in edge.BARRIER and
         edge.BARRIER.count('asm!') == 1, 'wrong assembly input')
    identities = {}
    for role in 'PC':
        sdk = select(root, role)
        cargo = sdk/'bin/cargo'
        env = env_for(root/'verify', sdk)
        need('CI' not in env and 'TF_BUILD' not in env and 'CARGO_INCREMENTAL' not in env, 'wrong developer environment')
        need(cargo.samefile(root/'signed/bin/cargo') and sha(cargo) == signed['sha256'] and
             role_files(sdk) == pair['products'][role]['runtime'], 'changed native SDK')
        dyld(root, role, sdk, logs/'signed-runtime'/role/'dyld')
        identities[role] = physical(cargo)
    need(identities['P'] == identities['C'], 'Cargo selector changed native executable')
    save(matrix/'registration.json', {'cargo': CARGO_SOURCE, 'rust': [PARENT, CHILD], 'signed': identities,
                                      'barrier': edge.BARRIER, 'steps': edge.STEPS, 'inplace': INPLACE,
                                      'fixture_digest': sha(Path(edge.__file__))})
    bodies = edge.provider_factory(root, matrix)
    trace = ExecTrace()
    trace.ready()
    cases = {}
    stamps = {}
    try:
        for watch in ('unwatched', 'declared'):
            for placement in ('direct', 'library'):
                for defaults in (True, False):
                    for role in 'PC':
                        label = '-'.join((role, placement, watch, 'default' if defaults else 'off'))
                        cases[label] = edge.run_case(root, trace, role, placement, watch, defaults, bodies)
                        print('completed', label, flush=True)
        for role in 'PC':
            for placement in ('direct', 'library'):
                key = f'{role}stamp-{placement}-unwatched-default'
                rows = edge.run_case(root, trace, role, placement, 'unwatched', True, bodies,
                                     visits=INPLACE, change=same_stamp, label=role+'stamp')
                differing = []
                for name, state, rust in INPLACE:
                    item = rows[name]
                    expected = [0, [17 if state == 'overwrite' else 29, rust]]
                    need(item['empty'][:2] == expected, 'wrong independently empty in-place reference')
                    if item['warm'][:2] != expected:
                        differing.append(name)
                stamps[key] = differing
    finally:
        trace.close()
    for rows in cases.values():
        for name, state, rust in edge.STEPS:
            v = edge.NATIVE[state]
            expected = [0, [v, rust]] if v is not None else [101, None]
            need(rows[name]['empty'][:2] == expected, 'wrong independently empty reference')
    need(len(cases) == 16 and len(stamps) == 4 and len(edge.STEPS) == 11, 'missing native comparisons')
    out = {'signed': identities, 'commands': 392, 'inplace_wrong_warm': stamps, **edge.classify(cases)}
    save(matrix/'terminal.json', out)
    print(json.dumps({k: len(v) for k, v in out.items() if isinstance(v, list)}, sort_keys=True), stamps, flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(strict=True))
