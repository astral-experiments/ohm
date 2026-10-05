#!/usr/bin/env python3
"""Check compact native-object alignment across ordinary archive/linker boundaries.

Run after the coordinated compiler build; this script never builds the compiler.
All commands, format checks, and runtime addresses are retained in the JSON receipt.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_build_receipt(build, sysroot, version):
    """Bind source provenance to the compiler driver bytes used by this run."""
    assert Path(build['sysroot']).resolve() == sysroot, 'build receipt sysroot mismatch'
    assert build['version'].strip() == version.strip(), 'build receipt compiler version mismatch'
    drivers = build['drivers']
    assert isinstance(drivers, dict) and drivers, 'build receipt has no compiler driver hashes'
    expected = {}
    for name, checksum in drivers.items():
        path = Path(name)
        path = path if path.is_absolute() else sysroot / 'lib' / path
        path = path.resolve()
        assert path.parent == sysroot / 'lib', 'compiler driver is outside the sysroot lib directory'
        assert path.name.startswith('librustc_driver-') and path.suffix == '.so', path
        assert path not in expected, 'duplicate compiler driver in build receipt'
        expected[path] = checksum
    actual = {path.resolve() for path in (sysroot / 'lib').glob('librustc_driver-*.so')}
    assert actual == set(expected), 'build receipt compiler driver set mismatch'
    for path, checksum in expected.items():
        assert digest(path) == checksum, f'build receipt compiler driver hash mismatch: {path}'


def archive_members(path):
    """Yield resolved GNU/BSD ar member names and bytes, excluding index tables."""
    names = b''
    with path.open('rb') as stream:
        assert stream.read(8) == b'!<arch>\n', path
        while header := stream.read(60):
            assert len(header) == 60 and header[58:] == b'`\n', path
            size = int(header[48:58])
            name = header[:16].strip()
            data = stream.read(size)
            assert len(data) == size, path
            if size % 2:
                assert stream.read(1) == b'\n', path
            if name == b'//':
                names = data
                continue
            if name in (b'/', b'/SYM64/') or name.startswith(b'__.SYMDEF'):
                continue
            if name.startswith(b'#1/'):
                length = int(name[3:])
                assert 0 <= length <= size, path
                name, data = data[:length].rstrip(b'\0'), data[length:]
            elif name.startswith(b'/'):
                offset = int(name[1:])
                assert 0 <= offset < len(names), path
                end = names.find(b'/\n', offset)
                assert end != -1, path
                name = names[offset:end]
            else:
                name = name.removesuffix(b'/')
            yield name.decode(), data


def native_section(data, alignment):
    """Read the small ELF64 little-endian fixture's initialized data section."""
    assert data[:6] == b'\x7fELF\x02\x01'
    offset = struct.unpack_from('<Q', data, 40)[0]
    stride, count, strings = struct.unpack_from('<HHH', data, 58)
    assert stride == 64 and count > 0 and 0 < strings < count
    assert offset + count * stride <= len(data)
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * stride)
               for i in range(count)]
    names_header = headers[strings]
    names = data[names_header[4]:names_header[4] + names_header[5]]
    for header in headers:
        end = names.find(b'\0', header[0])
        assert end != -1
        if names[header[0]:end] != b'.data.native_value':
            continue
        assert header[1] == 1 and header[8] == alignment, header
        assert header[5] == 1 and data[header[4]:header[4] + 1] == b'Z', header
        return {'offset': header[4], 'size': header[5], 'alignment': header[8],
                'object_bytes': len(data)}
    raise AssertionError('missing .data.native_value')


