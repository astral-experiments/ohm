"""Separate unscored diagnostics and phase evidence for the frozen primary PMU sample."""
import gzip, json, os, shutil, subprocess, sys, time
from pathlib import Path
import measure as m

SOURCE = 'crates/ty_project/src/lib.rs'
BAD = b'\nconst _: u8 = "OHM_RON_CHECK_BAD_TYPE";\n'
NEXT_BAD = b'\nconst _: i16 = [false; 3]; // OHM_RON_SECOND_BAD_TYPE\n'
GOOD_EDIT = b'\nconst _: i16 = 29; // OHM_RON_VALID_DIFFERENT_BYTES\n'
PRIMARY = '9e3a59e091c467c5139532dfb09cd8765eef343c938c0680e75da3ec2282ce3e'

def details(path):
    s = path.stat()
    return dict(size=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns,
                dev=s.st_dev, ino=s.st_ino, sha=m.sha(path))

def source():
    result = {}
    for path in (SOURCE, m.changed):
        file = m.src / path
        result[path] = details(file)
        result[path]['bad'] = [s.decode().strip() for s in (BAD, NEXT_BAD) if s in file.read_bytes()]
    return result

def cache(env):
    result = {}
    store = m.O / 'diag-content'
    store.mkdir(exist_ok=True)
    # The named fingerprint before/after a failed rustc and its output cache
    # live together. New layouts nest per-unit fingerprints by workspace.
    for root in [Path(env[k]) for k in ('CARGO_TARGET_DIR','CARGO_BUILD_BUILD_DIR')]:
        for owner in root.rglob('*ty_project*'):
            if not owner.is_file() or not owner.name.endswith('ty_project') or owner.name.startswith('dep-'):
                continue
            if owner.parent.name != 'fingerprint' and '.fingerprint' not in owner.parts:continue
            for f in sorted(owner.parent.iterdir()):
                if not f.is_file() or str(f) in result:continue
                info = details(f)
                result[str(f)] = info
                if info['size'] < 3*1024*1024:
                    body = f.read_bytes()
                    assert m.h(body) == info['sha']
                    dst = store/(info['sha']+'.gz')
                    if not dst.exists():m.gz(dst,body)
    return result

def mention(raw):
    return [l.decode(errors='replace') for l in raw.splitlines() if b'E0308' in l or b'mismatched types' in l or b'OHM_RON_' in l]

def execute(role, label, env, release, base_cmd, *, style='json', observer='physical'):
    rel = role + '/' + label
    dest = m.O / rel
    if style == 'human':
        env = {k:v for k,v in env.items() if k != 'CARGO_LOG'}
    before = {'source':source(),'cache':cache(env)}
    command = base_cmd + (['--message-format=json'] if style=='json' else [])
    s = time.monotonic_ns()
    if observer == 'physical':
        result, _, events = m.observe(rel,m.R/('sdk-'+release)/'bin/rustc','ron',command,env,m.src)
    else:
        dest.mkdir(parents=True)
        trace = None
        raw_cmd = command
        if observer == 'cache-reads':
            names = sorted({path for path in before['cache'] if Path(path).name.startswith('output-')})
            # If the role has no cached diagnostics, still run the same fresh process.
            if names:
                trace = dest/'open-and-read.tsv'
                raw_cmd = ['strace','-f','-qq','-ttt','-Y','-yy','-s','16384','-o',str(trace),
                     '-e','trace=openat,openat2,read,pread64,unlink,unlinkat,close',*[v for name in names for v in ('-P',name)],'--',*command]
        result = subprocess.run(raw_cmd,env=env,cwd=m.src,capture_output=True,timeout=1200)
        m.gz(dest/'stdout.gz',result.stdout);m.gz(dest/'stderr.gz',result.stderr)
        if trace:
            m.gz(dest/'open-and-read.tsv.gz',trace.read_bytes())
            trace.unlink()
        events = []
    elapsed = time.monotonic_ns()-s
    after = {'source':source(),'cache':cache(env)}
    assert before['source'] == after['source']
    rustc = m.R/('sdk-'+release)/'bin/rustc'
    cargo = m.R/('sdk-'+release)/'bin/cargo'
    owners = []
    cargos = []
    for pid, identity, _, exe, args in events:
        if identity==[rustc.stat().st_dev,rustc.stat().st_ino] and '--crate-name' in args and '--out-dir' in args:
            owners.append([pid,args[args.index('--crate-name')+1],exe])
        if identity==[cargo.stat().st_dev,cargo.stat().st_ino] and 'check' in args:cargos.append([pid,exe])
    if observer=='physical':assert len(cargos)==1
    row = {'role':role,'label':label,'observer':observer,'style':style,'command':command,'exit':result.returncode,
           'stdout':m.h(result.stdout),'stderr':m.h(result.stderr),'elapsed_for_ownership_only':elapsed,
           'before':before,'after':after,'physical_rustcs':owners,'physical_cargo':cargos}
    if style=='json':
        notifications=[json.loads(line) for line in result.stdout.splitlines()]
        assert notifications[-1]=={'reason':'build-finished','success':result.returncode==0}
        row['messages']=[[o['package_id'],o['target']['kind'],o['target']['src_path'],o['message']['level'],o['message'].get('code'),
                          m.h(json.dumps(o['message'],sort_keys=True).encode())]
                         for o in notifications if o['reason']=='compiler-message']
        row['ty_artifacts']=[[o['fresh'],[[a,details(Path(a))] for a in o['filenames']]] for o in notifications
                if o['reason']=='compiler-artifact' and o['target']['name']=='ty_project']
    else:
        row['human_message_lines']=mention(result.stdout)+mention(result.stderr)
    m.save(dest/'receipt.json',row)
    return row

