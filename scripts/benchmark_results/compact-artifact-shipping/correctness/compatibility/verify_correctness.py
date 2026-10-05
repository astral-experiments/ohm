#!/usr/bin/env python3
"""Verify/extract this additive proof bundle, then check its recorded native execution.

This verifies receipts, not the remote machine or a fresh compiler execution.
No older archive, installed toolchain, or original absolute path is read.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

REMOTE = Path('/home/dev-user/code/oss/ohm-compact-study/shipping/compatibility')
RUST = '4790daedc77c40dc4dc3a0f1789a9579d6aee773b88f4ec968e2884ef42fcc49'
CARGO = '20b9d1fdf46667b3f65bbcba67bf7358acaeb4653b6df1fd05ed431f46172872'
FINAL_CARGO = '76793c44b8f426220ce9b86449fe405b8a85a95f'
FINAL_PATCH = 'cc8871ae6b1572a771c54f8ac84e118be3354986190951b54faed4762c123d5d'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def canonical(name):
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts and str(p) == name,
            'non-canonical archive path: ' + name)
    require(p.parts[0] == 'compatibility-proof' and len(p.parts) > 1, 'wrong archive root')
    return p


def extract(archive, manifest_path, destination):
    seal = load(manifest_path)
    require(sha(archive) == seal['archive_sha256'], 'archive hash mismatch')
    require(not destination.exists() and not destination.is_symlink(), 'destination already exists')
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        names = [m.name for m in members]
        require(len(names) == len(set(names)) == seal['members'], 'duplicate/member count mismatch')
        require(len(members) < 2000 and sum(m.size for m in members) < 100 * 1024**2,
                'proof archive exceeds bounded scope')
        for member in members:
            canonical(member.name)
            require(member.isfile() and member.size < 20 * 1024**2, 'non-regular/oversized member')
        raw_inventory = tar.extractfile('compatibility-proof/inventory.json').read()
        require(hashlib.sha256(raw_inventory).hexdigest() == seal['inventory_sha256'], 'inventory hash')
        inventory = json.loads(raw_inventory)
        expected = inventory['files']
        require(set(names) == {'compatibility-proof/' + n for n in expected} |
                {'compatibility-proof/inventory.json'}, 'inventory coverage')
        # Validate all content before creating the destination. Extraction never overwrites.
        for member in members:
            relative = str(PurePosixPath(member.name).relative_to('compatibility-proof'))
            if relative == 'inventory.json':
                continue
            data = tar.extractfile(member).read()
            require(len(data) == expected[relative]['bytes'] and
                    hashlib.sha256(data).hexdigest() == expected[relative]['sha256'], relative)
        destination.mkdir()
        for member in members:
            path = destination / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as output:
                output.write(tar.extractfile(member).read())
    return destination / 'compatibility-proof', seal


def recorded_execution(root):
    def remote(path):
        relative = Path(path).relative_to(REMOTE)
        require('..' not in relative.parts and str(REMOTE / relative) == path,
                'noncanonical remote receipt path')
        result = root / relative
        require(result.resolve().is_relative_to(root.resolve()), 'receipt escapes extracted root')
        return result

    def receipt(name):
        return load(root / 'evidence' / name / 'result.json')

    compiler, cargo, native = (receipt(n) for n in ('compiler-v3', 'cargo-v2', 'native-v1'))
    require(all(r['passed'] for r in (compiler, cargo, native)), 'current execution not passed')
    require(compiler['patch_sha256'] == RUST and cargo['patch_sha256'] == CARGO, 'source patches')
    for name, value in [('compiler-v3', RUST), ('cargo-v2', CARGO)]:
        require(sha(root / 'inputs' / (name + '.patch')) == value, 'patch bytes')
    cm = load(root / 'inputs/compiler-v3-manifest.json')
    gm = load(root / 'inputs/cargo-v2-manifest.json')
    require(load(root / 'evidence/compiler-v3/source-files.json')['files'] ==
            {r['path']: r['sha256'] for r in cm['files']}, 'compiler built source files')
    require(load(root / 'evidence/cargo-v2/source-files.json')['files'] == gm['files'], 'Cargo built source files')
    for name, record in [('compiler-v3', compiler), ('cargo-v2', cargo)]:
        require(record['source_manifest_sha256'] == sha(root / 'evidence' / name / 'source-files.json'),
                'source manifest bytes')
    require(cargo['manifest_sha256'] == sha(root / 'inputs/cargo-v2-manifest.json'), 'Cargo manifest bytes')
    require(len(native['components']) == 6, 'native component scope')
    for ref in native['components'].values():
        p = remote(ref['path'])
        require(sha(p) == ref['sha256'] and load(p)['passed'], 'native component receipt')
    require(native['compiler_build_sha256'] == cargo['compiler_build_sha256'] ==
            sha(root / 'evidence/compiler-v3/result.json'), 'compiler binding')
    require(native['cargo_build_sha256'] == sha(root / 'evidence/cargo-v2/result.json'), 'Cargo binding')
    policy = receipt('cargo-policy-v1')
    require(policy['script_sha256'] == sha(root / 'controls/native_cargo_compatibility.py'), 'policy control')
    require(policy['compiler_build_sha256'] == native['compiler_build_sha256'] and
            policy['cargo_build_sha256'] == native['cargo_build_sha256'], 'policy builds')
    require(policy['toolchain'] == native['toolchain'] and policy['toolchain_unchanged'], 'policy identities')
    for key in ('path', 'rustc_sha256', 'rustdoc_sha256', 'drivers', 'wild_sha256', 'marker'):
        require(compiler['toolchain'][key] == cargo['toolchain'][key] == native['toolchain'][key], key)
    require(cargo['cargo']['sha256'] == native['toolchain']['cargo_sha256'], 'Cargo binary identity')
    require(native['toolchain']['marker'] == {'name': 'compact-artifacts-v2', 'sha256':
            hashlib.sha256(b'RCOBJ001\n').hexdigest()}, 'v2 marker')
    counts = {}
    for row in cargo['commands']:
        log = root / 'evidence/cargo-v2' / (row['name'] + '.log')
        require(sha(log) == row['log_sha256'], 'Cargo command log')
        if row['name'] in ('selection-units', 'provenance-units', 'wrapper-range', 'routing-suite'):
            match = re.search(r'test result: ok\. (\d+) passed; 0 failed; 0 ignored;', log.read_text())
            require(row['code'] == 0 and match, 'required Cargo tests')
            counts[row['name']] = int(match[1])
    require(counts == {'selection-units': 4, 'provenance-units': 1, 'wrapper-range': 1, 'routing-suite': 6}, 'test counts')
    suites = receipt('rust-suites-v1')
    require(suites['compiler_build_sha256'] == native['compiler_build_sha256'] and
            suites['patch_sha256'] == RUST and suites['toolchain'] == compiler['toolchain'],
            'forced Rust suite compiler identity')
    require({r['suite'] for r in suites['commands']} ==
            {'compact-artifact-exports', 'public-api-hash-artifact', 'compact-artifact-lto-dwarf'}, 'Rust suite set')
    require(suites['test_payload_sha256'] == sha(root / 'inputs/compiler-tests-v1.tar.gz'), 'new regression tests')
    for row in suites['commands']:
        log = root / 'evidence/rust-suites-v1' / (row['suite'] + '.log')
        require(row['code'] == 0 and sha(log) == row['log_sha256'] and
                '1 passed; 0 failed; 0 ignored;' in log.read_text(), 'forced Rust suite')
    supplement = receipt('native-supplement-v1')
    tc = compiler['toolchain']
    require(supplement['sysroot'] == tc['path'], 'native supplement compiler path')
    protected = supplement['protected']
    sysroot = Path(tc['path'])
    require(protected[str(sysroot / 'bin/rustc')] == tc['rustc_sha256'] and
            protected[str(sysroot / 'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd')] == tc['wild_sha256'],
            'native supplement compiler/Wild bytes')
    for name, value in tc['drivers'].items():
        require(protected[str(sysroot / 'lib' / name)] == value, 'native supplement driver bytes')
    require(supplement['script_sha256'] == sha(root / 'controls/native_compiler_compatibility.py'), 'supplement control')
    require(len(supplement['cases']) == 6 and all(r['passed'] for r in supplement['cases']) and
            supplement['protected_unchanged'], 'compiler native cases')
    for row in supplement['commands']:
        p = remote(row['path'])
        require(sha(p) == row['sha256'] and load(p)['code'] == row['code'], 'native compiler command')
    rows = policy['records']
    require(len(rows) == 32 and len({r['label'] for r in rows}) == 32, 'policy case count')
    for row in rows:
        require(row['passed'] and row['returncode'] == row['expected_status'], 'policy status')
        for ext in ('stdout', 'stderr'):
            require(sha(root / 'evidence/cargo-policy-v1' / (row['label'] + '.' + ext)) == row[ext + '_sha256'], 'policy output')
        if row['argv_log_sha256']:
            require(sha(root / 'evidence/cargo-policy-v1' / (row['label'] + '.argv.jsonl')) == row['argv_log_sha256'], 'policy compiler argv')
        require(row['scratch_cleanup']['passed'] and not row['scratch_cleanup']['leftovers'], 'scratch cleanup')
        if 'runtime' in row:
            require(row['runtime']['stdout'] == '42\n', 'actual executable result')
    require(not receipt('cargo-v1')['passed'] and receipt('cargo-v1')['phase'] == 'routing-suite', 'retained Fresh failure')
    require(cargo['prior_failed_receipt_sha256'] == sha(root / 'evidence/cargo-v1/result.json'), 'failure custody')
    for name in ('compiler-v3', 'cargo-v2'):
        preserved = load(root / 'evidence' / name / 'protected-after.json')
        require(preserved['passed'] and not preserved['changed'], 'prior artifact preservation')
    require(compiler['protected_after_sha256'] == sha(root / 'evidence/compiler-v3/protected-after.json'),
            'compiler preservation receipt bytes')
    return {'passed': True, 'scope': 'Hash-verified recorded native execution, not fresh remote execution or a performance/adoption claim.',
            'rust_patch': RUST, 'cargo_patch': CARGO, 'rust_forced_suites': 3,
            'cargo_required_tests': sum(counts.values()), 'compiler_cases': 6,
            'compiler_command_records': len(supplement['commands']), 'cargo_policy_records': len(rows),
            'additional_inherited_dylib_assertion': cargo['additional_inherited_dylib_check']}


def final_execution(root):
    """Bind the separately rebuilt final Cargo without relabeling timed20b bytes."""
    compiler_path = root / 'evidence/compiler-v3/result.json'
    compiler = load(compiler_path)
    build_path = root / 'final-cargo/evidence/build.json'
    build = load(build_path)
    policy_root = root / 'final-cargo/native-evidence'
    policy = load(policy_root / 'result.json')
    require(build['passed'] and policy['passed'], 'final Cargo native execution')
    require(build['head'] == policy['head'] == FINAL_CARGO and
            build['patch_sha256'] == policy['patch_sha256'] == FINAL_PATCH, 'final Cargo source')
    require(sha(root / 'inputs/cargo-final.patch') == FINAL_PATCH, 'final patch bytes')
    manifest = load(root / 'inputs/cargo-final-manifest.json')
    require(manifest['head'] == FINAL_CARGO and manifest['patch_sha256'] == FINAL_PATCH and
            len(manifest['files']) == 14, 'final source manifest')
    require(build['manifest_sha256'] == sha(root / 'inputs/cargo-final-manifest.json') and
            build['source_manifest_sha256'] == sha(root / 'final-cargo/evidence/source-files.json') and
            load(root / 'final-cargo/evidence/source-files.json') == manifest, 'final built source files')
    require(build['compiler_build_sha256'] == policy['compiler_build_sha256'] == sha(compiler_path) and
            policy['build_receipt_sha256'] == sha(build_path), 'final native compiler/build binding')
    require(build['script_sha256'] == sha(root / 'controls/build-final-cargo.py') and
            policy['script_sha256'] == sha(root / 'controls/native_final_cargo.py'), 'final controls')
    require(build['cargo'] == policy['cargo'] and
            build['toolchain'] == {**compiler['toolchain'], 'cargo_sha256': build['cargo']['sha256']},
            'final standalone Cargo identity')
    require(build['cargo']['path'] == str(REMOTE / 'final-cargo/bin/cargo'), 'standalone Cargo path')
    require(FINAL_CARGO in build['cargo']['version'], 'final Cargo version capture')
    # This binds the ordering gate only. The separate performance archive verifies raw timing data.
    handover_path = root / 'final-cargo/measurement-handover.json'
    collection_path = root / 'anchors/performance-collection.json'
    handover, collection = load(handover_path), load(collection_path)
    require(handover['passed'] and collection['passed'] and
            collection['counts'] == {'commands': 90, 'accepted': 90, 'excluded': 0} and
            build['handover_sha256'] == sha(handover_path) and
            build['collection_sha256'] == handover['collection_sha256'] == sha(collection_path) and
            handover['verified_files'] == collection['file_count'] and
            handover['verified_bytes'] == collection['total_bytes'], 'final build after verified collection')
    expected = {'selection-units': 4, 'provenance-units': 1, 'wrapper-range': 1, 'routing-suite': 6,
                'corrected-dylib': 1, 'ordinary-bad-config': 1, 'ordinary-target-env': 1}
    found = {}
    for row in build['commands']:
        log = root / 'final-cargo/evidence' / (row['name'] + '.log')
        require(sha(log) == row['log_sha256'] and row['code'] == 0, 'final build/test command')
        if row['name'] in expected:
            require(f"{expected[row['name']]} passed; 0 failed; 0 ignored;" in log.read_text(),
                    'final required test execution')
            require(row['name'] not in found, 'duplicate final test group')
            found[row['name']] = expected[row['name']]
    require(found == expected, 'final test set')
    preserved = load(root / 'final-cargo/evidence/protected-after.json')
    require(preserved['passed'] and not preserved['changed'] and policy['protected_unchanged'],
            'measured artifacts unchanged after final proof')
    protected = policy['protected']
    tc = compiler['toolchain']
    sysroot = Path(tc['path'])
    identities = {'bin/rustc': tc['rustc_sha256'], 'bin/rustdoc': tc['rustdoc_sha256'],
                  'bin/cargo': load(root / 'evidence/cargo-v2/result.json')['cargo']['sha256'],
                  'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd': tc['wild_sha256'],
                  'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/compact-artifacts-v2': tc['marker']['sha256']}
    identities.update({'lib/' + k: v for k, v in tc['drivers'].items()})
    for relative, value in identities.items():
        require(protected[str(sysroot / relative)] == value, 'final protected toolchain identity')
    require(protected[build['cargo']['path']] == build['cargo']['sha256'], 'protected standalone Cargo')
    lld_path = root / 'evidence/lld-assembly-v1/result.json'
    require(policy['lld_assembly_sha256'] == sha(lld_path), 'final LLD assembly binding')
    for path, record in load(lld_path)['files'].items():
        require(protected[path] == record['sha256'], 'final LLD bytes')
    cases = {'ordinary': (False, False), 'default': (True, True), 'optout': (False, False),
             'response-fallback': (False, False), 'lld-adapter': (True, False)}
    rows = policy['records']
    require(len(rows) == len(cases) and {r['label'] for r in rows} == set(cases), 'final native case set')
    for row in rows:
        label = row['label']
        compact, direct = cases[label]
        require(row['passed'] and row['returncode'] == 0 and row['runtime'] == '42\n' and
                not row['scratch_leftovers'], 'final executable/cleanup result')
        require(row['expected_compact'] == compact and row['expected_direct_reader'] == direct and
                (row['archive']['compact_members'] > 0) == compact, 'final storage mode')
        for ext in ('stdout', 'stderr'):
            require(sha(policy_root / (label + '.' + ext)) == row[ext + '_sha256'], 'final native output')
        argv_path = policy_root / (label + '.argv.jsonl')
        require(sha(argv_path) == row['argv_log_sha256'], 'final native argv bytes')
        units = [a for a in map(json.loads, argv_path.read_text().splitlines()) if
                 '--crate-name' in a and a[a.index('--crate-name') + 1] == 'final_app']
        require(len(units) == 1 and ('-Zcompact-artifacts=yes' in units[0]) == compact and
                ('-Zcompact-artifacts-linker=yes' in units[0]) == direct, 'final compiler selection')
        if label in ('ordinary', 'response-fallback', 'lld-adapter'):
            require(not any('wild-ld' in a for a in units[0]), 'unexpected generated Wild override')
    return {'head': FINAL_CARGO, 'patch_sha256': FINAL_PATCH, 'required_tests': sum(found.values()),
            'native_cases': len(rows), 'standalone_cargo_sha256': build['cargo']['sha256'],
            'scope': 'Separate final Cargo correctness confirmation; frozen20b timings retain their own identity.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    root, seal = extract(args.archive, args.manifest, args.destination)
    result = recorded_execution(root)
    result['final_cargo'] = final_execution(root)
    result.update(archive_sha256=seal['archive_sha256'], inventory_sha256=seal['inventory_sha256'], members=seal['members'])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