class Check:
    def __init__(self, args):
        self.args = args
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('CARGO_', 'RUST')) and key not in ('CC', 'CFLAGS', 'LDFLAGS')}
        self.env['RUSTC_BOOTSTRAP'] = '1'
        self.receipt = {'started': time.time(), 'passed': False, 'commands': [], 'cases': [],
                        'script_sha256': digest(Path(__file__)), 'compiler': str(args.rustc),
                        'target': str(args.target), 'platform': platform.platform()}

    def save(self):
        self.args.receipt.write_text(json.dumps(self.receipt, indent=2) + '\n')

    def run(self, command, cwd):
        command = [str(arg) for arg in command]
        start = time.monotonic()
        result = subprocess.run(command, cwd=cwd, env=self.env, capture_output=True, text=True)
        self.receipt['commands'].append({'argv': command, 'cwd': str(cwd),
                                        'seconds': time.monotonic() - start,
                                        'returncode': result.returncode,
                                        'stdout': result.stdout, 'stderr': result.stderr})
        self.save()
        if result.returncode:
            raise RuntimeError(f'command failed ({result.returncode}): {command!r}\n{result.stderr}')
        return result.stdout

    def runtime(self, executable, lane, alignment):
        result = json.loads(self.run([executable], lane))
        assert result['alignment'] == alignment and result['value'] == 90, result
        assert result['address'] != 0 and result['address'] % alignment == 0, result
        return result

    def case(self, alignment):
        lane = self.args.target / str(alignment)
        lane.mkdir()
        row = {'alignment': alignment, 'passed': False, 'staticlib': []}
        self.receipt['cases'].append(row)
        (lane / 'native.c').write_text(f'''#include <stdint.h>
_Alignas({alignment}) unsigned char native_value = 90;
uintptr_t native_address(void) {{ return (uintptr_t)&native_value; }}
unsigned int native_read(void) {{ return native_value; }}
''')
        (lane / 'main.c').write_text(f'''#include <stdint.h>
#include <stdio.h>
#ifndef EXPORTED
#define exported_address native_address
#define exported_read native_read
#endif
extern uintptr_t exported_address(void);
extern unsigned int exported_read(void);
int main(void) {{
    volatile uintptr_t address = exported_address();
    unsigned int value = exported_read();
    printf("{{\\\"address\\\":%llu,\\\"alignment\\\":{alignment},\\\"value\\\":%u}}\\n",
           (unsigned long long)address, value);
    return !address || address % {alignment} || value != 90;
}}
''')
        (lane / 'dep.rs').write_text('''#[link(name = "native", kind = "static")]
unsafe extern "C" {
    fn native_address() -> usize;
    fn native_read() -> u32;
}
pub fn address() -> usize { unsafe { native_address() } }
pub fn value() -> u32 { unsafe { native_read() } }
''')
        (lane / 'export.rs').write_text('''#[unsafe(no_mangle)]
pub extern "C" fn exported_address() -> usize { dep::address() }
#[unsafe(no_mangle)]
pub extern "C" fn exported_read() -> u32 { dep::value() }
''')
        (lane / 'consumer.rs').write_text(f'''fn main() {{
    let address = std::hint::black_box(dep::address());
    let value = dep::value();
    assert_ne!(address, 0);
    assert_eq!(address % {alignment}, 0);
    assert_eq!(value, 90);
    println!("{{{{\\\"address\\\":{{address}},\\\"alignment\\\":{alignment},\\\"value\\\":{{value}}}}}}");
}}
''')
        self.run([self.args.cc, '-c', '-std=c11', '-O0', '-fPIC', '-ffunction-sections',
                  '-fdata-sections', 'native.c', '-o', 'native.o'], lane)
        row['original_native_section'] = native_section((lane / 'native.o').read_bytes(), alignment)
        self.run([self.args.ar, 'crs', 'libnative.a', 'native.o'], lane)
        self.run([self.args.cc, 'main.c', 'libnative.a', '-fuse-ld=bfd', '-o', 'baseline'], lane)
        row['baseline_runtime'] = self.runtime(lane / 'baseline', lane, alignment)

        compact = ['-Zcompact-artifacts=yes', '-Zcompress-incremental=no']
        self.run([self.args.rustc, 'dep.rs', '--edition=2024', '--crate-type=rlib',
                  '--emit=link,metadata', '-Lnative=.', *compact], lane)
        compact_members = list(archive_members(lane / 'libdep.rlib'))
        native = [data for name, data in compact_members if name == 'native.o']
        assert len(native) == 1 and native[0].startswith(b'RCOBJ001')
        metadata = {name: data for name, data in compact_members
                    if name in ('lib.rmeta', 'lib.rmeta-link')}
        assert set(metadata) == {'lib.rmeta', 'lib.rmeta-link'}
        assert all(data.startswith(b'\x7fELF') for data in metadata.values())
        row['compact_native_bytes'] = len(native[0])
        row['dependency_sha256'] = digest(lane / 'libdep.rlib')
        # Leave only the self-contained rlib in the consumer's library directory.
        donor = lane / 'unsearched-donor'
        donor.mkdir()
        for name in ('libnative.a', 'native.o', 'libdep.rmeta'):
            (lane / name).rename(donor / name)

        for phase in ('fresh', 'green'):
            self.run([self.args.rustc, 'export.rs', '--edition=2024', '--crate-type=staticlib',
                      '--extern=dep=libdep.rlib', '-Cincremental=incremental', *compact], lane)
            ordinary = list(archive_members(lane / 'libexport.a'))
            assert all(not data.startswith(b'RCOBJ001') for _, data in ordinary)
            restored = [data for name, data in ordinary if name == 'native.o']
            assert len(restored) == 1
            section = native_section(restored[0], alignment)
            if alignment >= 1 << 24:
                assert section['offset'] % alignment != 0, section
                assert section['object_bytes'] < alignment, section
            self.run([self.args.cc, '-DEXPORTED', 'main.c', 'libexport.a', '-fuse-ld=bfd',
                      '-ldl', '-lpthread', '-lm', '-lrt', '-lutil', '-o', f'export-{phase}'], lane)
            row['staticlib'].append({'phase': phase, 'restored_native_section': section,
                                     'runtime': self.runtime(lane / f'export-{phase}', lane, alignment)})
        objects = list((lane / 'incremental').rglob('*.o'))
        assert objects and all(path.open('rb').read(8) == b'RCOBJ001' for path in objects)
        row['compact_incremental_objects'] = len(objects)

        # Ordinary consumers must restore compact members before invoking any native linker.
        self.run([self.args.rustc, 'consumer.rs', '--edition=2024', '--extern=dep=libdep.rlib',
                  '-Zunstable-options', '-Clinker-features=-lld',
                  '-Clink-arg=-fuse-ld=bfd', '-o', 'ordinary-bfd'], lane)
        row['ordinary_bfd_runtime'] = self.runtime(lane / 'ordinary-bfd', lane, alignment)
        if self.args.lld:
            self.run([self.args.rustc, 'consumer.rs', '--edition=2024', '--extern=dep=libdep.rlib',
                      '-Zunstable-options', '-Clinker-features=-lld',
                      f'-Clink-arg=-B{self.args.target / "lld-driver"}',
                      '-Clink-arg=-fuse-ld=lld', '-o', 'ordinary-lld'], lane)
            row['ordinary_lld_runtime'] = self.runtime(lane / 'ordinary-lld', lane, alignment)
        else:
            row['ordinary_lld_runtime'] = {'skipped': 'no --lld executable provided'}
        assert digest(lane / 'libdep.rlib') == row['dependency_sha256']
        row['passed'] = True
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, default=Path('/home/dev-user/code/oss/ohm-compact-study'))
    parser.add_argument('--rustc', type=Path)
    parser.add_argument('--target', type=Path,
                        default=Path('/tmp/codex-cargo-targets/ohm/isolated/compact-objects/shipping-alignment'))
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--cc', default='clang')
    parser.add_argument('--ar', default='ar')
    parser.add_argument('--lld', type=Path,
                        help='optional installed rust-lld/ld.lld for additional ordinary-LLD proof')
    parser.add_argument('--build-receipt', type=Path,
                        help='explicit compiler build receipt; validate its driver hashes before testing')
    args = parser.parse_args()
    args.rustc = args.rustc or args.study / 'toolchains/compact-shipping/bin/rustc'
    args.receipt = args.receipt or args.study / 'shipping/evidence/alignment-correctness.json'
    args.rustc, args.target, args.receipt = (path.resolve() for path in
                                          (args.rustc, args.target, args.receipt))
    args.lld = args.lld.resolve() if args.lld else None
    assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
    assert args.rustc.is_file() and shutil.which(args.cc) and shutil.which(args.ar)
    assert args.lld is None or args.lld.is_file()
    assert not args.target.exists(), f'refusing to overwrite {args.target}'
    assert not args.receipt.exists(), f'refusing to overwrite {args.receipt}'
    args.target.mkdir(parents=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    check = Check(args)
    try:
        version = check.run([args.rustc, '-vV'], args.target)
        assert 'host: x86_64-unknown-linux-gnu' in version
        for command in ([args.cc, '--version'], [args.ar, '--version'], ['ld.bfd', '--version']):
            check.run(command, args.target)
        if args.lld:
            # rust-lld is a multicall executable; the ld.lld basename selects its ELF driver.
            directory = args.target / 'lld-driver'
            directory.mkdir()
            alias = directory / 'ld.lld'
            alias.symlink_to(args.lld)
            check.receipt['lld'] = {'path': str(args.lld), 'sha256': digest(args.lld)}
            check.run([alias, '--version'], args.target)
        build = args.build_receipt or args.study / 'shipping/evidence/candidate-build.json'
        if args.build_receipt:
            assert build.is_file(), f'missing explicit build receipt: {build}'
        if build.is_file():
            check.receipt['candidate_build'] = json.loads(build.read_text())
            check.receipt['candidate_build_sha256'] = digest(build)
            check.receipt['candidate_build_path'] = str(build.resolve())
            if args.build_receipt:
                sysroot = Path(check.run([args.rustc, '--print=sysroot'], args.target).strip()).resolve()
                validate_build_receipt(check.receipt['candidate_build'], sysroot, version)
                check.receipt['candidate_build_validated'] = True
        for alignment in (64, 4096, 1 << 24):
            check.case(alignment)
        check.receipt['passed'] = True
    except Exception as error:
        check.receipt['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        check.receipt['finished'] = time.time()
        check.save()
    print(json.dumps({'passed': True, 'receipt': str(args.receipt), 'cases': len(check.receipt['cases'])}))


if __name__ == '__main__':
    main()
