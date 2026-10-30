"""Inspect two normal Ruff commands, with one separately identified diagnostic profile."""
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(SCRIPTS / 'ohm-gnu-ty-input-census'), str(SCRIPTS / 'ohm-aarch64-registers')]
import census
import tree_ir

OLD = '107e38d04573ff546a1caa8bff0c04875efb6afb'
NEW = '49bf50b1c782a4e443ae3edce2fdb6d81c2df562'
TREES = {OLD: '203551e4e338c005e8495d7267ac78fb8278317d',
         NEW: 'cf34a6e6988e47cea33e0d708ce66d3097788101'}
LOCK = 'e37036fd781578faeafa15fc0a09b938dd78bd160c8e3be958dfb74eb975f61c'
FILE = 'crates/ruff_db/src/parsed.rs'
ADDED = {'indexed_nodes_relative_tail_bounds', 'indexed_nodes_wide_tail_bounds', 'indexed_nodes_chunk_boundary'}
CONTROL = 'indexed_nodes_round_trip'
INVALID = 'OHM_ATOMIC_DB_MISSING_SYMBOL'


def check_tests(exe, env, src, out, old=False, wrong=False):
    def execute(argv, label, rc):
        p = subprocess.run(['qemu-aarch64', '-L', '/usr/aarch64-linux-gnu', str(exe), *argv],
                           cwd=src/'crates/ruff_db', env=env, capture_output=True, timeout=300)
        census.blob(out/(label+'.stdout.gz'), p.stdout)
        census.blob(out/(label+'.stderr.gz'), p.stderr)
        assert p.returncode == rc, (argv, p.returncode, p.stdout[-500:], p.stderr[-500:])
        return p.stdout.decode()

    text = execute(['--list', '--format', 'terse'], 'list', 0)
    names = sorted(line.removesuffix(': test') for line in text.splitlines() if line.endswith(': test'))
    selected = {n.rsplit('::', 1)[-1]: n for n in names if n.rsplit('::', 1)[-1] in ADDED | {CONTROL}}
    assert set(selected) == ({CONTROL} if old else ADDED | {CONTROL}), selected
    for short, name in selected.items():
        rc = 101 if wrong and short != CONTROL else 0
        output = execute(['--exact', name, '--test-threads=1'], short, rc)
        assert ('0 passed; 1 failed' if rc else '1 passed; 0 failed') in output
    return names


def witness(messages, mode, dest, src, env, old=False, wrong=False):
    rows = [m for m in messages if m['reason'] == 'compiler-artifact']
    matches = [m for m in rows if m['target']['name'] == 'ruff_db' and
               m['target']['kind'] == ['lib'] and m['profile']['test'] == (mode == 'test')]
    root, = matches
    if mode == 'test':
        f = Path(root['executable'])
        with f.open('rb') as inp:
            header = inp.read(20)
        assert header[:7] == bytes.fromhex('7f454c46020101') and header[18:20] == bytes.fromhex('b700')
        extra = {'test_names': check_tests(f, env, src, dest, old=old, wrong=wrong)}
    else:
        f, = map(Path, (s for s in root['filenames'] if s.endswith('.rlib')))
        ar = census.qualify.archive(f.read_bytes())
        census.save(dest/'archive-members.json', ar)
        extra = {'members': len(ar['objects']), 'metadata': ar['metadata']}
    roster = sorted(json.dumps([r[k] for k in ('package_id', 'target', 'features', 'profile')],
                               sort_keys=True) for r in rows)
    return f, {'sha256': census.sha(f), 'size': f.stat().st_size, 'units': len(roster),
               'roster': census.digest('\n'.join(roster).encode()), **extra}


