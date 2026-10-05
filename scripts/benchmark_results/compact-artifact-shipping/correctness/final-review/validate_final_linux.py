#!/usr/bin/env python3
"""Run only after root hands the devbox over following benchmark collection.

Reuse build intermediates, but never replace the measured toolchains or Cargo.
This is final-source functional validation, not a new performance measurement.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

TARGET = 'x86_64-unknown-linux-gnu'
HEADS = {
    'rust': 'd59f1c63326e874185ed4ec5bb052f384745110f',
    'wild': '9fbf96f8b0ced108ea3f90c2341a289b16363ff7',
    'cargo': '4a2813050da607ca5cfe7b5cf3a17ba7c9676be1',
}
BASES = {
    'rust': 'e55e0485efc397741f4aaf861f1c74a281ac902f',
    'wild': 'dba82ebe99d98adbfe6358215d456cdddb1877da',
    'cargo': '207626090e1fb9b405abd806a86c1b42bd2db5ff',
}
REFS = {
    'rust': 'refs/heads/charlie/compact-format-shipping',
    'wild': 'refs/heads/charlie/compact-format-stable',
    'cargo': 'refs/heads/charlie/compact-artifact-cargo-opt-in',
}
SHARED_TREE = '87dad1ac8aab2b7bf757bb607cef25196f4c66fb'


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def out(argv, cwd=None):
    return subprocess.check_output(list(map(str, argv)), cwd=cwd, text=True).strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def snapshot(roots):
    result = {}
    for root in roots:
        assert root.exists(), root
        for path in sorted(root.rglob('*')) if root.is_dir() else [root]:
            if path.is_file():
                result[str(path)] = {'sha256': digest(path), 'bytes': path.stat().st_size}
                if path.is_symlink():
                    result[str(path)]['symlink'] = os.readlink(path)
    return result


def verify_checkout(path, head):
    assert path.resolve() == path
    assert out(['git', 'rev-parse', '--show-toplevel'], path) == str(path)
    assert out(['git', 'config', 'user.email'], path) == 'charlie.r.marsh@gmail.com'
    assert out(['git', 'rev-parse', 'HEAD'], path) == head, path
    assert not out(['git', 'status', '--porcelain', '--ignore-submodules=all'], path), path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=Path('/home/dev-user/code/oss/ohm-compact-study'))
    parser.add_argument('--execute-after-benchmark-handover', action='store_true', required=True)
    args = parser.parse_args()
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
    root = args.study.resolve()
    ship = root / 'shipping'
    status_path = ship / 'evidence/line-matrix/status.json'
    status = json.loads(status_path.read_text())
    assert status['status'] == 'completed' and status['samples'] == 312, status
    transfer_manifest = ship / 'evidence/benchmark-transfer-manifest.json'
    assert transfer_manifest.is_file(), 'benchmark evidence must be collected first'
    inputs = Path(__file__).resolve().parent
    review = ship / 'final-review'
    sysroot = root / 'toolchains/compact-final-review'
    target_root = Path('/tmp/codex-cargo-targets/ohm/isolated/compact-objects')
    bootstrap = target_root / 'bootstrap'
    sources = {'rust': root / 'rust', 'wild': root / 'wild', 'cargo': ship / 'cargo'}
    nested_cargo = sources['rust'] / 'src/tools/cargo'
    for name, path in sources.items():
        verify_checkout(path, BASES[name])
    verify_checkout(nested_cargo, BASES['cargo'])
    assert not review.exists() and not sysroot.exists()
    assert bootstrap.is_dir() and (ship / '.wild-release-build').is_dir()
    assert shutil.disk_usage(root).free > 5 * 1024**3
    manifests = json.loads((inputs / 'inputs.json').read_text())
    assert manifests['sources'] == HEADS and manifests['bases'] == BASES
    for name, checksum in manifests['sha256'].items():
        assert Path(name).name == name and digest(inputs / name) == checksum, name
    for name, path in sources.items():
        bundle = inputs / f'{name}.bundle'
        subprocess.run(['git', 'bundle', 'verify', str(bundle)], cwd=path, check=True)
        assert out(['git', 'bundle', 'list-heads', bundle, REFS[name]], path) == f'{HEADS[name]} {REFS[name]}'
    measured = root / 'toolchains/compact-shipping'
    measured_roots = [measured, ship / 'bin/cargo', ship / 'wild-release']
    original = snapshot(measured_roots)
    previous = json.loads((ship / 'evidence/compiler-shipping-final.json').read_text())
    assert previous['sources'] == BASES
    for name, checksum in previous['drivers'].items():
        assert digest(measured / 'lib' / name) == checksum
    assert digest(ship / 'bin/cargo') == '230b28d5eacdad73f11106d2878b52384a9c2ba61053b0939e1254df717ff013'
    assert digest(ship / 'wild-release/wild') == previous['wild_sha256']
    review.mkdir()
    evidence = review / 'evidence'
    evidence.mkdir()
    save(evidence / 'measured-artifacts-before.json', original)
    receipt = {'passed': False, 'started': time.time(), 'sources': HEADS, 'previous_sources': BASES,
               'shared_compact_tree': SHARED_TREE, 'commands': [], 'sysroot': str(sysroot),
               'scope': 'Final-source functional validation only; measured binaries and timing data preserved',
               'inputs': manifests, 'production_pgo_bolt': False,
               'free_bytes_before': shutil.disk_usage(root).free,
               'benchmark_handover': {'status': status, 'status_sha256': digest(status_path),
                                      'transfer_manifest_sha256': digest(transfer_manifest)}}
    save(evidence / 'validation.json', receipt)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('RUSTFLAGS', 'RUSTC_LOG', 'CARGO_ENCODED_RUSTFLAGS', 'CARGO_UNSTABLE_'))}
    for name in ['RUSTC', 'RUSTDOC', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CARGO_BUILD_BUILD_DIR',
                 'CARGO_TARGET_DIR', 'RUSTUP_TOOLCHAIN', 'CFG_OMIT_GIT_HASH']:
        environment.pop(name, None)
    environment.update(CARGO_HOME='/tmp/codex-cargo-home', CARGO_BUILD_JOBS='6')

    def run(name, argv, cwd=root, extra=None):
        command = list(map(str, argv))
        logpath = evidence / f'{name}.log'
        assert not logpath.exists()
        row = {'name': name, 'argv': command, 'cwd': str(cwd), 'log': str(logpath),
               'environment_overrides': extra or {}, 'started': time.time()}
        receipt['commands'].append(row)
        try:
            with logpath.open('w') as log:
                result = subprocess.run(command, cwd=cwd, env={**environment, **(extra or {})},
                                        stdout=log, stderr=subprocess.STDOUT, text=True)
            row['exit_code'] = result.returncode
            assert result.returncode == 0, f'{name} failed: {logpath}'
        finally:
            row['seconds'] = time.time() - row['started']
            save(evidence / 'validation.json', receipt)
        print(f'{name} passed ({row["seconds"]:.1f}s)', flush=True)
        return logpath

    try:
        for name, path in sources.items():
            run(f'{name}-fetch', ['git', '-c', 'fetch.recurseSubmodules=false', 'fetch', '--no-tags',
                                 '--no-recurse-submodules', inputs / f'{name}.bundle', REFS[name]], path)
            run(f'{name}-fast-forward', ['git', '-c', 'submodule.recurse=false', 'merge', '--ff-only',
                                         '--no-edit', HEADS[name]], path)
        run('nested-cargo-fetch', ['git', 'fetch', '--no-tags', '--no-recurse-submodules',
                                  inputs / 'cargo.bundle', REFS['cargo']], nested_cargo)
        run('nested-cargo-pin', ['git', '-c', 'submodule.recurse=false', 'checkout', '--detach',
                                HEADS['cargo']], nested_cargo)
        for name, path in sources.items():
            verify_checkout(path, HEADS[name])
        verify_checkout(nested_cargo, HEADS['cargo'])
        assert out(['git', 'rev-parse', 'HEAD:src/tools/cargo'], sources['rust']) == HEADS['cargo']
        assert out(['git', 'rev-parse', 'HEAD:compact-artifact'], sources['wild']) == SHARED_TREE
        manifest = json.loads((ship / 'release-tools/stable-source-manifest.json').read_text())
        assert manifest['bundled_tools']['wild']['source']['revision'] == BASES['wild']
        manifest['bundled_tools']['wild']['source']['revision'] = HEADS['wild']
        save(review / 'source-manifest.json', manifest)
        # Reuse only the build cache; the measured prepared payload stays untouched.
        (review / '.wild-release-build').symlink_to(ship / '.wild-release-build', target_is_directory=True)
        payload = review / 'wild-release'
        run('wild-source-build', ['python3', inputs / 'prepare-wild.py', review / 'source-manifest.json',
                                  TARGET, payload, '--source-checkout', sources['wild']],
            sources['wild'], {'CARGO_BUILD_JOBS': '4'})
        assert (payload / 'compact-artifacts-v1').read_bytes() == b'RCOBJ001\n'
        assert json.loads((payload / 'provenance.json').read_text())['binary_sha256'] == digest(payload / 'wild')
        for name in ['LICENSE-MIT', 'LICENSE-APACHE']:
            assert (payload / name).read_bytes() == (sources['wild'] / name).read_bytes()
        cargo_target = target_root / 'shipping-cargo'
        # Cargo's build script does not watch Git HEAD; test-only commits can
        # otherwise leave the old embedded version in an up-to-date executable.
        build_script = sources['cargo'] / 'build.rs'
        build_script_hash = digest(build_script)
        run('cargo-refresh-version', ['touch', build_script])
        assert digest(build_script) == build_script_hash
        run('cargo-build', ['cargo', '+ohm', '-Zohm-defaults=no', 'build', '--locked', '--release',
                            '--features', 'ohm-defaults', '--bin', 'cargo'], sources['cargo'],
            {'CARGO_TARGET_DIR': str(cargo_target)})
        (review / 'bin').mkdir()
        cargo = review / 'bin/cargo'
        shutil.copy2(cargo_target / 'release/cargo', cargo)
        cargo_version = out([cargo, '-vV'])
        assert HEADS['cargo'] in cargo_version
        receipt['cargo'] = {'path': str(cargo), 'sha256': digest(cargo), 'version': cargo_version}
        common = ['--stage', '1', '--set', 'build.submodules=false', '--set',
                  f'target.{TARGET}.ohm-wild-linker={payload}']
        build_env = {'CARGO_TARGET_DIR': str(bootstrap)}
        run('compiler-build', ['python3', 'x.py', 'build', *common, 'compiler/rustc',
                               'src/tools/rustdoc', 'library'], sources['rust'], build_env)
        logpath = run('compiler-run-make', ['python3', 'x.py', 'test', *common, '--force-rerun',
                      'tests/run-make/compact-artifact-exports', 'tests/run-make/public-api-hash-artifact'],
                      sources['rust'], build_env)
        summaries = re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', logpath.read_text())
        assert summaries == [('2', '0', '0')], summaries
        receipt['forced_run_make'] = {'passed': 2, 'failed': 0, 'ignored': 0, 'force_rerun': True}
        stage = bootstrap / TARGET / 'stage1'
        assert (stage / 'bin/rustdoc').is_file()
        assert list((stage / f'lib/rustlib/{TARGET}/lib').glob('libstd-*.rlib'))
        run('copy-final-sysroot', ['cp', '-aL', '--reflink=auto', stage, sysroot])
        binrel = Path(f'lib/rustlib/{TARGET}/bin')
        linker = sysroot / binrel / 'wild-ld'
        linker.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload / 'wild', linker / 'ld.bfd')
        shutil.copy2(payload / 'compact-artifacts-v1', linker / 'compact-artifacts-v1')
        for name in ['rust-lld', 'gcc-ld']:
            target = sysroot / binrel / name
            if not target.exists():
                source = measured / binrel / name
                if source.is_dir():
                    shutil.copytree(source, target, symlinks=False)
                else:
                    shutil.copy2(source, target)
        assert digest(linker / 'ld.bfd') == digest(payload / 'wild')
        build = {'passed': True, 'time': time.time(), 'sources': HEADS, 'sysroot': str(sysroot),
                 'version': out([sysroot / 'bin/rustc', '-vV']),
                 'rustdoc_sha256': digest(sysroot / 'bin/rustdoc'),
                 'wild_sha256': digest(linker / 'ld.bfd'), 'marker': 'RCOBJ001',
                 'drivers': {p.name: digest(p) for p in (sysroot / 'lib').glob('librustc_driver-*.so')},
                 'shared_compact_tree': SHARED_TREE, 'production_pgo_bolt': False,
                 'forced_run_make': receipt['forced_run_make']}
        assert build['drivers']
        save(evidence / 'compiler-build.json', build)
        run('cargo-lifecycle', ['python3', inputs / 'cargo_lifecycle.py', '--cargo', cargo,
            '--rustc', sysroot / 'bin/rustc', '--rustdoc', sysroot / 'bin/rustdoc',
            '--source-root', review / 'cargo-lifecycle', '--target-root', target_root / 'final-review/cargo-lifecycle',
            '--output', evidence / 'cargo-lifecycle.json'])
        assert json.loads((evidence / 'cargo-lifecycle.json').read_text())['passed']
        run('alignment-correctness', ['python3', inputs / 'alignment_correctness.py', '--study', root,
            '--rustc', sysroot / 'bin/rustc', '--target', target_root / 'final-review/alignment',
            '--receipt', evidence / 'alignment-correctness.json', '--cc', 'clang', '--ar', 'ar',
            '--lld', sysroot / binrel / 'rust-lld', '--build-receipt', evidence / 'compiler-build.json'])
        assert json.loads((evidence / 'alignment-correctness.json').read_text())['passed']
        for name, path in sources.items():
            verify_checkout(path, HEADS[name])
        verify_checkout(nested_cargo, HEADS['cargo'])
        receipt['passed'] = True
    except BaseException as error:
        receipt['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        after = snapshot(measured_roots)
        save(evidence / 'measured-artifacts-after.json', after)
        receipt['measured_artifacts_unchanged'] = original == after
        receipt['finished'] = time.time()
        if original != after:
            receipt['passed'] = False
        save(evidence / 'validation.json', receipt)
        assert original == after, 'Measured artifacts changed during final validation'
    print(json.dumps({'passed': True, 'receipt': str(evidence / 'validation.json')}), flush=True)


if __name__ == '__main__':
    main()
