#!/usr/bin/env python3
"""Compare ordinary, external-store, and self-contained compact artifacts."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CORE_PATH = HERE.parent.parent / 'compact-artifact-prototypes/objects/harness/benchmark.py'
if not CORE_PATH.is_file():
    CORE_PATH = HERE.parent.parent / 'harness/benchmark.py'  # Retained devbox study.
spec = importlib.util.spec_from_file_location('compact_benchmark_core', CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
CORE_SHA = 'ea7867f9f9a0f19ceb7d9c558aa7aa6758ae3e254878685fbc58768c65713cef'
assert core.digest(CORE_PATH) == CORE_SHA
original_environment, original_formats = core.environment, core.formats
core.MODES = ('baseline', 'standard', 'compact-raw', 'compact-archive')
core.RECORDED_ENV += ('CARGO_UNSTABLE_EMBED_METADATA',)


def environment(args, mode, lane, project):
    env, flags = original_environment(args, 'compact' if mode == 'compact-raw' else 'standard' if mode == 'compact-archive' else mode, lane, project)
    if mode == 'compact-raw':
        flags.append('-Zcompact-artifact-raw-metadata=yes')
    elif mode == 'compact-archive':
        flags.append('-Zcompact-artifacts=yes')
        # Match the shipping Cargo opt-in: registry rlibs must retain their full
        # metadata so copying an archive never requires a donor sidecar.
        env['CARGO_UNSTABLE_EMBED_METADATA'] = 'true'
    if mode != 'compact-archive':
        env.pop('CARGO_UNSTABLE_EMBED_METADATA', None)
    env['CARGO_ENCODED_RUSTFLAGS'] = '\x1f'.join(flags)
    return env, flags


def archive_members(path):
    """Read GNU/BSD ar member prefixes without decoding object payloads."""
    with path.open('rb') as stream:
        assert stream.read(8) == b'!<arch>\n', path
        while header := stream.read(60):
            assert len(header) == 60 and header[58:] == b'`\n', path
            size = int(header[48:58])
            start = stream.tell()
            name = header[:16].strip()
            if name.startswith(b'#1/'):
                name_size = int(name[3:])
                assert 0 <= name_size <= size, path
                stream.seek(name_size, 1)
                name = b'bsd-member'
            yield name, stream.read(min(8, start + size - stream.tell()))
            stream.seek(start + size + (size % 2))


def formats(roots, mode):
    result = original_formats(roots, mode if mode in ('standard', 'baseline') else 'compact')
    seen = set()
    metadata = {'raw': 0, 'packed': 0, 'empty': 0, 'other': 0}
    members = {'compact': 0, 'elf': 0, 'other': 0}
    for root in roots:
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not Path(directory, d).is_symlink()]
            for name in files:
                path = Path(directory, name)
                if path.is_symlink() or path.suffix not in ('.rlib', '.rmeta'):
                    continue
                st = path.stat()
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
                with path.open('rb') as stream:
                    magic = stream.read(8)
                if path.suffix == '.rmeta':
                    kind = ('packed' if magic == b'RUSTZRL1' else 'raw' if magic.startswith(b'rust\0\0\0') else 'empty' if not magic else 'other')
                    metadata[kind] += 1
                elif magic == b'!<arch>\n':
                    for _, prefix in archive_members(path):
                        kind = 'compact' if prefix == b'RCOBJ001' else 'elf' if prefix.startswith(b'\x7fELF') else 'other'
                        members[kind] += 1
    result['metadata_formats'] = metadata
    result['archive_member_formats'] = members
    if mode in ('baseline', 'standard'):
        result['passed'] &= members['compact'] == 0
    elif mode == 'compact-raw':
        result['forbidden'] = ('wrapper',)
        result['passed'] &= not result['counts'].get('wrapper')
    if mode == 'compact-archive':
        result['required'] = ('archive', 'object')
        result['forbidden'] = ('manifest', 'wrapper')
        counts = result['counts']
        result['passed'] = bool(all(counts.get(k) for k in result['required']) and not any(counts.get(k) for k in result['forbidden']) and members['compact'])
    result['passed'] &= bool(metadata['raw'] and not metadata['packed'] and not metadata['other'])
    return result


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-wild', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args, _ = parser.parse_known_args()
    fresh = not args.output.exists() or not any(args.output.iterdir())
    core.environment, core.formats = environment, formats
    try:
        core.main()
    finally:
        if fresh and not args.dry_run and args.output.is_dir():
            (args.output / 'shipping.json').write_text(json.dumps({
                'purpose': 'Compare storeless compact ar against ordinary output and compact manifests with raw metadata and repaired prefix reuse',
                'wrapper_sha256': core.digest(__file__), 'core_sha256': CORE_SHA,
                'modes': core.MODES, 'argv': sys.argv,
                'controls': 'Pristine compiler and pinned shipped Wild versus three candidate modes using one fork Wild; compact-archive embeds full metadata matching the Cargo opt-in; original timing/census/oracles/monitor unchanged',
            }, indent=2) + '\n')


if __name__ == '__main__':
    main()