def count_settled(work, out, src, env, cmd, preceding):
    # The physical Cargo that rustup selected inherits its own toolchain environment.
    # Register its exact argv, every rustc, and all other child images on a further visit.
    trace = work/'profile-execs'
    trace.mkdir()
    p = subprocess.run(['strace', '-ff', '-q', '-v', '-s', '262144', '-e', 'trace=execve,execveat',
                        '-o', str(trace/'proc'), *cmd], cwd=src, env=env, capture_output=True, timeout=1800)
    assert p.returncode == 0 and json.loads(p.stdout.splitlines()[-1]) == {'reason':'build-finished','success':True}
    census.blob(out/'profile-registration-stdout.gz', p.stdout)
    census.blob(out/'profile-registration-stderr.gz', p.stderr)
    with tarfile.open(out/'profile-registration-execs.tar.gz','w:gz',compresslevel=1) as t:
        for f in sorted(trace.iterdir()): t.add(f,arcname=f.name)
    sdk = Path(os.environ['CENSUS_SDK'])
    registered = tree_ir.rows(trace)
    principal, = [(argv, inherited) for _,path,argv,inherited in registered
                  if path.is_file() and path.samefile(sdk/'bin/cargo')]
    cargo, activated = principal
    assert cargo[1:] == cmd[2:] and activated['RUSTUP_TOOLCHAIN'] == 'ohm'
    assert not set(activated) & {'GH_TOKEN','GITHUB_TOKEN','RUSTFLAGS','RUSTC_WRAPPER','LD_PRELOAD'}
    physical = []
    for _, path, argv, _ in registered:
        is_rustc = path.is_file() and path.samefile(sdk/'bin/rustc')
        crate = argv[argv.index('--crate-name')+1] if is_rustc and '--crate-name' in argv else None
        physical.append({'name':path.name,'argv':argv,'crate':crate, 'link_only':any(x.startswith('-Zlink-only') for x in argv)})
    census.save(out/'profile-registration.json', physical)
    expected = { ' '.join(r['argv']):r for r in physical if r['crate'] or r['argv'] == cargo }
    need_full = collections.Counter(r['crate'] for r in physical if r['crate'])
    census.save(out/'profile-shape.json',{'preceding':preceding,'registered':dict(need_full)})
    loc = work/'callgrind'
    loc.mkdir()
    logged = subprocess.run([tree_ir.VG,'--tool=callgrind','--trace-children=yes','--separate-threads=no',
                             '--cache-sim=no','--branch-sim=no','--collect-jumps=no',
                             '--callgrind-out-file='+str(loc/'cg.%p'),'--log-file='+str(loc/'log.%p'),*cargo],
                            cwd=src,env=activated,capture_output=True,timeout=3700)
    census.blob(out/'profile-stdout.gz', logged.stdout)
    census.blob(out/'profile-stderr.gz', logged.stderr)
    assert logged.returncode == 0 and json.loads(logged.stdout.splitlines()[-1]) == {'reason':'build-finished','success':True}
    profiles, seen = [], set()
    for f in sorted(loc.glob('cg.*')):
        pid = int(f.suffix[1:])
        label = tree_ir.event_command(f)
        rec = expected.get(label)
        if rec:
            assert label not in seen
            seen.add(label)
        else:
            assert ' --crate-name ' not in label and Path(label.split()[0]).name not in ('rustc','cargo'), label
        ir = census.qualify.instructions(f,pid)
        log = loc/('log.'+str(pid))
        emitted = re.findall(rb'Collected\s+:\s+([\d,]+)',log.read_bytes())
        assert len(emitted) == 1 and int(emitted[0].replace(b',',b'')) == ir
        profiles.append({'pid':pid,'class':(rec['crate'] or 'cargo') if rec else Path(label.split()[0]).name,
                         'link_only':rec['link_only'] if rec else None,'ir':ir,'physical_argv':label})
        census.blob(out/'profiles'/(f.name+'.gz'), f.read_bytes())
        census.blob(out/'profiles'/(log.name+'.gz'), log.read_bytes())
    assert seen == set(expected)
    census.save(out/'diagnostic-ir.json',{'single_unpaired_observation':True,'profiles':profiles})
    print('Single profile',[(v['class'],v['ir']) for v in profiles],flush=True)
    return [json.loads(x) for x in logged.stdout.splitlines()]


