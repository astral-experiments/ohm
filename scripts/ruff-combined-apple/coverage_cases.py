"""Check that the declared source path survives Cargo's implicit remapping."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


MANIFEST = '[package]\nname="coverage_case"\nversion="0.1.0"\nedition="2021"\n[workspace]\n'
MAIN = 'fn main() {\n    let answer = 29;\n    println!("answer={answer}");\n}\n'
PROFILE = "cargo-features=['profile-rustflags']\n"
CARGO = ['cargo', '+ohm']


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')


def call(argv, project, env, logs, name):
    run = subprocess.run(argv, cwd=project, env=env, capture_output=True, timeout=240)
    (logs / (name + '.stdout')).write_bytes(run.stdout)
    (logs / (name + '.stderr')).write_bytes(run.stderr)
    save(logs / (name + '.json'), {'argv': list(map(str, argv)), 'status': run.returncode})
    assert run.returncode == 0, (name, run.returncode, run.stderr[-1500:])
    return run


def setup(directory, sdk, base):
    project = (directory / 'project').resolve()
    (project / 'src').mkdir(parents=True)
    toolchains = directory / 'rustup/toolchains'
    toolchains.mkdir(parents=True)
    (toolchains / 'ohm').symlink_to(sdk, target_is_directory=True)
    env = dict(base, RUSTUP_HOME=str(toolchains.parent), RUSTUP_TOOLCHAIN='ohm',
               CARGO_HOME=str(directory / 'cargo-home'), CARGO_TARGET_DIR=str(directory / 'target'),
               CARGO_BUILD_BUILD_DIR=str(directory / 'build'), CARGO_NET_OFFLINE='true')
    assert not any(k in env for k in ('RUSTFLAGS', 'CARGO_ENCODED_RUSTFLAGS', 'LLVM_PROFILE_FILE',
                                      'RUSTC', 'RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER'))
    return project, env


def coverage(project, base, logs, toolbin, mode, healthy):
    logs.mkdir()
    flags = ['-C', 'instrument-coverage']
    manifest = MANIFEST
    env = dict(base)
    if mode == 'environment':
        env['RUSTFLAGS'] = '-Cinstrument-coverage'
    elif mode == 'profile':
        manifest = PROFILE + MANIFEST + '\n[profile.dev]\nrustflags = ' + json.dumps(flags) + '\n'
    else:
        assert mode == 'cargo-rustc'
    main = project / 'src/main.rs'
    if not main.exists():
        main.write_text(MAIN)
    assert main.read_text() == MAIN
    toml = project / 'Cargo.toml'
    if not toml.exists():
        toml.write_text(manifest)
    assert toml.read_text() == manifest
    (logs / 'main.rs').write_text(MAIN)
    (logs / 'Cargo.toml').write_text(manifest)
    save(logs / 'settings.json', {'mode': mode, 'project': str(project), 'target': env['CARGO_TARGET_DIR'],
                                  'build': env['CARGO_BUILD_BUILD_DIR'], 'RUSTFLAGS': env.get('RUSTFLAGS')})
    verb = 'rustc' if mode == 'cargo-rustc' else 'build'
    argv = [*CARGO, verb, '--bin', 'coverage_case', '--offline', '--message-format=json']
    if mode == 'cargo-rustc':
        argv.extend(['--', *flags])
    built = call(argv, project, env, logs, 'compile')
    messages = list(map(json.loads, built.stdout.splitlines()))
    assert messages[-1] == {'reason': 'build-finished', 'success': True}
    unit, = [row for row in messages if row['reason'] == 'compiler-artifact' and row.get('executable')]
    assert unit['target']['name'] == 'coverage_case' and unit['target']['kind'] == ['bin']
    exe = Path(unit['executable'])
    assert exe.is_file() and exe.resolve().is_relative_to(Path(env['CARGO_TARGET_DIR']).resolve())
    raw = []
    for i in (1, 2):
        output = logs / f'execution-{i}.profraw'
        assert not output.exists()
        executed = call([exe], project, dict(env, LLVM_PROFILE_FILE=str(output)), logs, f'execution-{i}')
        assert executed.stdout == b'answer=29\n' and not executed.stderr and output.stat().st_size > 0
        raw.append(output)
    # LLVM's libraries belong only on its own child process, never on Cargo or the tested binary.
    llvm_env = dict(env)
    library_path = 'DYLD_LIBRARY_PATH' if toolbin.parent.name.endswith('apple-darwin') else 'LD_LIBRARY_PATH'
    llvm_env[library_path] = str(toolbin.parents[2])
    merged = logs / 'merged.profdata'
    call([toolbin / 'llvm-profdata', 'merge', '-sparse', *raw, '-o', merged], project, llvm_env, logs, 'merge')
    cov = [exe, '-instr-profile=' + str(merged)]
    shown = call([toolbin / 'llvm-cov', 'show', *cov], project, llvm_env, logs, 'show')
    exported = call([toolbin / 'llvm-cov', 'export', *cov], project, llvm_env, logs, 'export')
    data, = json.loads(exported.stdout)['data']
    source, = data['files']
    filename = Path(source['filename'])
    function, = [f for f in data['functions'] if str(filename) in f['filenames']]
    code_line = re.findall(rb'^\s*2\|\s*(\d+)\|\s*let answer = 29;\s*$', shown.stdout, re.M)
    result = {'rendered': bool(code_line), 'count': function['count'], 'filename': str(filename),
              'annotated_line_counts': [int(n) for n in code_line], 'lines': source['summary']['lines'],
              'fresh': unit['fresh'], 'executable': str(exe), 'exe_sha256': digest(exe),
              'source_sha256': digest(main), 'manifest_sha256': digest(toml),
              'raw_sha256': [digest(p) for p in raw], 'merged_sha256': digest(merged)}
    save(logs / 'result.json', result)
    assert function['count'] == 2 and source['summary']['lines']['percent'] == 100
    if healthy:
        assert filename == main and code_line == [b'2'] and not shown.stderr, (filename, shown.stderr)
    else:
        assert str(filename).startswith('/ohm-workspace/') and str(filename).endswith('/src/main.rs')
        assert not filename.exists() and not code_line and str(filename).encode() in shown.stderr
        assert b'No such file or directory' in shown.stderr, shown.stderr
    return result


def remap(project, env, logs, prefix, healthy):
    logs.mkdir()
    main = project / 'src/main.rs'
    location = project / 'src/location.rs'
    if not main.exists():
        main.write_text('include!(concat!(env!("CARGO_MANIFEST_DIR"), "/src/location.rs"));\n'
                        'fn main() { println!("{}", declared()); }\n')
        location.write_text("fn declared() -> &'static str { file!() }\n")
    args = ['--remap-path-prefix', str(project) + '=' + prefix]
    manifest = PROFILE + MANIFEST + '\n[profile.dev]\nrustflags = ' + json.dumps(args) + '\n'
    toml = project / 'Cargo.toml'
    if not toml.exists() or toml.read_text() != manifest:
        toml.write_text(manifest)
    (logs / 'Cargo.toml').write_text(manifest)
    observed = call([*CARGO, 'run', '--offline', '--quiet'], project, env, logs, 'run')
    assert not observed.stderr
    line, = observed.stdout.decode().splitlines()
    expected = prefix + '/src/location.rs'
    product = Path(env['CARGO_TARGET_DIR']) / 'debug/coverage_case'
    save(logs / 'result.json', {'declared': expected, 'observed': line, 'exe_sha256': digest(product),
                                'files': {p.name: digest(p) for p in (toml, main, location)}})
    if healthy:
        assert line == expected, (line, expected)
    else:
        assert line.startswith('/ohm-workspace/') and line.endswith('/src/location.rs') and line != expected
    return line


def run(root, normal, fixed, base, logs, host):
    assert 'RUSTC_BOOTSTRAP' not in base and host == os.environ['OHM_TARGET']
    stock = Path(os.environ['RUNNER_TEMP']) / 'coverage-rustup/toolchains' / ('1.99.0-' + host)
    tools = stock / 'lib/rustlib' / host / 'bin'
    cases = root / 'coverage-source'; cases.mkdir()
    evidence = logs / 'coverage-source'; evidence.mkdir()
    for name in ('llvm-profdata', 'llvm-cov'):
        tool = tools / name
        assert tool.is_file()
        variable = 'DYLD_LIBRARY_PATH' if host.endswith('apple-darwin') else 'LD_LIBRARY_PATH'
        info = call([tool, '--version'], cases, dict(base, **{variable: str(stock / 'lib')}), evidence, name)
        assert b'23.1.' in info.stdout, info.stdout
    save(evidence / 'tools.json', {name: {'path': str(tools / name), 'sha256': digest(tools / name)}
                                  for name in ('llvm-profdata', 'llvm-cov')})
    for role, sdk, healthy in [('signed', normal, False), ('fixed', fixed, True)]:
        for mode in ('environment', 'profile', 'cargo-rustc'):
            name = role + '-' + mode
            project, env = setup(cases / name, sdk, base)
            coverage(project, env, evidence / name, tools, mode, healthy)
        project, env = setup(cases / (role + '-path'), sdk, base)
        outputs = [remap(project, env, evidence / (role + '-path-' + phase), '/declared-' + phase, healthy)
                   for phase in ('first', 'second')]
        assert (outputs[0] != outputs[1]) == healthy
    # Keep the exact signed compiler and libraries, the same command, and the two target trees.
    mixed = cases / 'hybrid'
    (mixed / 'bin').mkdir(parents=True)
    for p in normal.iterdir():
        if p.name != 'bin':
            (mixed / p.name).symlink_to(p, target_is_directory=p.is_dir())
    for p in (normal / 'bin').iterdir():
        if p.name == 'cargo':
            shutil.copy2(p, mixed / 'bin/cargo')
        else:
            (mixed / 'bin' / p.name).symlink_to(p)
    marker = [mixed / 'bin/rustc']
    for pattern in ('lib/librustc_driver-*', 'lib/rustlib/' + host + '/lib/libstd-*.rlib'):
        one, = list(mixed.glob(pattern))
        marker.append(one)
    before = {str(p.relative_to(mixed)): [p.stat().st_dev,p.stat().st_ino,digest(p)] for p in marker}
    cov_project, cov_env = setup(cases / 'warm-coverage', mixed, base)
    path_project, path_env = setup(cases / 'warm-path', mixed, base)
    summaries = []
    for phase, healthy in [('old', False), ('upgrade', True), ('repeat', True)]:
        if phase == 'upgrade':
            staged = mixed / 'bin/candidate-cargo'
            shutil.copy2(fixed / 'bin/cargo', staged)
            staged.replace(mixed / 'bin/cargo')
        expected = fixed if healthy else normal
        assert digest(mixed / 'bin/cargo') == digest(expected / 'bin/cargo')
        assert {str(p.relative_to(mixed)): [p.stat().st_dev,p.stat().st_ino,digest(p)]
                for p in marker} == before
        # Check the compiler Rustup selects and that its effective sysroot still uses the signed std.
        cfg = call(['rustc','+ohm','--print','sysroot'], cov_project, cov_env, evidence, 'warm-sysroot-' + phase)
        effective = Path(cfg.stdout.decode().strip())
        for p in marker:
            assert (effective / p.relative_to(mixed)).samefile(normal / p.relative_to(mixed))
        row = coverage(cov_project, cov_env, evidence / ('warm-coverage-' + phase), tools, 'environment', healthy)
        path = remap(path_project, path_env, evidence / ('warm-path-' + phase), '/declared-warm', healthy)
        summaries.append({'phase': phase, 'cargo_sha256': digest(mixed / 'bin/cargo'),
                          'coverage': row, 'path': path})
    save(evidence / 'warm-upgrade.json', {'unchanged_rust': before, 'phases': summaries})
