"""Normal #28444 check inventory, source-linked diagnostic messages and actual CLI behavior."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker as w

PACKAGES = ('ruff_linter', 'ruff_graph', 'ruff_workspace', 'ruff_markdown')
CHECK = ['cargo', '+ohm', 'check', '-p', 'ruff_markdown', '--lib', '--locked','--offline', '--message-format=json']
BUILD = ['cargo', '+ohm', 'build', '-p', 'ruff', '--bin', 'ruff', '--locked','--offline', '--message-format=json']


def parts(out):
    return [json.loads(line) for line in (out/'stdout').read_bytes().splitlines()]


def prefetch():
    w.checked_head(); w.source(w.NEW); w.resources()
    env = w.environment(); del env['CARGO_NET_OFFLINE']
    for name, cmd, target, kind, mode in [('scope', CHECK, 'ruff_markdown', 'lib', 'check'), ('executable', BUILD, 'ruff', 'bin','build')]:
        args = [x for x in cmd if x != '--offline'] + ['-Zunstable-options', '--unit-graph']
        output = subprocess.check_output(args, cwd=w.SRC, env=env, timeout=900)
        data = json.loads(output)
        root, = [data['units'][i] for i in data['roots']]
        w.need(root['target']['name'] == target and root['target']['kind'] == [kind] and root['mode'] == mode, 'different target graph')
        w.save(w.OUT/(name+'-unit-graph.json'), data)
    # Reuse the signed, lockfile-bound archive and executable verification. The two genuine
    # preceding unit graphs fetch only extra inputs used by the normal downstream commands.
    w.prefetch()


def metadata(out, records):
    result = {}
    for pkg in PACKAGES:
        unit, = [r for r in records if r['reason'] == 'compiler-artifact' and r['target']['name'] == pkg and r['target']['kind'] == ['lib']]
        path, = [Path(f) for f in unit['filenames'] if f.endswith('.rmeta')]
        sha = w.sha(path); directory = w.OUT/'members'; directory.mkdir(exist_ok=True)
        dest = directory/(sha+'.rmeta.zst')
        if not dest.exists():
            with dest.open('xb') as f: subprocess.run(['zstd','-q','-3','-c',path], stdout=f,check=True)
        result[pkg] = dict(package=unit['package_id'], filename=path.name, bytes=path.stat().st_size, sha256=sha, zstd_sha256=w.sha(dest), fresh=unit['fresh'])
    w.save(out/'scope-rmetas.json', result)
    return result


def check(name, rev, env, trace=False):
    w.source(rev); out = w.OUT/name
    cmd = CHECK
    if trace:
        executable = shutil.which('strace'); w.need(executable is not None,'strace absent')
        w.save(w.OUT/'scope-tracer.json', dict(path=executable, sha256=w.sha(Path(executable)),version=subprocess.check_output([executable,'--version'],text=True)))
        cmd = [executable,'-f','-qq','-z','-s','131072','-e','trace=execve','-o',str(w.OUT/'scope-execs.private'),*CHECK]
    w.run(cmd,env,out)
    roster, root, search = w.cargo_result(out)
    native = w.native(out,rev,root,search,env)
    selected=metadata(out,parts(out))
    if trace:
        import re
        raw = w.OUT/'scope-execs.private'; data=raw.read_bytes(); raw.unlink()
        owners=[]
        compiler_execs=[]
        for line in data.splitlines():
            if b'execve(' in line and b'"--crate-name"' in line:
                m=re.search(rb'"--crate-name", "([a-zA-Z0-9_]+)"',line)
                w.need(m is not None and b' = 0' in line and b'--emit=dep-info,metadata' in line, 'unexpected traced compiler exec')
                owners.append(m[1].decode())
                compiler_execs.append(line.decode())
        expected=sorted({r[1] for r in roster if not r[-1]})
        w.need(sorted(owners)==expected, ('traced native owners versus Cargo',owners,expected))
        w.save(out/'native-execs.json', dict(sha256=__import__('hashlib').sha256(data).hexdigest(),size=len(data),compiler_owners=sorted(owners),cargo_nonfresh=expected,execs=compiler_execs))
    return dict(roster=roster,selected=selected,oracle=native)


def cli(name, revision, env):
    w.checkout(revision); out=w.OUT/name; w.run(BUILD,env,out,timeout=2000)
    records=parts(out); w.need([r['success']for r in records if r['reason']=='build-finished']==[True], 'binary Cargo verdict')
    binary,=[Path(r['executable'])for r in records if r['reason']=='compiler-artifact' and r['target']['name']=='ruff' and r['target']['kind']==['bin']]
    argv=[str(binary),'check','--isolated','--no-cache','--select','D203,D211,D212,D213','--stdin-filename','probe.py','-']
    p=subprocess.run(argv, env=env, cwd=w.ROOT, input=b'',capture_output=True,timeout=45)
    lines=p.stderr.decode().splitlines(); warnings=['warning: '+s for s in w.NATIVE[revision]]
    w.need(p.returncode==0 and lines==warnings, ('actual Ruff conflict diagnostics',p.returncode,lines))
    elf=binary.open('rb'); magic=elf.read(4);elf.close();w.need(magic==b'\x7fELF','invalid native Ruff')
    result=dict(argv=argv,binary=w.sha(binary),bytes=binary.stat().st_size,exit=p.returncode,stdout=p.stdout.decode(),stderr=lines)
    w.save(out/'scope-cli.json',result); return result


def study():
    w.checked_head(); w.checkout(w.OLD); w.fresh_state(); env=w.environment()
    old=check('scope-old',w.OLD,env)
    old_idle=check('scope-old-unchanged',w.OLD,env)
    w.need(all(row[-1] for row in old_idle['roster']),'unexpected Old repeated work')
    parts0, mtimes=w.make_snapshot(); w.checkout(w.NEW)
    edited=check('scope-edit',w.NEW,env)
    idle=check('scope-new-unchanged',w.NEW,env)
    w.need(all(row[-1]for row in idle['roster']),'unexpected New repeated work')
    w.restore_snapshot(parts0,mtimes); w.checkout(w.NEW)
    traced=check('scope-traced-edit',w.NEW,env,True)
    w.need(edited==traced,'tracer changed the roster, native oracle or one of the four actual rmetas')
    file=w.SRC/w.SOURCE; original=file.read_bytes(); file.write_bytes(original+b'\nconst OHM_INVALID_CHECK_SENTINEL: u64 = "incorrect";\n')
    try:
        out=w.OUT/'scope-invalid'; w.run(CHECK,env,out,101); w.cargo_result(out,False)
    finally:
        file.write_bytes(original)
    repaired=check('scope-repaired',w.NEW,env)
    w.need(repaired['oracle']==edited['oracle'] and all(repaired['selected'][k]['sha256']==edited['selected'][k]['sha256'] for k in PACKAGES),'repaired metadata or native drift')
    w.fresh_state(); clean=check('scope-empty-new',w.NEW,env)
    stable=('native_object','executable','messages')
    w.need(all(clean['oracle'][k]==edited['oracle'][k]for k in stable),'full clean oracle')
    w.need(old['oracle']['messages']!=clean['oracle']['messages'],'missing real source change')
    outputs=dict(old=old['selected'],edit=edited['selected'],empty_new=clean['selected'],new_dirty=[r[1]for r in edited['roster'] if not r[-1]])
    w.save(w.OUT/'scope-check-admitted.json',outputs)
    # Isolate bin-profile state from the complete primary check history.
    w.fresh_state(); before=cli('scope-cli-old',w.OLD,env); after=cli('scope-cli-new',w.NEW,env)
    w.fresh_state(); empty=cli('scope-cli-empty-new',w.NEW,env)
    w.need(before['binary']!=after['binary'] and before['stderr']!=after['stderr'] and after['stderr']==empty['stderr'] and after['stdout']==empty['stdout'],'clean native behavior')
    w.save(w.OUT/'scope-admitted.json',dict(check=outputs,cli=dict(old=before,new=after,empty=empty),work='unscored original Cargo inventory and actual workspace diagnostics'))


if __name__=='__main__':
    {'prefetch':prefetch,'study':study}[sys.argv[1]]()
