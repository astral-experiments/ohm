#!/usr/bin/env python3
"""Exercise the shipping Cargo opt-in with real compact artifacts (not a timing test).

Requires Linux, a candidate rustc/rustdoc sysroot with the matching bundled Wild
and its capability marker, and itoa 1.0.15 already available in CARGO_HOME. Uses
only fresh, explicitly supplied fixture/target directories; never removes them
itself. Cargo clean is deliberately exercised inside those owned fixtures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def archive_members(path):
    """Read ar payload prefixes, accounting for GNU/BSD long member names."""
    with path.open('rb') as stream:
        assert stream.read(8) == b'!<arch>\n', f'not a self-contained ar: {path}'
        while header := stream.read(60):
            assert len(header) == 60 and header[58:] == b'`\n', path
            size = int(header[48:58])
            start = stream.tell()
            name = header[:16].strip()
            if name.startswith(b'#1/'):
                name_size = int(name[3:])
                assert 0 <= name_size <= size, path
                stream.seek(name_size, 1)
            yield stream.read(min(8, start + size - stream.tell()))
            stream.seek(start + size + (size % 2))


def storage(root):
    seen, allocated, logical = set(), 0, 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not Path(directory, name).is_symlink()]
        for path in [Path(directory), *(Path(directory, name) for name in files)]:
            stat = path.lstat()
            inode = stat.st_dev, stat.st_ino
            if path.is_symlink() or inode in seen:
                continue
            seen.add(inode)
            allocated += stat.st_blocks * 512
            logical += stat.st_size
    return {'unique_inodes': len(seen), 'allocated_bytes': allocated, 'logical_bytes': logical}


class Study:
    def __init__(self, args):
        self.args = args
        self.records = []
        self.result = {'passed': False, 'records': self.records}
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith(('CARGO_PROFILE_', 'CARGO_TARGET_', 'CARGO_UNSTABLE_')) or key in (
                'RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'RUSTDOCFLAGS',
                'CARGO_ENCODED_RUSTDOCFLAGS', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER',
            ):
                self.env.pop(key)
        self.settings = {
            'CARGO': str(args.cargo), 'RUSTC': str(args.rustc), 'RUSTDOC': str(args.rustdoc),
            'CARGO_HOME': str(args.cargo_home), 'CARGO_INCREMENTAL': '1',
            'CARGO_BUILD_BUILD_DIR': str(args.target_root / 'shared-build'),
            'CARGO_TERM_COLOR': 'never', 'CARGO_BUILD_JOBS': '4',
        }
        self.env.update(self.settings)
        self.result['environment'] = self.settings

    def save(self):
        self.args.output.write_text(json.dumps(self.result, indent=2) + '\n')

    def run(self, label, command, fixture=None, expect=0):
        command = list(map(str, command))
        cwd = self.args.source_root / fixture if fixture else self.args.source_root
        environment = dict(self.env)
        if fixture:
            environment['CARGO_TARGET_DIR'] = str(self.args.target_root / fixture)
        start = time.monotonic()
        result = subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True)
        self.records.append({
            'label': label, 'command': command, 'cwd': str(cwd),
            'target': environment.get('CARGO_TARGET_DIR'),
            'returncode': result.returncode, 'seconds': time.monotonic() - start,
            'stdout': result.stdout, 'stderr': result.stderr,
        })
        self.save()
        assert result.returncode == expect, f'{label}: {result.stderr}'
        return result

    def cargo(self, label, fixture, compact, *command, expect=0):
        return self.run(label, [
            self.args.cargo, '-Zohm-defaults=yes',
            '-Zohm-compact-artifacts=' + ('yes' if compact else 'no'), *command,
        ], fixture, expect)

    def build(self, label, fixture, compact):
        result = self.cargo(label, fixture, compact, 'build', '--locked', '--offline', '-vv',
                            '--message-format=json')
        artifacts = [json.loads(line) for line in result.stdout.splitlines()
                     if line.startswith('{') and json.loads(line).get('reason') == 'compiler-artifact']
        assert artifacts, label
        libraries = {}
        for artifact in artifacts:
            for filename in artifact['filenames']:
                if filename.endswith('.rlib'):
                    prefixes = list(archive_members(Path(filename)))
                    has_compact = b'RCOBJ001' in prefixes
                    assert has_compact == compact, f'{label}: wrong format in {filename}'
                    libraries[artifact['target']['name']] = filename
        assert {'itoa', 'dep', 'compact_lifecycle'} <= libraries.keys(), (label, libraries)
        self.records[-1]['selected_libraries'] = libraries
        self.records[-1]['all_fresh'] = all(artifact['fresh'] for artifact in artifacts)
        self.save()
        return result, artifacts, libraries

    def binary(self, label, fixture, expected):
        result = self.run(label, [self.args.target_root / fixture / 'debug/compact-lifecycle'], fixture)
        assert result.stdout.strip() == str(expected), result.stdout

    def fixture(self, name):
        root = self.args.source_root / name
        (root / 'src').mkdir(parents=True)
        (root / 'dep/src').mkdir(parents=True)
        (root / 'Cargo.toml').write_text('''[package]
name = "compact-lifecycle"
version = "0.1.0"
edition = "2024"
[workspace]
members = ["dep"]
[dependencies]
dep = { path = "dep" }
itoa = "=1.0.15"
''')
        (root / 'dep/Cargo.toml').write_text('''[package]
name = "dep"
version = "0.1.0"
edition = "2024"
''')
        (root / 'dep/src/lib.rs').write_text('fn private() -> u64 { 42 }\npub fn answer() -> u64 { private() }\n')
        (root / 'src/lib.rs').write_text('''/// Exercise rustdoc linking against a compact dependency.
/// ```
/// assert!(compact_lifecycle::answer() > 0);
/// ```
pub fn answer() -> u64 { dep::answer().into() }
#[test]
fn positive() { assert!(answer() > 0); }
''')
        (root / 'src/main.rs').write_text('''fn main() {
    println!("{}", itoa::Buffer::new().format(compact_lifecycle::answer()));
}
''')

    def main(self):
        a, b = 'first', 'second'
        versions = {}
        for name, binary, args in (
            ('cargo', self.args.cargo, ['-Vv']),
            ('rustc', self.args.rustc, ['-vV']),
            ('rustdoc', self.args.rustdoc, ['-V']),
        ):
            versions[name] = self.run(name + '-version', [binary, *args]).stdout
        assert 'host: x86_64-unknown-linux-gnu' in versions['rustc'], versions['rustc']
        sysroot = Path(self.run('sysroot', [self.args.rustc, '--print=sysroot']).stdout.strip())
        wild = sysroot / 'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld'
        assert (wild / 'compact-artifacts-v1').read_bytes() == b'RCOBJ001\n'
        assert (wild / 'ld.bfd').is_file()
        self.result['provenance'] = {
            'versions': versions, 'sysroot': str(sysroot), 'wild_sha256': digest(wild / 'ld.bfd'),
            'cargo_sha256': digest(self.args.cargo), 'script_sha256': digest(__file__),
        }
        for name in (a, b):
            self.fixture(name)
            self.cargo(name + '-lockfile', name, True, 'generate-lockfile', '--offline')
        _, _, compact_a = self.build('compact-first', a, True)
        self.binary('compact-first-output', a, 42)
        _, artifacts, _ = self.build('compact-noop', a, True)
        assert all(artifact['fresh'] for artifact in artifacts), artifacts
        self.cargo('compact-doctest', a, True, 'test', '--doc', '--locked', '--offline', '-vv')
        self.cargo('compact-unit-test', a, True, 'test', '--lib', '--locked', '--offline', '-vv')
        shared = self.args.target_root / 'shared-build'
        a_namespaces = [*shared.glob('debug/build/workspaces/*'), *shared.glob('debug/incremental/*')]
        assert a_namespaces, 'no shared workspace artifacts found'
        _, artifacts, compact_b = self.build('second-fixture-shared-cache', b, True)
        assert compact_b['itoa'] == compact_a['itoa'], (compact_a, compact_b)
        assert next(row for row in artifacts if row['target']['name'] == 'itoa')['fresh']
        self.binary('second-fixture-output', b, 42)
        dep = self.args.source_root / a / 'dep/src/lib.rs'
        dep.write_text('fn private() -> u64 { 43 }\npub fn answer() -> u64 { private() }\n')
        edit, _, _ = self.build('private-edit', a, True)
        assert '-Z link-only' in edit.stderr or '-Zlink-only' in edit.stderr, 'private edit did not reuse codegen via saved relink'
        self.binary('private-edit-output', a, 43)
        dep.write_text('fn private() -> u32 { 44 }\npub fn answer() -> u32 { private() }\n')
        _, artifacts, _ = self.build('public-api-edit', a, True)
        assert any(row['target']['name'] == 'compact_lifecycle' and not row['fresh'] for row in artifacts)
        self.binary('public-api-edit-output', a, 44)
        _, _, ordinary_a = self.build('toggle-ordinary', a, False)
        assert ordinary_a['itoa'] != compact_a['itoa'], 'format modes shared a registry artifact identity'
        self.binary('ordinary-output', a, 44)
        _, artifacts, _ = self.build('ordinary-noop', a, False)
        assert all(row['fresh'] for row in artifacts), artifacts
        valid = dep.read_text()
        dep.write_text(valid + '\nfn invalid() { missing_compact_lifecycle_probe(); }\n')
        for compact in (False, True):
            diagnostic = self.cargo(f'type-error-compact-{compact}', a, compact,
                                    'build', '--locked', '--offline', expect=101)
            assert 'cannot find function `missing_compact_lifecycle_probe`' in diagnostic.stderr
            assert 'internal compiler error' not in diagnostic.stderr
        dep.write_text(valid)
        self.build('toggle-back-compact', a, True)
        self.binary('toggle-back-output', a, 44)
        _, artifacts, _ = self.build('compact-again-noop', a, True)
        assert all(row['fresh'] for row in artifacts), artifacts
        self.result['storage_before_clean'] = storage(self.args.target_root)
        for path in self.args.target_root.rglob('*.rlib'):
            with path.open('rb') as stream:
                assert stream.read(8) != b'RCLIB001', f'external-store manifest leaked: {path}'
        self.cargo('clean-first', a, True, 'clean', '-v')
        assert not (self.args.target_root / a).exists(), 'cargo clean retained private target outputs'
        assert all(not path.exists() for path in a_namespaces), 'cargo clean retained workspace build/incremental outputs'
        assert Path(compact_b['itoa']).is_file(), 'cargo clean deleted shared registry artifact'
        self.result['storage_after_first_clean'] = storage(self.args.target_root)
        _, artifacts, _ = self.build('second-after-first-clean', b, True)
        assert all(row['fresh'] for row in artifacts), artifacts
        self.binary('second-after-clean-output', b, 42)
        _, artifacts, rebuilt = self.build('first-after-clean', a, True)
        assert rebuilt['itoa'] == compact_b['itoa']
        assert next(row for row in artifacts if row['target']['name'] == 'itoa')['fresh']
        self.binary('first-rebuilt-output', a, 44)
        for name in (a, b):
            self.cargo('final-clean-' + name, name, True, 'clean')
        assert not list(shared.glob('debug/build/workspaces/*'))
        assert not list(shared.glob('debug/incremental/*'))
        assert Path(compact_b['itoa']).is_file(), 'registry cache should survive workspace clean'
        self.result['storage_after_both_clean'] = storage(self.args.target_root)
        self.result['passed'] = True
        self.save()
        print(f'Cargo lifecycle passed: {self.args.output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo', type=Path, required=True, help='Standalone candidate Cargo, not a rustup proxy')
    parser.add_argument('--rustc', type=Path, required=True)
    parser.add_argument('--rustdoc', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--target-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo-home', type=Path, default=Path('/tmp/codex-cargo-home'))
    args = parser.parse_args()
    for key, value in vars(args).items():
        setattr(args, key, value.absolute())
    assert not args.output.exists(), f'refusing to overwrite evidence: {args.output}'
    for root in (args.source_root, args.target_root):
        assert not root.is_symlink(), root
        assert not root.exists() or not any(root.iterdir()), f'requires fresh directory: {root}'
    for root in (args.source_root, args.target_root, args.output.parent):
        root.mkdir(parents=True, exist_ok=True)
    study = Study(args)
    try:
        study.main()
    except BaseException as error:
        study.result['error'] = repr(error)
        raise
    finally:
        study.save()


if __name__ == '__main__':
    main()
