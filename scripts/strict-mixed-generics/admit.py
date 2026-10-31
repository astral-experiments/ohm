"""Native executable, metadata, profile-transition and previous-sysroot admissions. No scores."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import HOST, WILD, WILD_SHA, CARGO_SHA, STAGE0, measured_file
from source import HERE, SIGNED, require, sha, write_json

ROOT = Path(os.environ.get('QA_ROOT', '.')).resolve()
RECEIPTS = ROOT / 'receipts'
FAMILY = HERE / 'source/fixture'
CHECKED = ['-Cdebuginfo=0', '-Cdebug-assertions=yes', '-Coverflow-checks=yes', '-Zub-checks=yes', '-Ccodegen-units=1', '-Csymbol-mangling-version=v0']


def invocation(name, args, cwd, env=None, expected=0, code=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True)
    place = RECEIPTS / name; place.mkdir(parents=True)
    (place / 'stdout').write_bytes(result.stdout); (place / 'stderr').write_bytes(result.stderr)
    write_json(place / 'command.json', {'argv': list(map(str, args)), 'cwd': str(cwd), 'status': result.returncode})
    err = result.stderr.decode(errors='replace')
    observed = (result.stdout + result.stderr).lower()
    require(all(marker not in observed for marker in (b'internal compiler error', b'the compiler unexpectedly panicked', b'the compiler panicked')), name + ' compiler panic')
    require(result.returncode == expected, name + ': ' + err[-2500:])
    if code: require(re.search(r'\b' + code + r'\b', err) is not None, name + ' wrong compiler diagnostic: ' + err[-1300:])
    return result.stdout.decode(errors='replace')


def expand(role, artifacts):
    source = artifacts / role
    record = json.loads((source / 'manifest.json').read_text()); archive = source / 'toolchain.tar.zst'
    product = json.loads((HERE / 'source/product.json').read_text()); old = json.loads((HERE / 'source/legacy220.json').read_text())
    expected = {'parent': (SIGNED['signed_rust'], SIGNED['signed_tree']), 'candidate': (product['port'], product['tree']), 'legacy': (old['commit'], old['tree'])}[role]
    require(record['role'] == role and (record['commit'], record['tree']) == expected and record['qa'] == os.environ['GITHUB_SHA'], 'unexpected role/run/revision')
    require(sha(archive) == record['transfer'] and record['stage0'] == STAGE0, 'bad transfer')
    dest = ROOT / role; dest.mkdir()
    remaining = set(record['files'])
    with subprocess.Popen(['zstd','-qdc',archive],stdout=subprocess.PIPE) as z:
        with tarfile.open(fileobj=z.stdout,mode='r|') as tar:
            for entry in tar:
                path = Path(entry.name)
                require(entry.isfile() and not path.is_absolute() and '..' not in path.parts and entry.name in remaining, 'unregistered SDK member')
                remaining.remove(entry.name); tar.extract(entry, dest, filter='data')
                (dest/path).chmod(record['files'][entry.name][2])
        require(not any(z.stdout.read()) and not remaining and z.wait() == 0,'incomplete SDK stream')
    actual = {str(p.relative_to(dest)): measured_file(p) for p in dest.rglob('*') if p.is_file()}
    require(actual == record['files'], role + ': stage1 membership differs')
    if role != 'legacy': require(sha(dest / WILD) == WILD_SHA and sha(dest / 'bin/cargo') == CARGO_SHA, 'wrong Cargo or Wild')
    return dest, record


def metadata(kit, old, other, stock, role):
    work = ROOT / ('metadata-' + role); work.mkdir()
    exe = kit / 'bin/rustc'
    app = work / 'app.rs'; app.write_text('extern crate qa_exporter; #[no_mangle] pub fn bare_pointer() -> fn(u64)->u64 { qa_exporter::probe::<u16> } fn main() { let x = std::hint::black_box(40); assert_eq!(qa_exporter::emit(x),42); println!("{}",std::hint::black_box(bare_pointer())(x)); }\n')
    opts = [exe, app, '-Copt-level=1', *CHECKED, '--error-format=json']
    for name, rlib in [('matched', kit / 'specimen/libqa_exporter-qabare.rlib'), ('cross-epoch', other / 'specimen/libqa_exporter-qabare.rmeta'), ('untagged-user', old / 'specimen/libqa_exporter-qabare.rmeta')]:
        out = work / name
        args = [*opts, '--extern', 'qa_exporter=' + str(rlib), '-o', str(out)]
        if name != 'matched': args += ['--emit=metadata']
        invocation(role + '/metadata/' + name, args, work, expected=0 if name == 'matched' else 1, code=None if name == 'matched' else 'E0514')
        if name == 'matched': require(invocation(role + '/metadata/run-matched', [out], work) == '42\n', 'wrong matched user result')
        else: require(not out.exists(), 'rejected incompatible metadata was written')
    # Exactly this path, inside the selected physical sysroot, is the positive legacy contract. The same bytes outside were rejected above.
    old_lib = old / 'lib/rustlib' / HOST / 'lib'
    source_rlib = old / 'specimen/libqa_exporter-qabare.rlib'; installed = old_lib / source_rlib.name
    if not installed.exists(): shutil.copy2(source_rlib, installed)
    require(sha(source_rlib) == sha(installed), 'changed bare exporter')
    out = work / 'bare-app'
    ir = work / 'bare.ll'
    invocation(role + '/metadata/untagged-selected-sysroot', [*opts, '--sysroot', old, '--extern', 'qa_exporter=' + str(installed), '--emit=llvm-ir=' + str(ir) + ',link=' + str(out)], work)
    require(invocation(role + '/metadata/run-untagged', [out], work) == '42\n', 'wrong real legacy result')
    body, = re.findall(r'^define [^\n]* @bare_pointer\([^\n]*\n(.*?)^}', ir.read_text(), flags=re.S|re.M)
    symbol, = re.findall(r'^\s*ret ptr @(\S+)',body,flags=re.M)
    require('probe' in symbol and any(l.startswith('declare ') and '@'+symbol+'(' in l for l in ir.read_text().splitlines()), 'legacy exporter was not actually shared')
    simple = work / 'stock.rs'; simple.write_text('fn main() { println!("stock"); }\n')
    invocation(role + '/metadata/official-stock-rejected', [exe, simple, '--sysroot', stock, '--emit=metadata', '-o', work / 'rejected.rmeta', '--error-format=json'], work, expected=1, code='E0514')
    require(not (work / 'rejected.rmeta').exists(), 'incompatible stock was accepted')
    return symbol


def pointers(ir):
    values = {}
    for name in ('hinted', 'never', 'foreign'):
        body, = re.findall(r'^define [^\n]* @' + name + r'_pointer\([^\n]*\n(.*?)^}', ir, flags=re.M | re.S)
        target, = re.findall(r'^\s*ret ptr @(\S+)', body, flags=re.M)
        require(name in target, 'unexpected pointer: ' + target)
        values[name] = 'provider' in target
    return values


def target_matrix(kit, role):
    rustc = kit / 'bin/rustc'; answer = {}; fixture = HERE / 'cross'
    key = subprocess.check_output(['git','hash-object',fixture/'minicore.rs'],text=True).strip()
    require(key == 'b732088553bb37336f6fa954f79a329e7508f624', 'changed rustc minicore fixture')
    for target in (HOST, 'aarch64-unknown-linux-gnu', 'custom-host'):
        work = ROOT / (role + '-target-' + target); work.mkdir()
        target_arg = target
        if target == 'custom-host':
            target_arg = work / (HOST + '.json')
            spec = invocation(role+'/target/'+target+'/target-spec',[rustc,'--target',HOST,'-Zunstable-options','--print=target-spec-json'],work)
            target_arg.write_text(spec)
        for name,deps,opt in [('minicore', [],0),('shared',['minicore'],0),('provider',['minicore','shared'],0),('consumer',['minicore','shared','provider'],1)]:
            flags = [rustc,fixture/(name+'.rs'),'-Zunstable-options','--target',target_arg,'--crate-type=rlib',*CHECKED,f'-Copt-level={opt}','-Ldependency=.']
            for dep in deps: flags += ['--extern',dep+'=lib'+dep+'.rlib']
            if name == 'consumer': flags += ['--emit=llvm-ir,link']
            invocation(role+'/target/'+target+'/'+name,flags,work)
        ir = (work/'consumer.ll').read_text(); triple, = re.findall(r'^target triple = "([^"]+)"$',ir,flags=re.M)
        require(triple == (HOST if target == 'custom-host' else target), 'wrong LLVM backend: '+triple)
        body, = re.findall(r'^define [^\n]* @hinted_pointer\([^\n]*\n(.*?)^}',ir,flags=re.M|re.S)
        sym, = re.findall(r'^\s*ret ptr @(\S+)',body,flags=re.M)
        require('hinted' in sym, 'missing observed generic'); answer[target] = 'provider' in sym
        write_json(RECEIPTS/role/'target'/target/'symbol.json',{'triple':triple,'symbol':sym})
    return answer


def raw_matrix(kit, role):
    rustc = kit / 'bin/rustc'; results = {}
    for public in ('no', 'yes'):
        work = ROOT / (role + '-raw-' + public); work.mkdir()
        flags = [*CHECKED, '-Zpublic-api-hash=' + public, '-Ldependency=.']
        invocation(role + '/' + public + '/shared', [rustc, FAMILY / 'shared.rs', '-Copt-level=0', *flags], work)
        for label, p_opt, c_opt, pflags, cflags in [
            ('mixed', 0, 1, [], []), ('homogeneous-1', 1, 1, [], []), ('homogeneous-0', 0, 0, [], []),
            ('other-direction', 1, 0, [], []), ('producer-forces-yes', 0, 1, ['-Zshare-generics=yes'], []),
            ('producer-forces-no', 0, 1, ['-Zshare-generics=no'], []), ('consumer-forces-yes', 0, 1, [], ['-Zshare-generics=yes']),
            ('consumer-forces-no', 0, 1, [], ['-Zshare-generics=no']), ('producer-no-ub', 0, 1, ['-Zub-checks=no'], []),
            ('repaired', 0, 1, [], [])]:
            name = role + '/' + public + '/' + label
            invocation(name + '/producer', [rustc, FAMILY / 'provider.rs', f'-Copt-level={p_opt}', *flags, *pflags, '-Cincremental=incr-provider', '--extern', 'shared=libshared.rlib'], work)
            invocation(name + '/consumer', [rustc, FAMILY / 'consumer.rs', f'-Copt-level={c_opt}', *flags, *cflags, '-Cincremental=incr-consumer', '--emit=llvm-ir,link', '--extern', 'shared=libshared.rlib', '--extern', 'provider=libprovider.rlib'], work)
            ir = (work / 'consumer.ll').read_text(); got = pointers(ir)
            invocation(name + '/run', [work / 'consumer'], work)
            write_json(RECEIPTS / name / 'symbols.json', got)
            results[public + '/' + label] = got
    return results


AXES = '''pub fn observed(x: u8) -> (bool,bool,bool) {
    (cfg!(debug_assertions), std::panic::catch_unwind(|| std::hint::black_box(x) + 1).is_err(), core::intrinsics::ub_checks())
}
'''


def axes(kit, role):
    exe = kit / 'bin/rustc'; base = ROOT / (role + '-axes'); base.mkdir()
    lib = base / 'export.rs'; app = base / 'axes_main.rs'
    feature = '#![feature(core_intrinsics)]\n#![allow(internal_features)]\n'
    lib.write_text(feature + AXES + '#[inline] pub fn generic<T>(x: u8) -> (bool,bool,bool) { let _ = size_of::<T>(); observed(x) }\npub fn anchor(x:u8)->(bool,bool,bool){ generic::<u16>(x) }\n')
    app.write_text(feature + 'extern crate export;\n' + AXES + 'fn main() { let x=std::hint::black_box(255); println!("{:?} {:?} {:?}",export::anchor(x),observed(x),export::generic::<u16>(x)); }\n')
    results = {}
    for label, p, c in [('all', '111', '111'), ('p-nodebug', '011', '111'), ('p-nooverflow', '101', '111'), ('p-noub', '110', '111'), ('c-nodebug', '111', '011'), ('c-nooverflow', '111', '101'), ('c-noub', '111', '110')]:
        def flags(bits): return [a + ('yes' if b == '1' else 'no') for a,b in zip(('-Cdebug-assertions=', '-Coverflow-checks=', '-Zub-checks='),bits)]
        invocation(role + '/axes/' + label + '/lib', [exe, lib, '--crate-type=rlib', '-Copt-level=0', '-Cdebuginfo=0', *flags(p)], base)
        invocation(role + '/axes/' + label + '/app', [exe, app, '--extern', 'export=libexport.rlib', '-Copt-level=1', '-Cdebuginfo=0', *flags(c)], base)
        result = invocation(role + '/axes/' + label + '/run', [base / 'axes_main'], base).strip()
        truth = lambda bits: '(' + ', '.join('true' if b == '1' else 'false' for b in bits) + ')'
        require(result.startswith(truth(p) + ' ' + truth(c) + ' '), label + ' changed declared debug/overflow/UB semantics: ' + result)
        results[label] = result
    return results


def cargo_transitions(kit, role):
    root = ROOT / (role + '-cargo'); root.mkdir()
    project = root / 'workspace'; project.mkdir()
    (project / 'Cargo.toml').write_text('[workspace]\nmembers=["shared","provider","consumer"]\nresolver="3"\n[profile.dev]\nopt-level=1\ndebug=0\ndebug-assertions=true\noverflow-checks=true\nincremental=true\n')
    for name, deps in [('shared', []), ('provider', ['shared']), ('consumer', ['shared', 'provider'])]:
        crate = project / name; (crate / 'src').mkdir(parents=True)
        (crate / 'Cargo.toml').write_text('[package]\nname="'+name+'"\nversion="0.1.0"\nedition="2021"\n[dependencies]\n' + ''.join(d+'={path="../'+d+'"}\n' for d in deps))
        data = (FAMILY / (name + '.rs')).read_text()
        if name == 'provider': data += '\npub fn current_value() -> u8 { 17 }\n'
        if name == 'consumer': data = data.replace('fn main() {', 'fn main() { println!("{}", provider::current_value());')
        (crate / 'src' / ('main.rs' if name == 'consumer' else 'lib.rs')).write_text(data)
    base = {k:v for k,v in os.environ.items() if not k.startswith(('CARGO_', 'RUSTC_', 'RUSTUP_', 'RUSTFLAGS')) and k not in ('RUSTC', 'RUSTDOC', 'LD_PRELOAD')}
    base.update(RUSTUP_HOME=str(root / 'rustup'), CARGO_HOME=str(root / 'cargo-home'), CARGO_INCREMENTAL='1', CARGO_NET_OFFLINE='true')
    invocation(role + '/cargo/link-toolchain', ['rustup', 'toolchain', 'link', 'ohm', kit], project, base)
    proxy = shutil.which('cargo'); require(proxy is not None, 'rustup Cargo proxy missing')
    producer = project / 'provider/src/lib.rs'; original = producer.read_text(); answers = {}
    def visit(label, store, opt, output=None, invalid=False):
        target = root / ('target-' + store)
        env = {**base, 'CARGO_TARGET_DIR': str(target), 'CARGO_BUILD_BUILD_DIR': str(root / ('build-' + store))}
        prefix = role + '/cargo/' + label
        command = [proxy, '+ohm', '--offline', '--config', 'profile.dev.package.shared.opt-level=0', '--config', f'profile.dev.package.provider.opt-level={opt}', 'build', '-p', 'consumer', '-vv', '--message-format=json']
        stdout = invocation(prefix + '/build', command, project, env, expected=101 if invalid else 0)
        lines = [json.loads(s) for s in stdout.splitlines() if s.strip()]
        if invalid:
            codes = [i['message']['code']['code'] for i in lines if i['reason'] == 'compiler-message' and i['message'].get('level') == 'error' and i['message'].get('code')]
            require(codes == ['E0308'] and lines[-1] == {'reason':'build-finished','success':False}, 'lost malformed edit verdict')
            return
        require(lines[-1] == {'reason':'build-finished', 'success':True}, 'Cargo did not finish')
        artifacts = {i['target']['name']:i for i in lines if i['reason'] == 'compiler-artifact'}
        require(set(artifacts) == {'consumer','shared','provider'} and artifacts['provider']['profile']['opt_level'] == str(opt), 'wrong unit/profile roster')
        executable = Path(artifacts['consumer']['executable']); require(executable.is_file(), 'missing native executable')
        observed = invocation(prefix + '/run', [executable], project, env).strip(); require(observed == str(output), 'stale Cargo executable: ' + label)
        # Cargo can retain different build IDs and debug paths in the two isolated stores. Compare the executed contract instead.
        write_json(RECEIPTS / prefix / 'observation.json', {'output': observed, 'elf':sha(executable), 'fresh':{n:i['fresh'] for n,i in artifacts.items()}, 'producer_opt':str(opt)})
        answers[label] = observed
    for label, store, opt in [('initial','history',0), ('repeat','history',0), ('flip-o1','history',1), ('empty-o1','empty-o1',1), ('return-o0','history',0), ('empty-o0','empty-o0',0)]:
        visit(label, store, opt, 17)
    producer.write_text(original.replace('-> u8 { 17 }','-> u8 { 29 }'))
    visit('edited','history',0,29); visit('edited-empty','empty-edit',0,29)
    producer.write_text(original.replace('-> u8 { 17 }','-> u8 { "malformed" }'))
    visit('invalid','history',0,invalid=True); visit('invalid-empty','empty-bad',0,invalid=True)
    producer.write_text(original); visit('repaired','history',0,17); visit('repair-empty','empty-repair',0,17)
    return answers


def main(artifacts, stock):
    RECEIPTS.mkdir(parents=True)
    roles = {r: expand(r, artifacts) for r in ['parent','candidate','legacy']}
    graph = ROOT / 'incremental-transaction'
    invocation('incremental/worker', [sys.executable, '-IB', HERE/'incremental.py', '--old', roles['parent'][0], '--new', roles['candidate'][0], '--work', graph], ROOT)
    invocation('incremental/independent-reader', [sys.executable, '-IB', HERE/'verify_incremental.py', graph], ROOT)
    # Retain the raw streams and rmeta envelope used by the independent reader.
    report = json.loads((graph/'completed.json').read_text())
    for item in report['commands']:
        require(item['exit'] == (1 if item['label'].startswith('reject-user-') else 0), 'wrong native incremental test status')
    shutil.copy2(graph/'completed.json', RECEIPTS/'incremental/completed.json')
    for source in (graph/'raw').rglob('*'):
        if source.is_file() and source.name in ('stdout','stderr','libsubject.rmeta'):
            target = RECEIPTS/'incremental/raw'/source.relative_to(graph/'raw');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    p, c, l = [roles[r][1] for r in roles]
    require(p['flags'] == c['flags'] == l['flags'] and p['version'] == c['version'] == l['version'] and p['llvm'] == c['llvm'] == l['llvm'], 'stage environments differ')
    fixture = json.loads((HERE/'source/product.json').read_text())['files']
    for n in ('shared.rs','provider.rs','consumer.rs'):
        item = 'tests/run-make/ohm-profile-aware-shared-generics/' + n
        blob = subprocess.check_output(['git','hash-object',FAMILY/n],text=True).strip()
        require(fixture[item]['pr_head'].split()[2] == blob and fixture[item]['signed_patched'].split()[2] == blob,'product fixture differs')
    require(subprocess.check_output([stock/'bin/rustc','-vV'],text=True).splitlines()[0].startswith('rustc 1.99.0 (b940084d7 '), 'not official Rust 1.99.0')
    stock_cmd = [stock/'bin/rustc','-vV']; invocation('stock/release', stock_cmd, ROOT)
    hello = ROOT/'official.rs'; hello.write_text('fn main() { println!("stock=42"); }\n')
    invocation('stock/compile-self',[stock/'bin/rustc',hello,'-o',ROOT/'official'],ROOT)
    require(invocation('stock/run-self',[ROOT/'official'],ROOT) == 'stock=42\n','official SDK not usable on its own')
    results = {}
    for role, other in [('parent','candidate'),('candidate','parent')]:
        kit = roles[role][0]; bare_symbol = metadata(kit, roles['legacy'][0], roles[other][0], stock, role)
        results[role] = {'bare_export':bare_symbol, 'targets':target_matrix(kit,role), 'raw':raw_matrix(kit,role), 'axes':axes(kit,role), 'cargo':cargo_transitions(kit,role)}
    require(results['parent']['bare_export'] == results['candidate']['bare_export'], 'new reader changed ownership of the genuine untagged export')
    require(results['parent']['targets'] == {HOST:True,'aarch64-unknown-linux-gnu':True,'custom-host':True} and results['candidate']['targets'] == {HOST:False,'aarch64-unknown-linux-gnu':True,'custom-host':True}, 'wrong native/cross-target ownership')
    require(results['parent']['axes'] == results['candidate']['axes'], 'candidate changed checked behavior')
    require(results['parent']['cargo'] == results['candidate']['cargo'], 'candidate changed Cargo output')
    for key, old in results['parent']['raw'].items():
        new = results['candidate']['raw'][key]
        if key.endswith(('/mixed','/repaired')):
            require(old == {'hinted':True,'never':True,'foreign':True} and new == {**old,'hinted':False}, 'did not isolate advertised symbol change: ' + key)
        else: require(old == new, 'out-of-contract difference: ' + key)
    write_json(RECEIPTS/'qualification.json', {'results': results,'roles':{k:{x:r[x] for x in ['commit','tree','metadata','transfer']} for k,(_,r) in roles.items()},'status':'pass'})


if __name__ == '__main__': main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
