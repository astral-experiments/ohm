"""Independent mechanism replay of the original three-file Ruff #19021 commit on the matched pair."""
from pathlib import Path
from collections import Counter
import re
import shutil
import tomllib
import hashlib
import json
import os
import subprocess
import sys
import time

study = Path(os.environ["RUNNER_TEMP"]) / "ohm-original-ruf009"
root = study / "receipt"
root.mkdir()
arm = sys.argv[1]
opened = Path(json.loads((study/"sdk.json").read_text())["directory"]).resolve(strict=True)
assert arm in ('p', 'c')
label = {'p':'normal','c':'defer'}[arm]
work = Path(os.environ['GITHUB_WORKSPACE'])/'ruff'
old = '710c60f7135879b05f6c05a34085cd7af5c19e7f'
new = 'b00f68a23cedbd3a38fc25bac63638f0f11fc3f0'
out = root / arm
out.mkdir()
state=study/"state"
state.mkdir()
git = lambda *args: subprocess.check_output(['git', *args], cwd=work, text=True).strip()
assert git('rev-parse','HEAD') == new and git('rev-parse',new+'^') == old and not git('status','--porcelain')
git('checkout','--detach',old)
assert git('rev-parse','HEAD') == old
assert hashlib.sha256((work/'Cargo.lock').read_bytes()).hexdigest() == '47d65136d6cf3743b88970429f5e3bf39e788afe8c35ca5ce2f94939648086eb'
changed = git('diff','--name-only',old,new).splitlines()
assert len(changed)==3 and len([n for n in changed if n.endswith('.rs')])==1
alias = state/'rustup'
sdk = (opened/label).resolve(strict=True)
manifest = json.loads((opened/'rustcs.json').read_bytes())['arms'][label]
assert Path(manifest['root']).samefile(sdk)
home=state/'home'
home.mkdir()
env = {'HOME':str(home),'PATH':os.environ['PATH'],'LC_ALL':'C','GIT_CONFIG_NOSYSTEM':'1',
       'GIT_CONFIG_GLOBAL':'/dev/null','RUSTUP_AUTO_INSTALL':'0','RUSTUP_HOME':str(alias),'CARGO_HOME':str(study/'cargo-home'),'CARGO_TARGET_DIR':str(state/'target'),
       'CARGO_BUILD_BUILD_DIR':str(state/'build'),'LD_LIBRARY_PATH':str(sdk/'lib'),'CARGO_NET_OFFLINE':'true'}
assert not any(env.get(k) for k in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','RUSTC','RUSTC_WORKSPACE_WRAPPER','RUSTC_WRAPPER','LD_PRELOAD',
                                    'CARGO_LOG','CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST','CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'))

