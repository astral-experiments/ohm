#!/usr/bin/env python3
"""Validate compact archive worktree seeds on the retained, owned Btrfs fixture.

No compiler build. No formatting or deletion of the retained image. Only the
mount created by this run is unmounted, without force or lazy detachment.
All fixture files remain in the image for inspection after normal unmount.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time

STUDY = Path('/home/dev-user/code/oss/ohm-compact-study')
IMAGE = STUDY / 'cow-fixture.img'
UUID = 'bd56beef-edf3-4499-bd76-cb58c9b34088'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def archive_members(path):
    names = b''
    with path.open('rb') as stream:
        assert stream.read(8) == b'!<arch>\n', path
        while header := stream.read(60):
            assert len(header) == 60 and header[58:] == b'`\n', path
            size, name = int(header[48:58]), header[:16].strip()
            data = stream.read(size)
            assert len(data) == size
            if size % 2:
                assert stream.read(1) == b'\n'
            if name == b'//':
                names = data
                continue
            if name in (b'/', b'/SYM64/') or name.startswith(b'__.SYMDEF'):
                continue
            if name.startswith(b'#1/'):
                length = int(name[3:])
                name, data = data[:length].rstrip(b'\0'), data[length:]
            elif name.startswith(b'/'):
                offset = int(name[1:])
                end = names.find(b'/\n', offset)
                assert end >= 0
                name = names[offset:end]
            else:
                name = name.removesuffix(b'/')
            yield name.decode(), data


class Check:
    def __init__(self, args):
        self.args = args
        self.mount = STUDY / 'shipping/worktree-cow'
        self.root = self.mount / 'shipping' / args.case
        self.sources, self.targets = self.root / 'sources', self.root / 'targets'
        self.donor, self.child = self.sources / 'donor', self.sources / 'child'
        self.shared = self.targets / 'shared-build'
        self.mount_owned = False
        self.mount_record = None
        self.receipt = {'passed': False, 'started': time.time(), 'commands': [],
                        'case': args.case, 'script_sha256': digest(Path(__file__)),
                        'image': str(IMAGE), 'mount': str(self.mount), 'case_root': str(self.root)}
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('CARGO_', 'RUST'))}
        self.settings = {'CARGO': str(args.cargo), 'RUSTC': str(args.rustc),
                         'RUSTDOC': str(args.rustdoc), 'RUSTC_BOOTSTRAP': '1',
                         'CARGO_HOME': str(args.cargo_home), 'CARGO_BUILD_JOBS': '4',
                         'CARGO_INCREMENTAL': '1', 'CARGO_TERM_COLOR': 'never',
                         'CARGO_BUILD_BUILD_DIR': str(self.shared)}
        self.env.update(self.settings)
        self.receipt['environment'] = self.settings

    def save(self):
        self.args.output.write_text(json.dumps(self.receipt, indent=2) + '\n')

    def run(self, label, command, cwd=None, target=None):
        command = list(map(str, command))
        environment = dict(self.env)
        if target:
            environment['CARGO_TARGET_DIR'] = str(target)
        start = time.monotonic()
        result = subprocess.run(command, cwd=cwd or STUDY, env=environment,
                                text=True, capture_output=True)
        self.receipt['commands'].append({'label': label, 'argv': command, 'cwd': str(cwd or STUDY),
                                        'target': str(target) if target else None,
                                        'seconds': time.monotonic() - start,
                                        'returncode': result.returncode, 'stdout': result.stdout,
                                        'stderr': result.stderr})
        self.save()
        assert result.returncode == 0, f'{label}: {result.stderr}'
        return result

    def cargo(self, label, cwd, target, *command):
        return self.run(label, [self.args.cargo, '-Zohm-defaults=yes',
                               '-Zohm-compact-artifacts=yes', *command], cwd, target)

    def mount_records(self):
        return [line for line in Path('/proc/self/mountinfo').read_text().splitlines()
                if line.split()[4] == str(self.mount)]

    def verify_mount(self):
        records = self.mount_records()
        assert len(records) == 1, records
        fstype, device, *_ = records[0].split(' - ', 1)[1].split()
        assert fstype == 'btrfs' and re.fullmatch(r'/dev/loop[0-9]+', device), records
        backing = Path('/sys/block') / Path(device).name / 'loop/backing_file'
        assert Path('/' + backing.read_text().strip().lstrip('/')).resolve() == IMAGE.resolve()
        if self.mount_record:
            assert records[0].split()[0] == self.mount_record.split()[0], 'mount identity changed'
        return records[0], device

    def mount_fixture(self):
        info = IMAGE.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), info
        assert info.st_size == 4 * 1024**3, 'retained image size changed'
        identity = self.run('verify-retained-image', ['blkid', '-p', '-o', 'export', IMAGE]).stdout
        fields = dict(line.split('=', 1) for line in identity.splitlines() if '=' in line)
        assert fields['UUID'] == UUID and fields['TYPE'] == 'btrfs', fields
        assert not self.run('verify-image-detached', ['sudo', '-n', 'losetup', '-j', IMAGE]).stdout.strip()
        assert not self.mount_records(), 'will not adopt or tear down an existing mount'
        self.mount.mkdir(parents=True, exist_ok=True)
        assert not self.mount.is_symlink() and not any(self.mount.iterdir()), self.mount
        self.receipt['image_identity'] = {'uuid': UUID, 'size': info.st_size, 'inode': info.st_ino,
                                          'device': info.st_dev, 'owner_uid': info.st_uid}
        self.run('mount-owned-fixture', ['sudo', '-n', 'mount', '-t', 'btrfs',
                                        '-o', 'loop,nosuid,nodev', IMAGE, self.mount])
        self.mount_owned = True
        self.mount_record, _ = self.verify_mount()
        self.receipt['mount_record'] = self.mount_record
        assert not self.root.exists(), f'requires a new owned case directory: {self.root}'
        self.sources.mkdir(parents=True)
        self.targets.mkdir()

    def teardown(self):
        if not self.mount_owned:
            return
        # Normal unmount can briefly report EBUSY after a completed build.
        # Retry only normal EBUSY unmounts, rechecking mount ownership each time.
        # A persistent holder still fails; never force or lazily detach the mount.
        for attempt in range(5):
            _, device = self.verify_mount()
            try:
                self.run('unmount-owned-fixture', ['sudo', '-n', 'umount', self.mount])
                break
            except AssertionError:
                result = self.receipt['commands'][-1]
                if attempt == 4 or result['returncode'] != 32 or 'target is busy' not in result['stderr']:
                    raise
                time.sleep(1)
        self.mount_owned = False
        assert not self.mount_records()
        loops = self.run('verify-loop-autoclear', ['sudo', '-n', 'losetup', '-j', IMAGE]).stdout.strip()
        if loops:
            # Some mount versions do not mark their allocated loop device autoclear.
            assert len(loops.splitlines()) == 1 and loops.startswith(device + ':'), loops
            backing = Path('/sys/block') / Path(device).name / 'loop/backing_file'
            assert Path('/' + backing.read_text().strip().lstrip('/')).resolve() == IMAGE.resolve()
            self.run('detach-owned-loop', ['sudo', '-n', 'losetup', '-d', device])
            assert not self.run('verify-detached', ['sudo', '-n', 'losetup', '-j', IMAGE]).stdout.strip()
        self.receipt['teardown'] = {'unmounted': True, 'image_preserved': IMAGE.is_file(),
                                    'fixture_files_retained_inside_image': True}

    def fixture(self):
        (self.donor / 'src').mkdir(parents=True)
        (self.donor / 'dep/src').mkdir(parents=True)
        (self.donor / 'Cargo.toml').write_text('''[package]
name = "compact-worktree"
version = "0.1.0"
edition = "2024"
[workspace]
members = ["dep"]
[dependencies]
dep = { path = "dep" }
itoa = "=1.0.15"
''')
        (self.donor / 'dep/Cargo.toml').write_text('''[package]
name = "dep"
version = "0.1.0"
edition = "2024"
''')
        self.private_edit(self.donor, 42)
        (self.donor / 'src/main.rs').write_text('fn main() { println!("{}", itoa::Buffer::new().format(dep::answer())); }\n')
        self.run('git-init', ['git', 'init', '-b', 'charlie/compact-shipping-donor'], self.donor)
        actual = Path(self.run('git-root', ['git', 'rev-parse', '--show-toplevel'], self.donor).stdout.strip())
        assert actual == self.donor and actual.is_relative_to(STUDY)
        # This devbox still has an OpenAI global default; route this new OSS
        # fixture locally without changing other repositories or global config.
        self.run('git-local-identity', ['git', 'config', '--local', 'user.email',
                                        'charlie.r.marsh@gmail.com'], self.donor)
        assert self.run('git-identity', ['git', 'config', '--get', 'user.email'], self.donor).stdout.strip() == 'charlie.r.marsh@gmail.com'
        self.cargo('lockfile', self.donor, self.targets / 'donor', 'generate-lockfile', '--offline')
        self.run('git-add', ['git', 'add', '.'], self.donor)
        self.run('git-commit', ['git', 'commit', '-m', 'Add compact archive worktree fixture'], self.donor)
        self.run('git-base', ['git', 'branch', 'main'], self.donor)
        self.run('git-upstream', ['git', 'branch', '--set-upstream-to=main'], self.donor)

    def private_edit(self, source, value):
        (source / 'dep/src/lib.rs').write_text(f'fn private() -> u64 {{ {value} }}\npub fn answer() -> u64 {{ private() }}\n')

    def build(self, label, source, target, value):
        result = self.cargo(label, source, target, 'build', '--locked', '--offline', '-vv',
                            '--message-format=json')
        artifacts = []
        for line in result.stdout.splitlines():
            if line.startswith('{'):
                row = json.loads(line)
                if row.get('reason') == 'compiler-artifact':
                    artifacts.append(row)
        assert artifacts
        assert next(row for row in artifacts if row['target']['name'] == 'itoa')['fresh'] or source == self.donor
        archives = []
        for row in artifacts:
            for filename in row['filenames']:
                if filename.endswith('.rlib'):
                    self.check_archive(Path(filename))
                    archives.append(filename)
        assert archives
        self.receipt['commands'][-1]['all_fresh'] = all(row['fresh'] for row in artifacts)
        self.receipt['commands'][-1]['selected_archives'] = archives
        output = self.run(label + '-runtime', [target / 'debug/compact-worktree'], source).stdout
        assert output.strip() == str(value), output
        return result

    def check_archive(self, path):
        members = dict(archive_members(path))
        assert any(data.startswith(b'RCOBJ001') for data in members.values()), path
        for name in ('lib.rmeta', 'lib.rmeta-link'):
            assert members[name].startswith(b'\x7fELF'), (path, name)
        return members

    def namespaces(self):
        return {*self.shared.glob('debug/build/workspaces/*'), *self.shared.glob('debug/incremental/*')}

    def objects(self, namespaces):
        objects = {}
        for root in namespaces:
            for path in root.rglob('*.o'):
                if path.is_symlink():
                    continue
                with path.open('rb') as stream:
                    prefix = stream.read(8)
                if prefix == b'RCOBJ001':
                    info = path.stat()
                    objects[str(path)] = {'sha256': digest(path), 'device': info.st_dev,
                                          'inode': info.st_ino, 'size': info.st_size}
        return objects

    def main(self):
        self.run('cargo-version', [self.args.cargo, '-Vv'])
        assert 'host: x86_64-unknown-linux-gnu' in self.run('rustc-version', [self.args.rustc, '-vV']).stdout
        sysroot = Path(self.run('sysroot', [self.args.rustc, '--print=sysroot']).stdout.strip())
        wild = sysroot / 'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld'
        assert (wild / 'compact-artifacts-v1').read_bytes() == b'RCOBJ001\n'
        self.receipt['provenance'] = {'cargo_sha256': digest(self.args.cargo),
                                       'wild_sha256': digest(wild / 'ld.bfd'), 'sysroot': str(sysroot)}
        self.mount_fixture()
        self.fixture()
        donor_target, child_target = self.targets / 'donor', self.targets / 'child'
        self.build('donor-build', self.donor, donor_target, 42)
        assert 'Compiling' not in self.build('donor-noop', self.donor, donor_target, 42).stderr
        donor_namespaces = self.namespaces()
        donor_objects = self.objects(donor_namespaces)
        assert donor_objects, 'donor has no compact incremental objects'
        seeded = self.cargo('seed-worktree', self.donor, donor_target, 'worktree', 'add',
                            '-b', 'charlie/compact-shipping-child', self.child,
                            '--target-dir', child_target, 'HEAD')
        match = re.search(r'Seeded (\d+) files \((\d+) bytes, (\d+) reflinked files\)', seeded.stderr)
        assert match and int(match[1]) > 0 and int(match[3]) > 0, seeded.stderr
        self.run('child-local-base-upstream', ['git', 'branch', '--set-upstream-to=main'], self.child)
        child_namespaces = self.namespaces() - donor_namespaces
        child_objects = self.objects(child_namespaces)
        assert child_objects, 'seed did not contain compact incremental objects'
        donor_by_hash = {row['sha256']: row for row in donor_objects.values()}
        for row in child_objects.values():
            original = donor_by_hash[row['sha256']]
            assert (row['device'], row['inode']) != (original['device'], original['inode']), 'seed shared a mutable donor inode'
        self.receipt['seed'] = {'files': int(match[1]), 'bytes': int(match[2]),
                                'reflinked_files': int(match[3]), 'donor_objects': donor_objects,
                                'child_objects_before_build': child_objects}
        # Keep only Git's common administrative directory available to the child.
        # All donor Rust source, target outputs, metadata and incremental namespaces disappear.
        hidden = []
        for path in [donor_target, *sorted(donor_namespaces), self.donor / 'src',
                     self.donor / 'dep', self.donor / 'Cargo.toml', self.donor / 'Cargo.lock']:
            destination = path.with_name(path.name + '-donor-hidden')
            assert not destination.exists()
            path.rename(destination)
            hidden.append({'original': str(path), 'hidden': str(destination)})
        self.receipt['hidden_donor_paths'] = hidden
        # Copy only the child's seeded rlib. An ordinary compiler invocation has no adjacent
        # .rmeta, no -L dependency search path, no external CAS and no original donor paths.
        # Use system BFD: this development sysroot intentionally has no bundled rust-lld.
        deps = [path for root in child_namespaces for path in root.rglob('libdep-*.rlib')]
        assert len(deps) == 1, deps
        self.check_archive(deps[0])
        probe = self.targets / 'standalone-archive'
        probe.mkdir()
        shutil.copyfile(deps[0], probe / 'libdep.rlib')
        (probe / 'main.rs').write_text('fn main() { println!("{}", dep::answer()); }\n')
        self.run('seeded-archive-alone', [self.args.rustc, 'main.rs', '--edition=2024',
                                        '--extern', 'dep=libdep.rlib', '-Zunstable-options',
                                        '-Clinker-features=-lld', '-o', 'probe'], probe)
        assert self.run('seeded-archive-alone-runtime', [probe / 'probe'], probe).stdout.strip() == '42'
        self.build('child-with-donor-hidden', self.child, child_target, 42)
        self.private_edit(self.child, 43)
        first_edit = self.build('first-private-child-edit', self.child, child_target, 43)
        self.receipt['first_private_edit_link_only'] = '-Z link-only' in first_edit.stderr or '-Zlink-only' in first_edit.stderr
        self.private_edit(self.child, 44)
        next_edit = self.build('second-private-child-edit', self.child, child_target, 44)
        assert '-Z link-only' in next_edit.stderr or '-Zlink-only' in next_edit.stderr, 'child lost saved relink reuse'
        # Global compiler logging deliberately disables Cargo cache/seed admission.
        # The dedicated public-api-hash run-make suite proves prefix reuse separately.
        assert 'Compiling' not in self.build('child-final-noop', self.child, child_target, 44).stderr
        assert all(not Path(row['original']).exists() for row in hidden), 'a donor artifact path was recreated'
        forbidden = []
        for path in self.targets.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            with path.open('rb') as stream:
                if stream.read(8) in (b'RCLIB001', b'RUSTZRL1'):
                    forbidden.append(str(path))
        assert not forbidden, f'external-store or packed metadata artifact: {forbidden}'
        assert not any('compact-store' in path.name for path in self.targets.rglob('*'))
        self.receipt['correctness_passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo', type=Path, required=True)
    parser.add_argument('--rustc', type=Path, required=True)
    parser.add_argument('--rustdoc', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cargo-home', type=Path, default=Path('/tmp/codex-cargo-home'))
    parser.add_argument('--case', default='compact-archives-worktree')
    args = parser.parse_args()
    assert re.fullmatch(r'[a-z0-9][a-z0-9-]*', args.case), args.case
    for key in ('cargo', 'rustc', 'rustdoc', 'output', 'cargo_home'):
        setattr(args, key, getattr(args, key).absolute())
    assert not args.output.exists(), f'refusing to overwrite evidence: {args.output}'
    assert not args.output.is_relative_to(STUDY / 'shipping/worktree-cow'), 'receipt must remain available after unmount'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    check = Check(args)
    try:
        check.main()
    except BaseException as error:
        check.receipt['error'] = repr(error)
        raise
    finally:
        try:
            check.teardown()
        except BaseException as error:
            check.receipt['teardown_error'] = repr(error)
            raise
        finally:
            check.receipt['passed'] = bool(check.receipt.get('correctness_passed') and check.receipt.get('teardown'))
            check.save()
    print(f'Compact worktree correctness passed: {args.output}')


if __name__ == '__main__':
    main()
