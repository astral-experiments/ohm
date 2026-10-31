"""Build one native role with the same bootstrap, LLVM key, paths and full standard libraries."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source import HERE, SIGNED, git, oid, require, sha, write_json

HOST = 'x86_64-unknown-linux-gnu'
WILD = Path('lib/rustlib') / HOST / 'bin/wild-ld/ld.bfd'
CARGO_SHA = '035e681081683f4141e4c544b8cf9492b73784051e4541c12bb3cbdb73a798a4'
WILD_SHA = '0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5'
STAGE0 = {'source': '759b73eca37a7b589b1ecc0fea77d94a1f8ca36cddb94f1401c72343e0dc1d4e',
          'rustc': '3690cc576ede140504698405d5d8fa3826aaadbe71699c6c4ed0a565d6f493e2',
          'cargo': 'ff3022fcbd13b08434ea7afde9a0ef9d5b3f5c17b5fc7a40031be3ee000a6a24'}
LLVM = 'fba1b05a7bd8bdc73080edd02f672cef44648267'
OPTIONS = ['--ci', 'false', '--set', 'build.submodules=false', '--set', 'rust.omit-git-hash=true', '--set',
           'rust.debug-assertions=false', '--set', 'rust.lto=off', '--set', 'llvm.download-ci-llvm=true']
HOST_FLAGS = ['--stage', '1', '-j8', '--host', HOST, '--target', HOST]


def measured_file(p):
    return [sha(p), p.stat().st_size, p.stat().st_mode & 0o777]


def run_log(args, cwd, path):
    with path.open('xb') as f:
        p = subprocess.run(args, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
    if p.returncode:
        print(path.read_text(errors='replace')[-9000:], flush=True)
        p.check_returncode()


def run(role, root):
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64', 'wrong host')
    require(shutil.disk_usage(root).free > 32 * 2**30, 'need 32 GiB free')
    available = next(int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    require(available > 6 * 2**20, 'need 6 GiB free RAM')
    repo = root / 'rust'; log = root / 'receipts'; log.mkdir(exist_ok=True)
    require(oid(repo, 'HEAD:library') == SIGNED['library_tree'] and oid(repo, 'HEAD:src/bootstrap') == SIGNED['bootstrap_tree'], 'stdlib/bootstrap sources differ')
    upstream = git(repo, 'rev-list', '--author-date-order', '--author=bors@rust-lang\\.org', '-n1', 'HEAD').decode().strip()
    llvm = git(repo, 'rev-list', '--first-parent', '-n1', upstream, '--author=bors@rust-lang\\.org', '--', 'src/llvm-project', 'src/bootstrap/download-ci-llvm-stamp', 'src/version').decode().strip()
    require(upstream == 'b940084d7eb6a299eb4bfeb8e34901bc051e7ac4' and llvm == LLVM, 'different upstream or LLVM')
    require(not git(repo, 'diff', '--stat', llvm, 'HEAD', '--', 'src/llvm-project', 'src/bootstrap/download-ci-llvm-stamp', 'src/version'), 'changed LLVM inputs')
    require(oid(repo / 'library/backtrace', 'HEAD') == 'd902726a1dcdc1e1c66f73d1162181b5423c645b', 'changed backtrace')
    cmd = [sys.executable, 'x.py', *OPTIONS, 'build', *HOST_FLAGS, 'compiler/rustc', 'library']
    run_log(cmd, repo, log / 'bootstrap.log')
    stage = repo / 'build' / HOST / 'stage1'; stage0 = stage.parent / 'stage0/bin'
    bootstrap = {'source': sha(repo / 'src/stage0'), **{k: sha(stage0 / k) for k in ['rustc', 'cargo']}}
    require(bootstrap == STAGE0, 'bootstrap executable replaced')
    if role == 'candidate':
        def runtime_snapshot():
            root = stage / 'lib/rustlib' / HOST / 'lib'
            files = [stage/'bin/rustc', *(stage/'lib').glob('*.so*'), *(p for p in root.rglob('*') if p.is_file())]
            return {str(p.relative_to(stage)): measured_file(p) for p in files}
        before = runtime_snapshot()
        unit = 'rmeta::generic_export_flags_preserve_old_c_linker_bits'
        tests = [sys.executable, 'x.py', *OPTIONS, '--set','rust.verbose-tests=true','test', *HOST_FLAGS]
        run_log([*tests, 'compiler/rustc_metadata','--test-args','--exact '+unit], repo, log / 'metadata-unit.log')
        output = (log / 'metadata-unit.log').read_text(errors='replace')
        require('test ' + unit + ' ... ok' in output and '1 passed' in output, 'metadata unit selected no tests')
        # The original product fixture is compiled and run by Rust's own test harness.
        run_log([*tests,'tests/run-make/ohm-profile-aware-shared-generics'], repo, log / 'product-regression.log')
        result = (log / 'product-regression.log').read_text(errors='replace')
        require('1 passed' in result and 'ohm-profile-aware-shared-generics' in result, 'product regression selected no tests')
        require(before == runtime_snapshot(), 'running compiler tests changed the qualified runtime or standard library')
    leaf = Path('lib/rustlib') / HOST / 'lib'
    selected = {p.relative_to(stage): p for p in (stage / leaf).rglob('*') if p.is_file()}
    for name in ['std', 'core', 'alloc', 'test', 'proc_macro']:
        require(any(p.name.startswith('lib' + name + '-') and p.suffix == '.rlib' for p in selected), 'missing ' + name)
    if role != 'legacy':
        keep = [stage / 'bin/rustc', *(stage / 'lib').glob('*.so*')]
        for item in [stage / leaf.parent / 'bin/rust-lld', stage / leaf.parent / 'bin/gcc-ld']:
            if item.is_dir(): keep.extend(p for p in item.rglob('*') if p.is_file())
            elif item.is_file(): keep.append(item)
        for p in keep: selected[p.relative_to(stage)] = p
        require(any(n.name.startswith('libLLVM') for n in selected) and any(n.name.startswith('librustc_driver') for n in selected), 'missing LLVM or compiler driver')
        selected[Path('bin/cargo')] = root / 'strict-cargo/cargo'
        selected[WILD] = root / 'packages/sdk-21' / WILD
        require(sha(selected[Path('bin/cargo')]) == CARGO_SHA and sha(selected[WILD]) == WILD_SHA, 'non-enrolled Cargo or Wild')
    spec = root / 'specimen'; spec.mkdir()
    (spec / 'legacy.rs').write_text('#[inline] pub fn probe<T>(x: u64) -> u64 { std::hint::black_box(x) + size_of::<T>() as u64 }\npub fn emit(x: u64) -> u64 { probe::<u16>(x) }\n')
    run_log([stage / 'bin/rustc', spec / 'legacy.rs', '--crate-name', 'qa_exporter', '--crate-type', 'rlib', '-Copt-level=0', '-Cdebuginfo=0', '-Cdebug-assertions=yes', '-Coverflow-checks=yes', '-Zub-checks=yes', '-Cmetadata=qabare', '-Cextra-filename=-qabare', '--emit=link,metadata', '--out-dir', spec], spec, log / 'producer.log')
    for item in ('libqa_exporter-qabare.rlib', 'libqa_exporter-qabare.rmeta'):
        selected[Path('specimen') / item] = spec / item
    lib = spec / 'libqa_exporter-qabare.rmeta'
    stamp = subprocess.check_output([stage / 'bin/rustc', '-V'], text=True).strip()
    raw = lib.read_bytes()
    expected = {'legacy': stamp, 'parent': stamp + ' (Ohm metadata 1)', 'candidate': stamp + ' (Ohm metadata 2)'}[role].encode()
    require(expected in raw and (role != 'legacy' or b'(Ohm metadata' not in raw), 'wrong emitted metadata epoch')
    files = {str(n): measured_file(p) for n, p in sorted(selected.items())}
    transfer = root / 'transfer'; transfer.mkdir()
    with subprocess.Popen(['zstd', '-q', '-T3', '-3', '-o', str(transfer / 'toolchain.tar.zst')], stdin=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdin, mode='w|', dereference=True) as ar:
            for n, p in sorted(selected.items()): ar.add(p, arcname=str(n), recursive=False)
        z.stdin.close(); require(z.wait() == 0, 'zstd failed')
    require(not git(repo, 'status', '--porcelain=v1', '--untracked-files=no'), 'source changed during build')
    receipt = {'role': role, 'qa': os.environ['GITHUB_SHA'], 'commit': oid(repo, 'HEAD'), 'tree': oid(repo, 'HEAD^{tree}'),
               'flags': cmd[1:], 'stage0': bootstrap, 'llvm': llvm, 'version': stamp, 'metadata': expected.decode(),
               'files': files, 'transfer': sha(transfer / 'toolchain.tar.zst')}
    write_json(transfer / 'manifest.json', receipt); write_json(log / 'manifest.json', receipt)


if __name__ == '__main__':
    run(sys.argv[1], Path(sys.argv[2]).resolve())
