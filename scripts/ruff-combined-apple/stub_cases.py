"""Exercise the full/stub incremental boundary through both Cargo and native rustc."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess


def archive_image(product, logs, name):
    body = product.read_bytes()
    (logs / (name + '.rlib')).write_bytes(body)
    members = subprocess.check_output(['ar', 't', product]).splitlines()
    objects = [item for item in members if item.endswith(b'.rcgu.o')]
    assert b'lib.rmeta' in members and objects
    canonical = body
    names = []
    for member in objects:
        match = re.fullmatch(rb'(green_native_stub-[a-z0-9]+\.[a-z0-9]+\.)([a-z0-9]{7})(\.rcgu\.o)', member)
        assert match and canonical.count(member) >= 1, member
        stable = match[1] + b'0000000' + match[3]
        names.append([member.decode(), stable.decode(), canonical.count(member)])
        canonical = canonical.replace(member, stable)
    return {'raw': hashlib.sha256(body).hexdigest(), 'canonical': hashlib.sha256(canonical).hexdigest(),
            'member_names': names}


def call(directory, env, logs, tag, argv):
    result = subprocess.run(argv, cwd=directory, env=env, capture_output=True, timeout=180)
    (logs / (tag + '.stdout')).write_bytes(result.stdout)
    (logs / (tag + '.stderr')).write_bytes(result.stderr)
    return result


def cargo_history(work, env, logs, role, explicit):
    (work / 'src').mkdir(parents=True)
    (work / 'Cargo.toml').write_text('[package]\nname="green_native_stub"\nversion="0.1.0"\nedition="2021"\n[workspace]\n')
    lib = work / 'src/lib.rs'
    lib.write_text('pub fn value() -> u32 { 17 }\n')
    (work / 'src/main.rs').write_text('fn main() { println!("{}", green_native_stub::value()); }\n')
    (work / 'build.rs').write_text('fn main() { println!("cargo::rerun-if-changed=gate.txt"); }\n')
    (work / 'gate.txt').write_text('old\n')
    target, shared = work / 'target', work / 'shared'
    env = dict(env, CARGO_HOME=str(work / 'cargo-home'), CARGO_TARGET_DIR=str(target),
               CARGO_BUILD_BUILD_DIR=str(shared), CARGO_NET_OFFLINE='true')
    assert call(work, env, logs, 'lock', ['cargo', '+ohm', 'generate-lockfile', '--offline']).returncode == 0
    cmd = ['cargo', '+ohm'] + (['-Zembed-metadata=no'] if explicit else [])
    steps = {}
    affected = explicit and role == 'signed'

    def build(tag, expected=0, error=None, fresh=False):
        result = call(work, env, logs, tag, cmd + ['build', '--lib', '--locked', '--offline', '-vv', '--message-format=json'])
        lines = result.stdout.splitlines()
        build_script = b'[green_native_stub 0.1.0] cargo::rerun-if-changed=gate.txt'
        assert all(line.startswith(b'{') or line == build_script for line in lines)
        messages = [json.loads(line) for line in lines if line.startswith(b'{')]
        errors = [m['message'] for m in messages if m['reason'] == 'compiler-message' and m['message']['level'] == 'error']
        rows = [m for m in messages if m['reason'] == 'compiler-artifact' and m['target']['name'] == 'green_native_stub' and 'lib' in m['target']['kind']]
        drivers = [line for line in result.stderr.decode().splitlines() if 'Running ' in line and '--crate-name green_native_stub ' in line]
        assert result.returncode == expected and len(drivers) == int(not fresh), (tag, result.returncode, errors, drivers)
        if drivers:
            assert 'incremental=' in drivers[0] and ('embed-metadata=no' in drivers[0]) == explicit
        if error:
            assert any(error in e['message'] or e.get('code') and error == e['code']['code'] for e in errors), (tag, errors)
        else:
            assert not errors and len(rows) == 1 and rows[0]['fresh'] == fresh, (tag, rows, errors)
        steps[tag] = {'rc': result.returncode, 'errors': errors, 'drivers': drivers, 'artifacts': rows}
        return [Path(name) for row in rows for name in row['filenames'] if name.endswith('.rlib')]

    def execute(tag, value):
        result = call(work, env, logs, tag, cmd + ['run', '--locked', '--offline', '--quiet'])
        if affected:
            assert result.returncode == 101 and b'failed to create encoded metadata from file' in result.stderr, (tag, result.stderr)
        else:
            assert result.returncode == 0 and result.stdout == f'{value}\n'.encode(), (tag, result.stderr)
        steps[tag] = {'rc': result.returncode, 'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()}

    product, = build('cold')
    build('unchanged', fresh=True)
    execute('cold-binary', 17)
    (work / 'gate.txt').write_text('changed\n')
    expected = 101 if affected else 0
    error = 'failed to create encoded metadata from file' if affected else None
    build('real-build-script-input-edit', expected, error)
    # Preserve the old query graph, and remove every hard-link alias of this requested archive.
    identity = product.stat()
    held = work / 'held'; held.mkdir()
    leaves = [p for area in (target, shared) for p in area.rglob('*.rlib')
              if p.is_file() and os.path.samestat(identity, p.stat())]
    assert product in leaves
    for i, leaf in enumerate(leaves):
        leaf.rename(held / f'{i}-{leaf.name}')
    build('missing-product', expected, error)
    lib.write_text('pub fn value() -> u32 { 29 }\n')
    product, = build('real-native-edit')
    execute('edited-binary', 29)
    original = archive_image(product, logs, "edited")
    lib.write_text('pub fn value() -> u32 { "broken" }\n')
    build('invalid', 101, 'E0308')
    lib.write_text('pub fn value() -> u32 { 29 }\n')
    if not affected:
        build('repair')
        execute('repaired-binary', 29)
        repaired = archive_image(product, logs, "repaired")
        assert repaired["canonical"] == original["canonical"], (repaired, original)
    target.rename(work / 'old-target')
    shared.rename(work / 'old-shared')
    product, = build('independent-empty')
    execute('clean-binary', 29)
    empty = archive_image(product, logs, "empty")
    assert empty["canonical"] == original["canonical"], (empty, original)
    return {'steps': steps, 'new_archive': original, 'empty_archive': empty, 'missing_paths': [str(p) for p in leaves]}


def native(work, env, logs, kind, role, sdk, host):
    work.mkdir()
    (work / 'dep1.rs').write_text('pub fn val() -> u32 { 17 }\n')
    (work / 'main.rs').write_text('extern crate dep1; fn main() { println!("{}", dep1::val()); }\n')
    comp = ['rustc', '+ohm']
    opts = ['-Cprefer-dynamic'] if kind == 'dylib' else []
    args = comp + ['dep1.rs', '--crate-type=' + kind, '--emit=metadata,link',
                   '-Zembed-metadata=no', '-Cincremental=incremental'] + opts
    rows = {}
    for stage in ['cold', 'warm', 'warm-again']:
        result = call(work, env, logs, stage, args)
        failure = role == 'signed' and stage != 'cold'
        assert result.returncode == int(failure), (kind, stage, result.stderr)
        if failure:
            assert b'failed to create encoded metadata from file' in result.stderr
        rows[stage] = {'rc': result.returncode, 'stderr': result.stderr.decode()}
    if role == 'fixed':
        result = call(work, env, logs, 'consume', comp + ['main.rs', '-L', '.', '-o', 'consume'] + opts)
        assert result.returncode == 0, result.stderr
        libs = os.pathsep.join(map(str, [work, sdk / 'lib/rustlib' / host / 'lib', sdk / 'lib']))
        result = call(work, dict(env, LD_LIBRARY_PATH=libs, DYLD_LIBRARY_PATH=libs), logs, 'execute', [work / 'consume'])
        assert result.returncode == 0 and result.stdout == b'17\n', result.stderr
        rows['execute'] = result.stdout.decode()
    return rows


def qualify(root, signed, fixed, env, logs, host):
    out = {}
    for role, sdk in [('signed', signed), ('fixed', fixed)]:
        ru = root / ('stub-' + role + '-rustup') / 'toolchains'; ru.mkdir(parents=True)
        (ru / 'ohm').symlink_to(sdk, target_is_directory=True)
        own = dict(env, RUSTUP_HOME=str(ru.parent), RUSTUP_TOOLCHAIN='ohm')
        for tool in ['cargo', 'rustc']:
            actual = subprocess.check_output(['rustup', 'which', '--toolchain', 'ohm', tool], env=own, text=True).strip()
            assert Path(actual).samefile(sdk / 'bin' / tool)
        for label in ['default', 'explicit', 'rlib', 'dylib']:
            key = 'stub-' + role + '-' + label
            dest = logs / key; dest.mkdir()
            if label in ['rlib', 'dylib']:
                result = native(root / key, own, dest, label, role, sdk, host)
            else:
                result = cargo_history(root / key, own, dest, role, label == 'explicit')
            out[key] = result
            (dest / 'verified.json').write_text(json.dumps(result, indent=2) + '\n')
    (logs / 'green-stub.json').write_text(json.dumps(out, indent=2) + '\n')