def main(mode):
    assert mode in ('build','test')
    cmd = ['cargo','+ohm',mode,'-p','ruff_db','--lib',*(['--no-run'] if mode=='test' else []),
           '--target',census.TARGET,'--locked','--offline','-j4','--message-format=json']
    work,out,src,env = census.acquire(OLD,NEW,TREES,LOCK,[FILE],cmd)
    products = work/'products'
    products.mkdir()
    states = {}
    owners = {}
    def visit(label, old=False, invalid=False, wrong=False):
        dest,msg,k = census.trace_build(label,work,out,src,env,cmd,101 if invalid else 0)
        for m in msg:
            if m['reason'] == 'compiler-artifact':
                owners.setdefault(m['target']['name'],set()).add(m['target']['src_path'])
        emitted = [census.describe(row,src,(work/'target', work/'shared'),out,owners)[1]
                   for row in k['rustcs']]
        census.save(dest/'emitted.json',emitted)
        if invalid:
            assert any((m.get('message',{}).get('code') or {}).get('code')=='E0425' and INVALID in m['message']['rendered'] for m in msg)
            return None
        f, result = witness(msg,mode,dest,src,env,old,wrong)
        assert all(row['terminal']==[0] for row in k['rustcs'])
        result['full']=[(x['crate'],x['marker']) for x in emitted if not x['link_only']]
        result['link_only']=[x['crate'] for x in emitted if x['link_only']]
        result['links']=[Path(x['path']).name for x in k['link_tools'] if Path(x['path']).name in ('ld','ld.bfd','ld.lld','wild','rust-lld')]
        states[label] = result
        census.save(dest/'result.json',result)
        if label in ('edit','clean','repair','first-repeat','second-repeat'):
            shutil.copyfile(f,products/label)
        print(label,'full',result['full'] if label not in ('cold','clean') else len(result['full']),
              'link-only',result['link_only'],'links',result['links'],'units',result['units'],flush=True)
        return f

    visit('cold',old=True)
    census.command(['git','restore','--source',NEW,'--staged','--worktree','--','.'],src,env)
    assert census.command(['git','write-tree'],src,env)==TREES[NEW]
    visit('edit')
    assert states['edit']['sha256'] != states['cold']['sha256']
    visit('first-repeat')
    visit('second-repeat')
    raw = count_settled(work,out,src,env,cmd,[p[0] for p in states['second-repeat']['full']]+states['second-repeat']['link_only'])
    prof = out/'profile-product'
    prof.mkdir()
    _, rp = witness(raw,mode,prof,src,env)
    (src/FILE).write_text((src/FILE).read_text()+'\nconst _: usize = '+INVALID+';\n')
    visit('invalid',invalid=True)
    census.command(['git','restore','--worktree','--',FILE],src,env)
    visit('repair')
    assert not census.command(['git','diff','--name-only'],src,env)
    for name in ('target','shared'):
        directory = work/name
        assert directory.parent == work and directory.is_dir() and not directory.is_symlink()
        directory.rename(work/('retained-'+name))
    visit('clean')
    changed = [name for name in ('edit','first-repeat','second-repeat','repair') if states[name]['sha256'] != states['clean']['sha256']]
    if changed:
        preserved = out/'clean-comparison'
        preserved.mkdir()
        for name in [*changed,'clean']:
            subprocess.run(['zstd','-q','-1','-T2',str(products/name),'-o',str(preserved/(name+'.zst'))],check=True)
    assert len({r['roster'] for r in states.values()}) == 1
    assert rp['roster'] == states['clean']['roster']
    if mode == 'test':
        assert set(states['edit']['test_names'])-set(states['cold']['test_names']) == {
            n for n in states['edit']['test_names'] if n.rsplit('::',1)[-1] in ADDED}
        assert set(states['cold']['test_names']) <= set(states['edit']['test_names'])
        assert all(states[n]['test_names']==states['edit']['test_names'] for n in ('first-repeat','second-repeat','repair','clean'))
        source = (src/FILE).read_text()
        pattern = r"\n            // A partial chunk's trailing bits.*?\n            \);\n"
        old_body,count = re.subn(pattern,'\n',source,flags=re.S)
        assert count == 1 and old_body.count('#[should_panic') == source.count('#[should_panic')
        (src/FILE).write_text(old_body)
        visit('pre-fix-method-with-new-tests',wrong=True)
    census.save(out/'terminal-screen.json',{'mode':mode,'single_baseline':True,'cmd':cmd,'states':states,
                'mismatches_against_clean':changed,'profile_matches_clean':rp['sha256']==states['clean']['sha256']})
    print('Rust method, malformed edit and clean controls passed. Warm/clean differences:',changed,flush=True)

if __name__ == '__main__':
    main(sys.argv[1])
