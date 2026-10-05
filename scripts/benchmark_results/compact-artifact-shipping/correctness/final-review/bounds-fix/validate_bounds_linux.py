#!/usr/bin/env python3
"""Narrow functional follow-up after the reviewed raw-metadata allocation bound fix."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-after-benchmark-handover', action='store_true', required=True)
    parser.parse_args()
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
    root = Path('/home/dev-user/code/oss/ohm-compact-study')
    ship = root / 'shipping'
    inputs = Path(__file__).resolve().parent
    previous_inputs = inputs.parent / 'final-review-inputs'
    helper = load('validation_helpers', previous_inputs / 'validate_final_linux.py')
    digest, out, save = helper.digest, helper.out, helper.save
    manifest = json.loads((inputs / 'inputs.json').read_text())
    heads, bases = manifest['sources'], manifest['bases']
    for name, checksum in manifest['sha256'].items():
        assert Path(name).name == name and digest(inputs / name) == checksum
    status = json.loads((ship / 'evidence/line-matrix/status.json').read_text())
    assert status['status'] == 'completed' and status['samples'] == 312
    assert (ship / 'evidence/benchmark-transfer-manifest.json').is_file()
    prior = ship / 'final-review'
    previous = json.loads((prior / 'evidence/validation.json').read_text())
    assert previous['passed'] and previous['measured_artifacts_unchanged'] and previous['sources'] == bases
    original_path = prior / 'evidence/measured-artifacts-after.json'
    original = json.loads(original_path.read_text())
    protection = json.loads((prior / 'evidence/preservation-summary.json').read_text())
    assert digest(original_path) == protection['after_sha256']
    sources = {'rust': root / 'rust', 'wild': root / 'wild', 'cargo': ship / 'cargo'}
    for name, path in sources.items():
        helper.verify_checkout(path, bases[name])
    assert heads['cargo'] == bases['cargo']
    assert out(['git', 'rev-parse', 'HEAD'], sources['rust'] / 'src/tools/cargo') == heads['cargo']
    refs = {'rust': 'refs/heads/charlie/compact-format-shipping',
            'wild': 'refs/heads/charlie/compact-format-stable'}
    for name, ref in refs.items():
        bundle = inputs / f'{name}.bundle'
        subprocess.run(['git', 'bundle', 'verify', str(bundle)], cwd=sources[name], check=True)
        assert out(['git', 'bundle', 'list-heads', bundle, ref], sources[name]) == f'{heads[name]} {ref}'
    review = prior / 'bounds-fix'
    sysroot = root / 'toolchains/compact-final-review-bounds'
    assert not review.exists() and not sysroot.exists()
    review.mkdir()
    evidence = review / 'evidence'
    evidence.mkdir()
    cargo = prior / 'bin/cargo'
    assert digest(cargo) == previous['cargo']['sha256']
    measured = root / 'toolchains/compact-shipping'
    protected_roots = [measured, ship / 'bin/cargo', ship / 'wild-release']
    prior_drivers = {p: digest(p) for p in (root / 'toolchains/compact-final-review/lib').glob('librustc_driver-*.so')}
    receipt = {'passed': False, 'started': time.time(), 'sources': heads, 'previous_sources': bases,
               'shared_compact_tree': manifest['shared_compact_tree'], 'commands': [], 'inputs': manifest,
               'scope': 'Raw-metadata allocation-bound follow-up: shared unit tests, forced compiler suites, compact Wild and ordinary-linker interoperability; no timing/lifecycle/worktree rerun',
               'previous_validation_sha256': digest(prior / 'evidence/validation.json'),
               'protection_baseline_sha256': digest(original_path), 'production_pgo_bolt': False}
    env = {key: value for key, value in os.environ.items() if not key.startswith((
        'RUSTFLAGS', 'RUSTC', 'RUSTDOC', 'CARGO_PROFILE_', 'CARGO_TARGET_', 'CARGO_UNSTABLE_',
        'CARGO_ENCODED_', 'CARGO_BUILD_', 'RUSTUP_TOOLCHAIN'))}
    env.update(CARGO_HOME='/tmp/codex-cargo-home', CARGO_BUILD_JOBS='6')
    def run(name, argv, cwd=root, extra=None):
        path = evidence / f'{name}.log'
        assert not path.exists()
        row = {'name': name, 'argv': list(map(str, argv)), 'cwd': str(cwd),
               'log': str(path), 'environment_overrides': extra or {}, 'started': time.time()}
        receipt['commands'].append(row)
        try:
            with path.open('w') as log:
                result = subprocess.run(row['argv'], cwd=cwd, env={**env, **(extra or {})},
                                        stdout=log, stderr=subprocess.STDOUT, text=True)
            row['exit_code'] = result.returncode
            assert result.returncode == 0, f'{name} failed: {path}'
        finally:
            row['seconds'] = time.time() - row['started']
            save(evidence / 'validation.json', receipt)
        print(f'{name} passed ({row["seconds"]:.1f}s)', flush=True)
        return path.read_text()
    try:
        for name, ref in refs.items():
            run(f'{name}-fetch', ['git', 'fetch', '--no-tags', '--no-recurse-submodules',
                                  inputs / f'{name}.bundle', ref], sources[name])
            run(f'{name}-fast-forward', ['git', '-c', 'submodule.recurse=false', 'merge',
                                         '--ff-only', '--no-edit', heads[name]], sources[name])
        for name, path in sources.items():
            helper.verify_checkout(path, heads[name])
        assert out(['git', 'rev-parse', 'HEAD:compact-artifact'], sources['wild']) == manifest['shared_compact_tree']
        assert out(['git', 'rev-parse', 'HEAD:src/tools/cargo'], sources['rust']) == heads['cargo']
        wild_cache = ship / '.wild-release-build'
        unit_log = run('compact-unit', ['rustup', 'run', '1.97.1', 'cargo', 'test', '--locked', '--release',
                       '--target', helper.TARGET, '-p', 'compact-artifact', '--lib'], sources['wild'],
                       {'CARGO_TARGET_DIR': str(wild_cache)})
        assert re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', unit_log) == [('15', '0', '0')]
        receipt['compact_unit'] = {'passed': 15, 'failed': 0, 'ignored': 0}
        regression_log = run('raw-metadata-regression', ['rustup', 'run', '1.97.1', 'cargo', 'test',
                             '--locked', '--release', '--target', helper.TARGET, '-p', 'compact-artifact',
                             '--test', 'raw_metadata'], sources['wild'], {'CARGO_TARGET_DIR': str(wild_cache)})
        assert re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', regression_log) == [('1', '0', '0')]
        assert 'raw_metadata_length_is_checked_before_copying ... ok' in regression_log
        receipt['raw_metadata_regression'] = {'passed': 1, 'failed': 0, 'ignored': 0,
                                              'name': 'raw_metadata_length_is_checked_before_copying'}
        wild_manifest = json.loads((prior / 'source-manifest.json').read_text())
        wild_manifest['bundled_tools']['wild']['source']['revision'] = heads['wild']
        save(review / 'source-manifest.json', wild_manifest)
        (review / '.wild-release-build').symlink_to(wild_cache, target_is_directory=True)
        payload = review / 'wild-release'
        run('wild-source-build', ['python3', previous_inputs / 'prepare-wild.py', review / 'source-manifest.json',
                                  helper.TARGET, payload, '--source-checkout', sources['wild']],
                                  sources['wild'], {'CARGO_BUILD_JOBS': '4'})
        assert (payload / 'compact-artifacts-v1').read_bytes() == b'RCOBJ001\n'
        assert json.loads((payload / 'provenance.json').read_text())['binary_sha256'] == digest(payload / 'wild')
        target = Path('/tmp/codex-cargo-targets/ohm/isolated/compact-objects')
        bootstrap = target / 'bootstrap'
        common = ['--stage', '1', '--set', 'build.submodules=false', '--set',
                  f'target.{helper.TARGET}.ohm-wild-linker={payload}']
        overrides = {'CARGO_TARGET_DIR': str(bootstrap)}
        run('compiler-build', ['python3', 'x.py', 'build', *common, 'compiler/rustc',
                               'src/tools/rustdoc', 'library'], sources['rust'], overrides)
        test_log = run('compiler-run-make', ['python3', 'x.py', 'test', *common, '--force-rerun',
                       'tests/run-make/compact-artifact-exports', 'tests/run-make/public-api-hash-artifact'],
                       sources['rust'], overrides)
        assert re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', test_log) == [('2', '0', '0')]
        receipt['forced_run_make'] = {'passed': 2, 'failed': 0, 'ignored': 0, 'force_rerun': True}
        stage = bootstrap / helper.TARGET / 'stage1'
        assert list((stage / f'lib/rustlib/{helper.TARGET}/lib').glob('libstd-*.rlib'))
        run('copy-sysroot', ['cp', '-aL', '--reflink=auto', stage, sysroot])
        linker = sysroot / f'lib/rustlib/{helper.TARGET}/bin/wild-ld'
        linker.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload / 'wild', linker / 'ld.bfd')
        shutil.copy2(payload / 'compact-artifacts-v1', linker / 'compact-artifacts-v1')
        build = {'passed': True, 'sources': heads, 'shared_compact_tree': manifest['shared_compact_tree'],
                 'sysroot': str(sysroot), 'version': out([sysroot / 'bin/rustc', '-vV']),
                 'rustdoc_sha256': digest(sysroot / 'bin/rustdoc'), 'wild_sha256': digest(linker / 'ld.bfd'),
                 'drivers': {p.name: digest(p) for p in (sysroot / 'lib').glob('librustc_driver-*.so')},
                 'cargo': previous['cargo'], 'production_pgo_bolt': False}
        assert build['drivers']
        save(evidence / 'compiler-build.json', build)
        case = review / 'interop'
        (case / 'src').mkdir(parents=True)
        (case / 'Cargo.toml').write_text('[package]\nname="bounds-interop"\nversion="0.1.0"\nedition="2021"\n[workspace]\n')
        (case / 'src/lib.rs').write_text('#[inline(never)] pub fn value() -> u32 { 42 }\n')
        (case / 'src/main.rs').write_text('fn main() { let n = bounds_interop::value(); assert_eq!(n,42); println!("{n}"); }\n')
        case_target = target / 'final-review/bounds-interop'
        assert not case_target.exists()
        case_env = {'RUSTC': str(sysroot / 'bin/rustc'), 'RUSTDOC': str(sysroot / 'bin/rustdoc'),
                    'CARGO_TARGET_DIR': str(case_target), 'CARGO_BUILD_BUILD_DIR': str(case_target.parent / 'bounds-shared'),
                    'CARGO_INCREMENTAL': '1', 'CARGO_TERM_COLOR': 'never'}
        run('compact-cargo-run', [cargo, '-Zohm-defaults=yes', '-Zohm-compact-artifacts=yes', 'run', '--offline'], case, case_env)
        rlib = case_target / 'debug/libbounds_interop.rlib'
        archive = load('archive_reader', previous_inputs / 'alignment_correctness.py')
        members = sum(data.startswith(b'RCOBJ001') for _, data in archive.archive_members(rlib))
        assert members > 0
        binary = case_target / 'debug/bounds-interop'
        assert run('compact-runtime', [binary]).strip() == '42'
        assert 'Wild' in run('compact-linker-identity', ['readelf', '--string-dump=.comment', binary])
        ordinary = case / 'ordinary-consumer'
        run('ordinary-consumer-build', [sysroot / 'bin/rustc', '--edition=2021', case / 'src/main.rs',
                                       '--extern', f'bounds_interop={rlib}', '-C', 'linker-features=-lld',
                                       '-o', ordinary], case)
        assert run('ordinary-consumer-runtime', [ordinary]).strip() == '42'
        receipt['interop'] = {'compact_members': members, 'compact_runtime': 42, 'linker': 'Wild',
                              'ordinary_bfd_consumer_runtime': 42, 'rlib_sha256': digest(rlib)}
        for name, path in sources.items():
            helper.verify_checkout(path, heads[name])
        receipt['passed'] = True
    except BaseException as error:
        receipt['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        after = helper.snapshot(protected_roots)
        save(evidence / 'measured-artifacts-after.json', after)
        receipt['measured_artifacts_unchanged'] = original == after
        receipt['prior_review_drivers_unchanged'] = all(digest(p) == checksum for p, checksum in prior_drivers.items())
        receipt['prior_review_cargo_unchanged'] = digest(cargo) == previous['cargo']['sha256']
        receipt['finished'] = time.time()
        unchanged = all(receipt[key] for key in ['measured_artifacts_unchanged',
                        'prior_review_drivers_unchanged', 'prior_review_cargo_unchanged'])
        if not unchanged:
            receipt['passed'] = False
        save(evidence / 'validation.json', receipt)
        assert unchanged, 'Protected measured or prior-review artifacts changed'
    print(json.dumps({'passed': True, 'receipt': str(evidence / 'validation.json')}), flush=True)


if __name__ == '__main__':
    main()
