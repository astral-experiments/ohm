"""Count the ordinary Cargo process and every rustc separately from native link helpers."""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'ohm-aarch64-registers')]
import paired
from paired import census, cli, rt
import tree_ir
from raw_counter import recount


def profile_role(role):
    donor = Path(os.environ['CENSUS_PARENT'])
    candidate = Path(os.environ['CENSUS_SDK'])
    stable = rt.ROOT / 'guest-sdk'
    shutil.copytree(donor if role == 'P' else candidate, stable, copy_function=os.link, symlinks=True)
    os.environ['CENSUS_SDK'] = str(stable)
    if role == 'P':
        os.environ.pop('CENSUS_CANDIDATE_RECORD')
    work, out, src, env = census.acquire(cli.OLD, cli.NEW, cli.TREES, cli.LOCK, cli.FILES, cli.CLI)
    tree_ir.rt.SDK = work / 'rustup/toolchains/ohm'
    identity = json.loads((out/'enrolled.json').read_text())
    assert identity['compiler']['source'] == (paired.PARENT if role == 'P' else paired.CHILD)
    tree_ir.calibrate()
    def normal(stage, old=False):
        stdout = paired.run_logged(cli.CLI, src, env, out/stage)
        row, exe = paired.product(stdout, src, env, old, out/stage)
        assert row['unit_count'] == 372
        return row, exe, cli.cli_product(exe, old, out/stage, src, env)
    old, _, old_program = normal('cold', True)
    census.command(['git','restore','--source',cli.NEW,'--staged','--worktree','--','.'], src, env)
    assert census.command(['git','write-tree'],src,env) == cli.TREES[cli.NEW] and census.sha(src/'Cargo.lock') == cli.LOCK
    edit, _, new_program = normal('edit')
    first, exe, repeated = normal('first-repeat')
    assert first['roster'] == edit['roster'] == old['roster'] and new_program == repeated and old_program != repeated
    # Register the unwrapped normal process argv from the kernel before using Valgrind.
    trace = work/'register'
    trace.mkdir()
    registered = paired.run_logged(['strace','-ff','-q','-v','-s','262144','-e','trace=execve,execveat','-o',str(trace/'proc'),*cli.CLI], src, env, out/'register')
    row, expected_exe = paired.product(registered, src, env, False, out/'register')
    assert row['roster'] == first['roster'] and row['unit_count'] == 372
    assert expected_exe == exe and census.sha(exe) == repeated['sha256']
    originals = tree_ir.rows(trace)
    physical = []
    expected = {}
    helpers = []
    proxy = Path(shutil.which('cargo',path=env['PATH']))
    command = activated = None
    proxy_pids = []
    root_pid = None
    for pid, path, argv, inherited in originals:
        assert path.is_file() and argv and not {'GH_TOKEN','GITHUB_TOKEN','LD_PRELOAD','RUSTC_WRAPPER'} & inherited.keys()
        physical.append({'pid':pid,'path':str(path),'argv':argv,'image':census.sha(path)})
        if path.samefile(proxy):
            assert argv[1:] == cli.CLI[1:]
            proxy_pids.append(pid)
        elif path.samefile(stable/'bin/cargo'):
            assert command is None and argv[1:] == cli.CLI[2:]
            command, activated, root_pid = argv, inherited, pid
            expected['cargo'] = argv
        elif path.samefile(stable/'bin/rustc'):
            assert '--crate-name' in argv and any(x.startswith('--emit') for x in argv)
            assert re.search(r'--jobserver-(?:auth|fds)=\d+,\d+', inherited['CARGO_MAKEFLAGS'])
            key = hashlib.sha256(json.dumps(argv).encode()).hexdigest()
            assert key not in expected
            expected[key] = argv
        else:
            helpers.append(Path(argv[0]).name)
    assert len(expected) >= 2 and proxy_pids == [root_pid] and activated['RUSTUP_TOOLCHAIN'] == 'ohm'
    # A same-PID exec can overwrite the earlier Valgrind profile. The sole such
    # transition in the original must be rustup selecting the physical Cargo.
    occurrence = collections.Counter(pid for pid,*_ in originals)
    assert {pid:n for pid,n in occurrence.items() if n>1} == {root_pid:2}
    assert len({' '.join(a) for a in expected.values()}) == len(expected)
    with tarfile.open(out/'original-execs.tar.gz','w:gz',compresslevel=1) as tar:
        for file in sorted(trace.iterdir()):
            tar.add(file,arcname=file.name,recursive=False)
    census.save(out/'registered-native.json',{'physical':physical,'expected':expected,'native_helpers':helpers})
    profiles = work/'guest-profiles'
    profiles.mkdir()
    argv = [tree_ir.VG,'--tool=callgrind','--trace-children=yes','--separate-threads=no','--cache-sim=no','--branch-sim=no','--collect-jumps=no',
            '--callgrind-out-file='+str(profiles/'cg.%p'),'--log-file='+str(profiles/'log.%p'),*command]
    instrumented, seen = tree_ir.counted_command(argv, out/'guest', src, activated, expected, timeout=5300)
    observed, returned = paired.product(instrumented.stdout,src,env,False,out/'guest')
    assert observed == row and returned == exe and cli.cli_product(exe,False,out/'guest',src,env) == repeated
    by_command = {' '.join(a):key for key,a in expected.items()}
    counted = {}
    diagnostic = []
    for path in sorted(profiles.glob('cg.*')):
        pid = int(path.suffix[1:])
        label = tree_ir.event_command(path)
        raw = path.read_bytes()
        log = (profiles/f'log.{pid}').read_bytes()
        census.blob(out/'raw'/(path.name+'.gz'),raw)
        census.blob(out/'raw'/(f'log.{pid}.gz'),log)
        key = by_command.get(label)
        if key is None:
            # Raw totals for external helpers have no operand binding here and do
            # not enter the reported Cargo/rustc instruction count.
            assert ' --crate-name ' not in label and Path(label.split()[0]).name not in ('cargo','rustc')
            diagnostic.append({'pid':pid,'label':label,'Ir':recount(raw,log,pid,[label])})
            continue
        assert key not in counted and (key=='cargo' or seen[key]['pid']==pid)
        counted[key] = {'pid':pid,'Ir':recount(raw,log,pid,expected[key])}
    assert set(counted) == set(expected) and set(seen) == set(expected)-{'cargo'}
    assert {int(p.suffix[1:]) for p in profiles.glob('log.*') if p.stat().st_size} == {v['pid'] for v in [*diagnostic,*counted.values()]}
    census.save(out/'instrumented.json',{'only_registered_Cargo_and_rustc_Ir':sum(v['Ir'] for v in counted.values()),
        'counts':counted,'helpers_unscored':diagnostic,'normal_helper_names':helpers,'product':repeated,'unit_roster':observed})
    for name in ('target','shared'):
        target=work/name
        assert target.parent==work and target.is_dir() and not target.is_symlink()
        shutil.rmtree(target)
    clean, _, reference = normal('independent-empty')
    assert clean['roster']==row['roster'] and reference==repeated
    census.save(out/'terminal-guest.json',{'role':role,'phase':'settled unchanged','scored':'registered physical Cargo plus all actual rustcs',
        'native_helpers_scored':False,'independent_clean':reference,'measured':census.sha(out/'instrumented.json')})
    print(role,len(counted)-1,'rustcs,',len(diagnostic),'other helper profiles; separately empty Ruff matches',flush=True)


if __name__=='__main__':
    mode,=sys.argv[1:]
    assert mode in ('guest-P','guest-C')
    profile_role(mode[-1])
