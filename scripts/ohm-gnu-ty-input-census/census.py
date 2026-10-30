"""Locate actual Rust codegen units still affected by opaque assembly after the GNU register fixes."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ohm-aarch64-linux'))
import qualify

A = '55c48b1e76649ce2e24a037a530c6c72144b4f82'
B = 'dab63706679cf1f9bf840bd6d7c9b93b0819caf1'
TREES = {A: '9a1de291b3a562b95b1a8abf2b14208801a1d587', B: '348cbb71b5a7e3a2f7277c2028284abefff06157'}
LOCK = 'bf44c77c90a8628b2ee8a818b30f913765ab0cecf43fdad16439767f72028c92'
TARGET = 'aarch64-unknown-linux-gnu'
CLI = ['cargo','+ohm','test','-p','ty_project','--lib','--no-run','--target',TARGET,'--locked','--offline','-j4','--message-format=json']
HARD = b'/dev/null/ohm-untracked-relink-inputs:'
SOFT = b'/dev/null/ohm-recheck-dependent-links-v2:'
OLD = b'/dev/null/ohm-recheck-dependent-links:'
NEW_TESTS = {'glob::'+m+'::tests::equality_accounts_for_pattern_root' for m in ('exclude','include')}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    with path.open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.write('\n')


def blob(path, data):
    path.parent.mkdir(exist_ok=True, parents=True)
    if path.exists():
        assert gzip.decompress(path.read_bytes()) == data
    else:
        path.write_bytes(gzip.compress(data, compresslevel=2, mtime=0))


def command(args, cwd, env=None):
    return subprocess.check_output(list(map(str,args)), cwd=cwd, env=env).decode().strip()


def flags(args, option):
    for i, value in enumerate(args):
        if value == option:
            yield args[i+1]
        elif option == '-C' and value.startswith('-C') and len(value)>2:
            yield value[2:]
        elif value.startswith(option+'='):
            yield value[len(option)+1:]


def marker(data):
    rules = set(data.splitlines())
    kinds = [name for name, line in [('hard',HARD),('v2',SOFT),('v1',OLD)] if line in rules]
    assert len(kinds) <= 1, kinds
    return kinds[0] if kinds else 'none'


def describe(row, src, roots, output, owners):
    a = row['argv']
    options = list(flags(a,'-C'))
    dest, = flags(a,'--out-dir')
    extra = [v[len('extra-filename='):] for v in options if v.startswith('extra-filename=')]
    assert len(extra)<=1
    dest=Path(dest).resolve()
    assert any(dest.is_relative_to(root) for root in roots)
    crate = row['crate']
    path = dest / (crate+(extra[0] if extra else '')+'.d')
    input_rs = [Path(v) for v in a if v.endswith('.rs') and (src/v).is_file()]
    rooted = [str((src / v).resolve()) for v in input_rs]
    declared_sources = owners.get(crate,set())
    local = any(Path(source).is_relative_to(src / 'crates') for source in rooted)
    if not local and declared_sources and all(Path(source).is_relative_to(src / 'crates') for source in declared_sources):
        local = True
    incremental=[v for v in options if v.startswith('incremental=')]
    assert len(incremental)<=1
    target=list(flags(a,'--target'))
    key = str(path)
    record = {'crate':crate,'local':local,'incremental':bool(incremental),'llvm_lto_off':'lto=off' in options,
              'target':target,'typed_sources':sorted(declared_sources),'ohm_check':any(v=='-Zohm-check-relink-inputs' for v in a),'test':'--test' in a,'link_only':row['link_only'],'input':[str(v) for v in input_rs],
              'pid':row['pid'],'argv_sha256':digest(json.dumps(a,separators=(',',':')).encode()),'path':key}
    if path.is_file():
        data=path.read_bytes()
        record.update(marker=marker(data),dep_sha=digest(data))
        blob(output/'depfiles'/(record['dep_sha']+'.gz'),data)
    else:
        record['marker']='unresolved'
    return key,record


def native_tests(exe, label, revision, root, store, env, previous):
    with exe.open('rb') as f:
        header=f.read(20)
    assert header[:7] == bytes.fromhex('7f454c46020101') and header[18:20]==b'\xb7\x00'
    raw = sha(exe)
    def run(name,args):
        p=subprocess.run(['qemu-aarch64','-L','/usr/aarch64-linux-gnu',str(exe),*args],cwd=root/'crates/ty_project',env=env,capture_output=True,timeout=240)
        blob(store/(name+'-stdout.gz'),p.stdout);blob(store/(name+'-stderr.gz'),p.stderr)
        assert p.returncode==0,(name,p.stderr[-600:])
        return p.stdout.decode()
    listed=run('list',['--list','--format','terse'])
    names={line.removesuffix(': test') for line in listed.splitlines() if line.endswith(': test')}
    suffix={n for n in names if n.endswith('::equality_accounts_for_pattern_root')}
    assert suffix==(NEW_TESTS if revision==B else set()),suffix
    if previous is None:
        control=next(n for n in sorted(names) if n.startswith('glob::') and n not in NEW_TESTS)
    else:
        control=previous['control']
        assert names==set(previous['tests'])|NEW_TESTS
    for n in sorted(suffix|{control}):
        out=run(n.replace(':','_'),['--exact',n,'--test-threads=1'])
        assert f'test {n} ... ok' in out and '1 passed; 0 failed' in out
    return {'sha256':raw,'bytes':exe.stat().st_size,'tests':sorted(names),'control':control,'source':revision,'phase':label}


def census():
    work=Path(os.environ['CENSUS_ROOT']).resolve();sdk=Path(os.environ['CENSUS_SDK']).resolve(strict=True)
    assert not work.exists();work.mkdir()
    out=work/'receipts';out.mkdir();src=work/'ruff'
    table=json.loads((HERE.parent/'ohm-aarch64-portable-review/source/sdk-members.json').read_text())
    v=table['roles']['M']; expected=table['common']|{table['driver_path']:v['driver']}
    assert len(expected)==119
    for n,(h,size,mode) in expected.items():
        f=sdk/n;assert f.stat().st_size==size and f.stat().st_mode&0o777==mode and sha(f)==h,n
    assert v['source']=='8f42a1c11e66c2a55299914d5025e4fa7549ead4'
    proxy=Path(shutil.which('rustup')).resolve(strict=True);shim=work/'proxies';shim.mkdir()
    for tool in ('cargo','rustc','rustup'):(shim/tool).symlink_to(proxy)
    home=work/'home';home.mkdir();rh=work/'rustup';(rh/'toolchains').mkdir(parents=True);(rh/'toolchains/ohm').symlink_to(sdk,target_is_directory=True)
    env={'HOME':str(home),'PATH':str(shim)+':/usr/local/bin:/usr/bin:/bin','RUSTUP_HOME':str(rh),'CARGO_HOME':str(work/'cargo-home'),
         'CARGO_TARGET_DIR':str(work/'target'),'CARGO_BUILD_BUILD_DIR':str(work/'shared'),'RUSTUP_AUTO_INSTALL':'0',
         'CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER':'/usr/bin/aarch64-linux-gnu-gcc',
         'CC_aarch64_unknown_linux_gnu':'/usr/bin/aarch64-linux-gnu-gcc','CXX_aarch64_unknown_linux_gnu':'/usr/bin/aarch64-linux-gnu-g++',
         'AR_aarch64_unknown_linux_gnu':'/usr/bin/aarch64-linux-gnu-ar','CARGO_TERM_COLOR':'never','LC_ALL':'C','TZ':'UTC',
         'CARGO_CACHE_AUTO_CLEAN_FREQUENCY':'never','GIT_CONFIG_GLOBAL':os.devnull,'GIT_CONFIG_NOSYSTEM':'1'}
    command(['git','init','-q',src],work,env)
    command(['git','fetch','--depth=2','--no-tags','https://github.com/astral-sh/ruff',B],src,env)
    command(['git','checkout','-q','--detach',A],src,env)
    assert command(['git','rev-parse',B+'^'],src,env)==A
    assert all(command(['git','rev-parse',rev+'^{tree}'],src,env)==tree for rev,tree in TREES.items())
    assert sha(src/'Cargo.lock')==LOCK
    patch=command(['git','diff','--name-only',A,B],src,env).splitlines()
    assert patch==['crates/ty_project/src/glob/exclude.rs','crates/ty_project/src/glob/include.rs','crates/ty_server/tests/e2e/main.rs','crates/ty_server/tests/e2e/snapshots/e2e__commands__debug_command.snap']
    # The target tests also compile host build scripts and procedural macros.
    command(['cargo','+ohm','fetch','--locked'],src,env)
    env['CARGO_NET_OFFLINE']='true'
    assert Path(command(['rustup','which','--toolchain','ohm','rustc'],src,env)).samefile(sdk/'bin/rustc')
    assert Path(command(['rustup','which','--toolchain','ohm','cargo'],src,env)).samefile(sdk/'bin/cargo')
    save(out/'enrolled.json',{'compiler':v,'cargo_sha':sha(sdk/'bin/cargo'),'rustc':command(['rustc','+ohm','-vV'],src,env),
         'cargo':command(['cargo','+ohm','-Vv'],src,env),'env':env,'trees':TREES,'changed':patch,'lock_sha256':LOCK,'cli':CLI})
    qualify.rt.SDK=sdk
    current={};prior=None;phase_rows={}
    for label,rev in [('cold',A),('edit',B),('repeat',B)]:
        if label=='edit':command(['git','restore','--source',B,'--staged','--worktree','--','.'],src,env)
        assert command(['git','write-tree'],src,env)==TREES[rev] and not command(['git','diff','--name-only'],src,env)
        dest=out/label;dest.mkdir();trace=work/(label+'-raw-execs');trace.mkdir()
        cmd=['strace','-ff','-q','-s','262144','-e','trace=execve,execveat','-o',str(trace/'proc'),*CLI]
        build=subprocess.run(cmd,cwd=src,env=env,capture_output=True,timeout=6600)
        blob(dest/'stdout.gz',build.stdout);blob(dest/'stderr.gz',build.stderr)
        with tarfile.open(dest/'execs.tar.gz','w:gz',compresslevel=1) as archive:
            for f in sorted(trace.iterdir()):archive.add(f,arcname=f.name,recursive=False)
        save(dest/'command.json',{'argv':cmd,'exit':build.returncode,'stdout':digest(build.stdout),'stderr':digest(build.stderr)})
        if build.returncode:
            print(build.stderr.decode(errors='replace')[-3500:],flush=True)
            print(build.stdout.decode(errors='replace')[-2500:],flush=True)
        assert build.returncode==0
        messages=[json.loads(l) for l in build.stdout.splitlines()]
        assert messages[-1]=={'reason':'build-finished','success':True}
        kernel=qualify.native(trace,src)
        assert kernel['cargo'][0]['terminal']==[0]
        save(dest/'kernel.json',kernel);units=[]
        owners={}
        for m in messages:
            if m['reason']=='compiler-artifact':
                target=m['target']
                owners.setdefault(target['name'].replace('-','_'),set()).add(target['src_path'])
        for proc in kernel['rustcs']:
            key,row=describe(proc,src,(work/'target',work/'shared'),out,owners)
            units.append(row)
            if not row['link_only']:
                current[key]=row
        emitted=[x for x in current.values() if x['local'] and x['target']==[TARGET] and x['incremental']]
        unresolved=[x['crate'] for x in emitted if x['marker']=='unresolved']
        hard=[x for x in emitted if x['marker']=='hard' and x['llvm_lto_off'] and x['ohm_check']]
        main,=[m for m in messages if m.get('target',{}).get('name')=='ty_project' and m.get('profile',{}).get('test') and m.get('executable')]
        product=native_tests(Path(main['executable']),label,rev,src,dest,env,prior)
        if prior is None:prior=product
        save(dest/'census.json',{'emitted':units,'current_local_incremental':emitted,'hard_lto_off':hard,'unresolved':unresolved,'product':product,'typed':sum(m['reason']=='compiler-artifact' for m in messages)})
        assert any(r['crate']=='ty_project' and r['test'] for r in emitted),'unwitnessed ordinary local test emitter'
        assert not unresolved,unresolved
        if label=='edit':assert product['sha256']!=prior['sha256']
        if label=='repeat':
            assert product['tests']==phase_rows['edit']['product']['tests']
            save(dest/'repeat-bytes.json',{'same_executable_as_edit':product['sha256']==phase_rows['edit']['product']['sha256']})
        phase_rows[label]={'hard':[x['crate'] for x in hard],'current_local_incremental':len(emitted),'full':sum(not r['link_only'] for r in units),'link_only':sum(r['link_only'] for r in units),'product':{'sha256':product['sha256'],'tests':product['tests']}}
        print(label,{k:v for k,v in phase_rows[label].items() if k!='product'},'tests',len(product['tests']),flush=True)
    save(out/'terminal.json',{'purpose':'untimed discovery after versioned markers','phases':phase_rows,'timed_observations':0})


if __name__=='__main__':
    if sys.argv[1:]==['--self-test']:
        assert marker(b'/tmp/x: /dev/null/ohm-untracked-relink-inputs\n')=='none'
        assert marker(HARD+b'\n')=='hard' and marker(SOFT+b'\n')=='v2'
        assert list(flags(['-C','lto=off','-Cincremental=x'],'-C'))==['lto=off','incremental=x']
        assert set(NEW_TESTS)=={'glob::exclude::tests::equality_accounts_for_pattern_root','glob::include::tests::equality_accounts_for_pattern_root'}
        print('Marker and compiler argument controls passed.')
    else:
        assert sys.argv[1:]==[];census()
