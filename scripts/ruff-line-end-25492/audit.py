"""Bounded observers for native products, physical execs and the instruction sampler."""
import ast
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile


def save(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(argv, env, cwd, *, exact=0, data=None, timeout=1800):
    p = subprocess.run([str(a) for a in argv], env=env, cwd=cwd, input=data,
                       capture_output=True, timeout=timeout)
    if exact is not None and p.returncode != exact:
        raise RuntimeError((list(map(str, argv[:4])), p.returncode, p.stderr[-3000:].decode(errors='replace')))
    return p


def checked_exec(line):
    if not line.endswith(' = 0'):
        return None
    m = re.match(r'^(?:execve\(|execveat\([^,]+, )"([^"\\]+)", (\[)', line)
    if not m:
        return None
    start, quoted, escaped = m.start(2), False, False
    for i in range(start + 1, len(line)):
        ch = line[i]
        if escaped:
            escaped = False
        elif quoted and ch == '\\':
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif ch == ']' and not quoted:
            return m[1], ast.literal_eval(line[start:i+1])
    raise ValueError('truncated native argv')


def exec_roster(trace, dst, sdk, host):
    rustc = sdk / 'bin/rustc'
    wild = sdk / 'lib/rustlib' / host / 'bin/wild-ld/ld.bfd'
    compilers, links = [], []
    with tarfile.open(dst/'exec.tar.gz', 'w:gz', compresslevel=2) as store:
        for p in sorted(trace.glob('exec.*')):
            if p.stat().st_size == 0:
                continue
            store.add(p, arcname=p.name)
            pid = int(p.suffix[1:])
            for line in p.read_text(errors='replace').splitlines():
                event = checked_exec(line)
                if event is None:
                    continue
                name, args = event
                path = Path(name)
                if path.name == 'rustc' and path.exists() and path.samefile(rustc) and '--crate-name' in args:
                    compilers.append({'pid':pid,'crate':args[args.index('--crate-name')+1],
                                      'link_only':any(a in ('-Zlink-only','link-only') or a.startswith(('-Zlink-only=','link-only=')) for a in args),
                                      'args':args})
                elif path.name in ('ld.bfd','wild','ld') and path.exists() and path.samefile(wild):
                    assert args.count('-o') == 1
                    links.append({'pid':pid,'out':args[args.index('-o')+1]})
    assert len({r['pid'] for r in compilers}) == len(compilers)
    save(dst/'processes.json', {'compilers':compilers,'wild':links})
    return compilers, links


def incremental(roots, owners, previous=None, retain=None):
    candidates = {owner:[] for owner in owners}
    for path in roots.rglob('dep-graph.bin'):
        session = path.parent
        if session.name.startswith('s-') and not session.name.endswith('-working'):
            for owner in owners:
                if session.parent.name.startswith(owner+'-'):
                    candidates[owner].append(session)
    results = {}
    for owner, matches in candidates.items():
        prior = (previous or {}).get(owner,{})
        old_session = prior.get('session')
        if len(matches)>1 and old_session:
            matches = [p for p in matches if str(p)!=old_session]
        if len(matches)!=1:
            results[owner]={'sessions':list(map(str,matches)),'objects':{},'unqualified':True}
            continue
        session, = matches
        objects = {}
        old = prior.get('objects',{})
        for p in sorted(session.glob('*.o')):
            st = p.stat()
            row = {'dev':st.st_dev,'ino':st.st_ino,'bytes':st.st_size,'sha256':sha(p)}
            if retain is not None:
                fd = retain.enter_context(p.open('rb'))
                assert os.fstat(fd.fileno()).st_ino==st.st_ino
            if p.name in old:
                row['same_old_inode'] = (row['dev'],row['ino']) == (old[p.name]['dev'],old[p.name]['ino'])
                row['same_old_bytes'] = row['sha256']==old[p.name]['sha256']
                row['physically_reused'] = row['same_old_inode'] and row['same_old_bytes']
            objects[p.name]=row
        results[owner]={'session':str(session),'objects':objects}
    return results


def probe_sampler(env, root, loop):
    binaries = sorted(Path('/usr/lib').glob('linux-tools*/perf')) + sorted(Path('/usr/lib/linux-tools').glob('*/perf'))
    for perf in reversed(binaries):
        path = root/('sampler-probe-'+str(abs(hash(str(perf))))+'.data')
        cmd=[perf,'record','-q','-e','instructions:u','-c','1000003','-P','-o',path,'--',loop,'0','10000000','1']
        if run(cmd,env,root,exact=None).returncode!=0:
            continue
        rows=run([perf,'script','-i',path,'-F','pid,period'],env,root,exact=None)
        pairs=[list(map(int,line.split())) for line in rows.stdout.splitlines() if re.fullmatch(rb'\s*\d+\s+\d+\s*',line)]
        if len(pairs)>=10 and all(b==1000003 for a,b in pairs):
            return perf
    return None