def reverse_history():
    m.run(['git','-C',m.src,'apply','--reverse','-'],input=gzip.decompress((m.HERE/'historical.patch.gz').read_bytes()))
    assert (m.src/m.changed).read_bytes()==m.w.git(m.src,'show',m.hist+'^:'+m.changed)

def run_role(role, release, base_env, defaults):
    # This exact checked-out Ruff source is used for each run. The writable build
    # trees never move or overlap. The downloaded locked registry is shared read-only.
    slot=m.R/('recover-'+role)
    env=m.w.environment(m.R,release,slot)
    env['CARGO_HOME']=base_env['CARGO_HOME']
    env['CARGO_LOG']='cargo::compiler=info,cargo::compiler::fingerprint=debug'
    m.save(m.O/role/'environment.json',env)
    cmd=m.cmd[:-1]
    if not defaults:cmd=cmd[:2]+['-Zohm-defaults=no']+cmd[2:]
    src_file=m.src/SOURCE
    expected=m.w.git(m.src,'show','HEAD:'+SOURCE)
    m.w.git(m.src,'restore','--source=HEAD','--worktree','--',m.changed)
    assert src_file.read_bytes()==expected
    visits=[]
    def visit(label,**kw):
        row=execute(role,label,env,release,cmd,**kw);visits.append([label,row['exit']])
        return row
    visit('train-original',observer='plain')
    reverse_history()
    visit('edit');visit('repeat')
    try:
        src_file.write_bytes(expected+BAD)
        visit('invalid')
        src_file.write_bytes(expected)
        visit('repair-json')
        visit('idle-human',style='human')
        visit('idle-json')
        visit('cache-reads',observer='cache-reads')
        src_file.write_bytes(expected+BAD)
        visit('bad-again')
        src_file.write_bytes(expected+NEXT_BAD)
        visit('different-bad')
        visit('unchanged-different-bad')
        src_file.write_bytes(expected+GOOD_EDIT)
        visit('different-repair')
        src_file.write_bytes(expected)
        visit('final-repair')
    finally:src_file.write_bytes(expected)
    # Same Ruff source and toolchain, entirely empty independent targets.
    fresh=m.R/('empty-'+role)
    clean=m.w.environment(m.R,release,fresh)
    clean.update(CARGO_HOME=base_env['CARGO_HOME'],CARGO_LOG=env['CARGO_LOG'])
    for label,style in [('empty-json','json'),('empty-human','human')]:
        row=execute(role,label,clean,release,cmd,style=style,observer='plain')
        assert row['exit']==0
    m.save(m.O/role/'visits.json',visits)
    return visits

def main():
    assert m.sha(m.HERE/'primary.zip')==PRIMARY
    import zipfile
    with zipfile.ZipFile(m.HERE/'primary.zip') as z:
        prev=json.loads(z.read('structural.json'))
        assert prev['share']>=.5 and 'terminal.json' not in z.namelist()
    secret=os.environ['QUALIFICATION_TOKEN']
    env=m.acquire()
    m.run(['cc','-O2','-Wall','-Werror',m.HERE/'observe.c','-o',m.R/'observer'])
    try:
        os.environ['GH_TOKEN']=secret
        m.packages.prepare(m.R,'20')
    finally:del os.environ['GH_TOKEN'];del secret
    e20=m.w.environment(m.R,'20',m.R/'inspect-20');m.w.tools(m.R,'20',e20)
    m.save(m.O/'cohort.json',{'previous':{'run':41139480769,'job':124349977576,'artifact':13017707410,'sha':PRIMARY},
         'kit20':m.read(m.R/'receipts/20/custody.json'),'tools20':m.read(m.R/'receipts/20/tools.json'),
         'normal_run':False,'preregistered_fraction':prev['share']})
    failures={}
    import traceback
    for role,release,defaults in [('signed21','21',True),('off21','21',False),('signed20','20',True)]:
        try:run_role(role,release,env,defaults)
        except Exception:
            failures[role]=traceback.format_exc()
            m.save(m.O/(role+'/exception.json'),{'exception':failures[role]})
    try:
        assert (m.src/m.changed).read_bytes()==m.w.git(m.src,'show',m.hist+'^:'+m.changed)
        assert (m.src/SOURCE).read_bytes()==m.w.git(m.src,'show','HEAD:'+SOURCE)
        m.profile(env)
    except Exception:failures['profile']=traceback.format_exc()
    m.save(m.O/'followthrough-terminal.json',{'failures':failures,'preserve_original_red_gate':True})
    if failures:raise RuntimeError(failures)

if __name__=='__main__':main()
