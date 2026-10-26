#!/usr/bin/env python3
"""Build both full toolchains' native Ruff oracles through identical canonical paths."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess


RUFF = '93526150df078af7dd8fc4226cdcc469539d2001'
SELECTION = {
    'build': ('crates/ruff/src/main.rs', b'"ruff failed"', b'"Ruff failed"', 'ruff', ['build'], 501, 6, 8),
    'test': ('crates/ruff_python_formatter/tests/fixtures.rs', b'"Unformatted code to be valid syntax"',
             b'"unformatted code to be valid syntax"', 'fixtures', ['test', '--no-run'], 619, 102, 24),
}
DRIVER = 'lib/librustc_driver-774a793a844d5500.so'
WILD = 'lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd'
GIB = 1 << 30
FLOOR_GIB = 24


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def identities(paths):
    stamp = {}
    for name, path in paths.items():
        stat = path.stat()
        stamp[name] = [stat.st_dev, stat.st_ino, stat.st_ctime_ns, stat.st_size]
    return stamp


def check_compilers(out, arm, runtime, driver):
    path = out/'compiler-identities.json'
    all_arms = json.loads(path.read_text()) if path.exists() else {}
    fingerprints = identities({'frontend':runtime/'bin/rustc','default_driver':runtime/DRIVER,
                               'selected_driver':driver})
    if arm in all_arms:
        assert fingerprints == all_arms[arm], ('compiler identity changed',arm,fingerprints,all_arms[arm])
    else:
        all_arms[arm] = fingerprints
        save(path,all_arms)


def capture(repo, env, command, directory, state, prefix=()):
    directory.mkdir()
    args = [*prefix, 'cargo', '+ohm', *command, '--locked', '--offline', '--message-format=json']
    with (directory/'stdout.jsonl').open('wb') as out, (directory/'stderr').open('wb') as err:
        p = subprocess.Popen(args, cwd=repo, env=env, stdout=out, stderr=err, start_new_session=True)
        while True:
            try:
                rc=p.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                if shutil.disk_usage(state).free < FLOOR_GIB*GIB:
                    os.killpg(p.pid,signal.SIGTERM)
                    p.wait()
                    raise RuntimeError('scratch reserve reached during warmup')
        if rc:
            raise RuntimeError((args,rc,(directory/'stderr').read_text()[-1800:]))
    artifacts=[r for r in map(json.loads,(directory/'stdout.jsonl').read_text().splitlines())
               if r['reason']=='compiler-artifact']
    graph=[]
    outputs={}
    dirty=[]
    for row in artifacts:
        target=row['target']
        key=json.dumps([row['package_id'], target['name'], target['kind'], row['features'], row['profile']],
                       separators=(',', ':'), sort_keys=True)
        graph.append(key)
        if not row['fresh']:
            dirty.append(target['name'])
        if row['executable']:
            if key in outputs:
                raise ValueError(('duplicate output identity',key))
            path=Path(row['executable'])
            outputs[key]={'file':str(path),'sha256':sha(path),'bytes':path.stat().st_size}
    observation={'graph':sorted(graph),'outputs':outputs,'dirty':dirty}
    save(directory/'result.json',observation)
    return observation


def compare(reference, observed):
    diffs=[]
    if reference['graph']!=observed['graph']:
        diffs.append({'graph':True})
    for key in sorted(reference['outputs'].keys()|observed['outputs'].keys()):
        a=reference['outputs'].get(key)
        b=observed['outputs'].get(key)
        if a is None or b is None or a['sha256']!=b['sha256']:
            diffs.append({'target':key,'parent':a,'stack':b})
    return diffs


def install(source, destination):
    assert not destination.is_symlink()
    destination.parent.chmod(destination.parent.stat().st_mode | 0o200)
    incoming=destination.with_name(destination.name+'.incoming')
    shutil.copy2(source,incoming)
    os.replace(incoming,destination)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode',choices=SELECTION)
    ap.add_argument('ruff',type=Path)
    ap.add_argument('spec',type=Path,help='immutable sysroot, component and digest manifest')
    ap.add_argument('state',type=Path,help='new directory on the scratch volume')
    ap.add_argument('output',type=Path,help='new directory for native logs and outcome')
    args=ap.parse_args()
    spec=json.loads(args.spec.read_text())
    repo,state,out=args.ruff.resolve(strict=True),args.state.resolve(),args.output.resolve()
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==RUFF
    assert not subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=repo)
    rel,old,new,unit,command,units,exes,budget=SELECTION[args.mode]
    assert shutil.disk_usage(state.parent).free >= (2*budget+FLOOR_GIB)*GIB
    source=repo/rel; original=source.read_bytes()
    assert original.count(old)==1 and new not in original
    states={'original':original,'changed':original.replace(old,new)}
    common=Path(spec['runtime']).resolve(strict=True)
    registry=Path(spec['registry']).resolve(strict=True)
    assert common.is_dir() and registry.is_dir()
    for rel,digest in spec['common_hashes'].items():
        assert sha(common/rel)==digest,rel
    state.mkdir()
    out.mkdir(parents=True)
    store=state/'arms';store.mkdir()
    active=state/'active'
    rustup=state/'rustup';(rustup/'toolchains').mkdir(parents=True)
    (rustup/'settings.toml').write_text('version = "12"\nprofile = "minimal"\n')
    (rustup/'toolchains/ohm').symlink_to(active/'toolchain')
    clang=state/'clang';real=shutil.which('clang');assert real
    clang.write_text('#!/bin/sh\nexec '+shlex.quote(real)+' "$@" '+shlex.quote('--ld-path='+str(active/'toolchain'/WILD))+' -Wl,--no-fork\n')
    clang.chmod(0o755)
    env=dict(os.environ,RUSTUP_HOME=str(rustup),RUSTUP_AUTO_INSTALL='0',
             CARGO_HOME=str(active/'cargo-home'),CARGO_TARGET_DIR=str(active/'target'),
             CARGO_BUILD_BUILD_DIR=str(active/'shared'),CARGO_BUILD_JOBS='4',CARGO_TERM_COLOR='never',
             CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=str(clang),
             CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST='all',CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST='all',
             SSL_CERT_FILE='/etc/ssl/certs/ca-certificates.crt',SSL_CERT_DIR='/etc/ssl/certs')
    for key in ['RUSTC','RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS']:
        assert not env.get(key),key
    for arm in ['parent','stack']:
        root=store/arm;root.mkdir();(root/'toolchain').mkdir()
        subprocess.run(['cp','-a','--reflink=auto',str(common)+'/.' ,root/'toolchain'],check=True)
        (root/'cargo-home').mkdir();(root/'cargo-home/registry').symlink_to(registry)
        for name,rel in [('cargo','bin/cargo'),('driver',DRIVER),('wild',WILD)]:
            item=spec['arms'][arm][name];path=Path(item['path']).resolve(strict=True)
            assert sha(path)==item['sha256']
            install(path,root/'toolchain'/rel)
            assert sha(root/'toolchain'/rel)==item['sha256']
        for rel,digest in spec['common_hashes'].items():
            assert sha(root/'toolchain'/rel)==digest
        assert (root/'toolchain/bin/rustc').stat().st_nlink==1
        (root/'chosen-arm').write_text(arm)
    observed={}
    curr=None
    limit=2*budget*GIB
    try:
        for arm in ['parent','stack']:
            first_free=shutil.disk_usage(state).free
            if curr:active.rename(store/curr)
            (store/arm).rename(active);curr=arm
            runtime=active/'toolchain'
            reported=subprocess.check_output(['rustc','+ohm','--print','sysroot'],env=env,text=True).strip()
            assert Path(reported).resolve(strict=True)==runtime.resolve(strict=True),(reported,runtime)
            check_compilers(out,arm,runtime,runtime/DRIVER)
            version=subprocess.check_output(['rustc','+ohm','-Vv'],env=env,text=True)
            assert spec['rustc_commit'] in version and 'LLVM version: 23.1.1' in version,version
            for label,edit in [('warm','original'),('changed','changed'),('original','original')]:
                data=source.read_bytes();assert data in states.values()
                if data != states[edit]:source.write_bytes(states[edit])
                input_paths={'cargo':runtime/'bin/cargo','wild':runtime/WILD}
                before=identities(input_paths)
                check_compilers(out,arm,runtime,runtime/DRIVER)
                result=capture(repo,env,command,out/(arm+'-'+label),state)
                check_compilers(out,arm,runtime,runtime/DRIVER)
                assert identities(input_paths)==before
                assert len(result['graph'])==units and len(result['outputs'])==exes
                if label!='warm':assert result['dirty']==[unit],(label,result['dirty'])
                for target,output in result['outputs'].items():
                    if json.loads(target)[1]==unit:
                        archive=state/'native-leaves'/arm/output['sha256']
                        archive.parent.mkdir(parents=True,exist_ok=True)
                        if not archive.exists():
                            subprocess.run(['cp','--reflink=auto',output['file'],archive],check=True)
                        assert sha(archive)==output['sha256']
                        output['archive']=str(archive)
                    elif label!='warm':
                        assert observed[arm,'warm']['outputs'][target]['sha256']==output['sha256']
                observed[arm,label]=result
                print(args.mode,arm,label,'units',units,'executables',exes,'dirty',len(result['dirty']),flush=True)
            used=first_free-shutil.disk_usage(state).free
            if arm=='parent' and (used>limit or shutil.disk_usage(state).free < max(used,budget*GIB)+FLOOR_GIB*GIB):
                raise RuntimeError(f'private state requires {used/GIB:.1f} GiB with insufficient capacity for a second arm')
        comparisons={label:compare(observed['parent',label],observed['stack',label]) for label in ['warm','changed','original']}
        if any(comparisons.values()):
            outcome={'status':'different-native-products','mode':args.mode,'compared_executables':exes,
                     'comparisons':comparisons}
            save(out/'outcome.json',outcome)
            print('Native oracle mismatches',args.mode,
                  {phase:[json.loads(x['target'])[1] if 'target' in x else 'unit graph' for x in rows]
                   for phase,rows in comparisons.items()},flush=True)
            return 12
        save(out/'outcome.json',{'status':'native-oracles-match','mode':args.mode,'units':units,'executables':exes})
    finally:
        if source.read_bytes()==states['changed']:source.write_bytes(original)
        if curr and active.exists():active.rename(store/curr)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