def sha(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

driver, = (sdk/'lib').glob('librustc_driver-*.so')
assert sha(driver) == manifest['files'][str(driver.relative_to(sdk))]
assert sha(sdk/'bin/cargo') == 'f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee'
assert not env.get("GH_TOKEN") and not env.get("GITHUB_TOKEN")
proxy = state/'proxies'
proxy.mkdir()
rustup = Path(shutil.which('rustup')).resolve(strict=True)
for tool in ('rustup','rustc','rustdoc','cargo'):
    (proxy/tool).symlink_to(rustup)
env['PATH'] = str(proxy) + os.pathsep + env['PATH']
subprocess.run(['rustup','toolchain','link','ohm',sdk],env=env,cwd=work,check=True)
online=dict(env, CARGO_NET_OFFLINE='false', CARGO_NET_GIT_FETCH_WITH_CLI='true', GIT_TERMINAL_PROMPT='0')
subprocess.run(['cargo','+ohm','fetch','--locked'],env=online,cwd=work,check=True)
lock=tomllib.loads((work/'Cargo.lock').read_text())['package']
wanted={p['name']+'-'+p['version']+'.crate':p['checksum'] for p in lock if p.get('source','').startswith('registry+')}
fetched={p.name:sha(p) for p in (study/'cargo-home/registry/cache').glob('*/*.crate')}
assert fetched and all(wanted.get(name)==digest for name,digest in fetched.items())
git_want={p['source'].rsplit('#',1)[1] for p in lock if p.get('source','').startswith('git+')}
git_got={subprocess.check_output(['git','-C',p,'rev-parse','HEAD'],text=True).strip() for p in (study/'cargo-home/git/checkouts').glob('*/*') if p.is_dir()}
assert len(git_want)==2 and git_got==git_want
(out/'dependencies.json').write_text(json.dumps({'registry':fetched,'git':sorted(git_got)},sort_keys=True)+'\n')
compiler = (sdk/'bin/rustc').resolve()
assert Path(subprocess.check_output(['rustup','which','--toolchain','ohm','rustc'],env=env,text=True).strip()).samefile(compiler)
watched={'ruff_linter','ruff_graph','ruff_workspace','ruff_server','ruff','ty_python_semantic','ruff_benchmark','ruff_formatter','ruff_markdown'}
cmd = ['cargo','+ohm','check','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json']

def phase(name, revision, success=True):
    dest=out/name;dest.mkdir()
    if success:git('diff','--quiet',revision,'--')
    original=dest/'cargo.jsonl'
    seen={}
    with original.open('wb') as fo,(dest/'cargo.stderr').open('wb') as fe:
        trace=dest/'process';trace.mkdir()
        traced=['strace','-ff','-s','8192','-e','trace=execve,execveat','-o',str(trace/'pid'),*cmd]
        process=subprocess.Popen(traced,cwd=work,env=env,stdout=fo,stderr=fe,start_new_session=True)
        while process.poll() is None:
            for p in Path('/proc').iterdir():
                if not p.name.isdecimal() or p.name in seen:continue
                try:
                    if os.getpgid(int(p.name))!=process.pid or not (p/'exe').samefile(compiler):continue
                    args=(p/'cmdline').read_bytes().decode(errors='replace').split('\0')
                    if '--crate-name' in args and any(a=='--emit' or a.startswith('--emit=') for a in args):seen[p.name]=args
                except (OSError,ValueError): pass
            time.sleep(0.008)
    assert process.returncode==(0 if success else 101),(dest/'cargo.stderr').read_text()[-1700:]
    rows=[json.loads(l) for l in original.read_bytes().splitlines()]
    assert rows[-1]=={'reason':'build-finished','success':success}
    units=[r for r in rows if r['reason']=='compiler-artifact']
    errors=[r['message'] for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error']
    if not success:
        assert any(m.get('code') and m['code']['code']=='E0308' and any(s['is_primary'] and s['file_name'].endswith('ruff/helpers.rs') for s in m['spans']) for m in errors)
    files={}
    for row in units:
        target=row['target']
        if target['kind']!=['lib'] or target['name'] not in watched:continue
        meta,=[Path(p) for p in row['filenames'] if p.endswith('.rmeta')]
        files[target['name']]={'sha256':sha(meta),'modified_ns':meta.stat().st_mtime_ns,'bytes':meta.stat().st_size,
                               'public':subprocess.check_output(['rustc','+ohm',meta,'-Zls=public_hash'],env=env,text=True).strip()}
    kernel={}
    for stream in sorted(trace.glob('pid.*')):
        for line in stream.read_text(errors='replace').splitlines():
            launch=re.match(r'^execve\("([^"]+)", \[',line)
            if not launch or not line.endswith(' = 0') or '"--crate-name", "' not in line or '"--emit' not in line:continue
            path=Path(launch[1]);path=path if path.is_absolute() else work/path
            if not path.exists() or not path.samefile(compiler):continue
            crate_name=re.search(r'"--crate-name", "([^"]+)"',line)[1]
            kind=re.search(r'"--crate-type", "([^"]+)"',line)
            assert stream.name not in kernel
            kernel[stream.name]=[crate_name,kind[1] if kind else None]
    # A sampled process can inherit rustc's image across fork before exec'ing its own program.
    # Keep those observations for diagnosis; only a successful exec is counted as a compiler.
    sampled_only={p:argv for p,argv in seen.items() if 'pid.'+p not in kernel}
    (dest/'sampled-only.json').write_text(json.dumps(sampled_only,sort_keys=True)+'\n')
    if name=='old':
        named=Counter(r['target']['name'].replace('-','_') for r in units if not r['fresh'])
        launched=Counter(v[0] for v in kernel.values())
        assert not (named-launched),('missing fresh cold rustc execs',named-launched)
        assert all(re.fullmatch(r'autocfg_[0-9a-f]+_\d+',k) for k in (launched-named)),('extra cold rustc execs',launched-named)
    data={'kernel_rustcs':kernel,'role':arm,'label':name,'revision':revision,'source_git_diff':git('diff','--name-only',old),'factory':json.loads((study/'sdk.json').read_bytes())['factory'],'driver_sha256':sha(driver),
          'command':cmd,'exit':process.returncode,'units':len(units),'dirty':[[r['target']['name'],r['target']['kind']]for r in units if not r['fresh']],
          'observed_rustc':seen,'metadata':files,'errors':[e.get('code')for e in errors]}
    (dest/'result.json').write_text(json.dumps(data,indent=2)+'\n')
    print(arm,name,'Cargo nonfresh',len(data['dirty']),'rustc PIDs observed',len(seen),
          'linter hash',files.get('ruff_linter',{}).get('public'),flush=True)
    return data

initial=phase('old',old)
assert len(initial['kernel_rustcs'])>100 and 'ruff_linter' in [v[0]for v in initial['kernel_rustcs'].values()]
sources=work/next(n for n in changed if n.endswith('.rs'))
try:
    phase('old-unchanged',old)
    git('restore','--source='+new,'--staged','--worktree','--',*changed)
    edit=phase('edit',new);phase('edit-unchanged',new)
    source=sources.read_bytes()
    try:
        sources.write_bytes(source+b'\npub fn ohm_ruf009_negative() -> u8 { false }\n')
        phase('invalid',new,False)
    finally:
        sources.write_bytes(source)
    repair=phase('repair',new)
    assert edit['metadata']['ruff_linter']['public']==repair['metadata']['ruff_linter']['public']
finally:
    git('restore','--source='+old,'--staged','--worktree','--',*changed)
returned=phase('return',old)
assert returned['metadata']['ruff_linter']['public']==initial['metadata']['ruff_linter']['public']
assert not git('status','--porcelain')
