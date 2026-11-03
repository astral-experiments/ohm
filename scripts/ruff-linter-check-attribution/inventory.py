"""Record the real downstream work after the Origin::path edit in Ruff #27470."""
import ast
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker as w


EXEC = re.compile(r'^execve\(("(?:\\.|[^"\\])*"), (\[.*?\]), .*\)\s+= 0$')
PRODUCER = 'annotate_snippets'  # The library target of package ruff_annotate_snippets.
DIRECT = {'ruff_db', 'ty_site_packages'}
TARGET = 'ty_server'
WITNESSES = {PRODUCER, *DIRECT, TARGET}
INVALID = 'const _: () = "OHM_VISIBILITY_E0308";'


def executed_compilers(trace):
    """Keep kernel-observed native compiler arguments, including the actual output modes."""
    compiler = (w.SDK/'bin/rustc').stat()
    roots = []
    for path in sorted(trace.glob('exec.[0-9]*')):
        for line in path.read_text().splitlines():
            if not line.startswith(('execve(', 'execveat(')) or not line.endswith('= 0'):
                continue
            m = EXEC.fullmatch(line)
            w.need(m, ('unsupported successful exec', line[:140]))
            exe, args = map(ast.literal_eval, m.groups())
            if '--crate-name' not in args:
                continue
            st = Path(exe).stat()
            if (st.st_dev, st.st_ino) != (compiler.st_dev, compiler.st_ino):
                continue
            name = args[args.index('--crate-name') + 1]
            w.need(args.count('--crate-name') == 1, 'ambiguous compiler unit')
            roots.append({'pid': int(path.suffix[1:]), 'crate': name, 'argv': args})
    return roots


def metadata_outputs(arts):
    """Preserve distinct Cargo units when a local crate builds for both host and target."""
    workspace, witnesses = {}, {}
    crates = set()
    for artifact in arts:
        target = artifact['target']
        if not artifact['package_id'].startswith('path+file:') or target['kind'] != ['lib']:
            continue
        for output in artifact['filenames']:
            path = Path(output)
            if path.suffix != '.rmeta':
                continue
            name = target['name']
            key = name + '/' + path.name
            w.need(key not in workspace, ('duplicate metadata unit', key))
            workspace[key] = path
            crates.add(name)
            if name in WITNESSES:
                w.need(name not in witnesses, ('multiple profiles for an enrolled witness', name))
                witnesses[name] = path
    w.need(witnesses.keys()==WITNESSES, ('missing enrolled crate', sorted(WITNESSES-witnesses.keys())))
    return workspace, witnesses, sorted(crates)


def phase(name, state, *, preserve=False, invalid=False, observe=None):
    """Compare complete Cargo verdicts separately from native compiler process inventories."""
    trace = w.ROOT/'traces'/w.OUT.name/name
    trace.mkdir(parents=True)
    out = w.OUT/name
    env = w.environment()
    score = observe is None and w.OUT.name in ('P','C') and name in ('old','old-unchanged','edited','new-unchanged')
    ordinary = w.CMD
    if score:
        proxy = shutil.which('cargo', path=env['PATH'])
        w.need(proxy and w.CMD[0]=='cargo', 'ordinary cargo proxy')
        ordinary = [w.ROOT/'whole-count',out/'pmu.json',proxy,*w.CMD]
    cmd = ['/usr/bin/strace', '-ff', '-qq', '-s', '131072', '-e', 'trace=execve,execveat',
           '-o', trace/'exec', '--', *ordinary]
    if observe is None:
        w.run(cmd, env, out, expected=101 if invalid else 0)
    else:
        w.need(not invalid and not score, "overlapping or failed counter scope")
        roots = observe(out, env)
    if score:
        pm = json.loads((out/'pmu.json').read_bytes())
        w.need(pm['instructions']>0 and pm['enabled']==pm['running']>0 and os.waitstatus_to_exitcode(pm['status'])==0,
               'incomplete or multiplexed whole-Cargo count')
        first = next(line for line in (trace/('exec.'+str(pm['pid']))).read_text().splitlines()
                     if line.startswith('execve(') and line.endswith('= 0'))
        entry = EXEC.fullmatch(first)
        w.need(entry and os.path.samefile(ast.literal_eval(entry[1]),proxy) and ast.literal_eval(entry[2])==w.CMD,
               'the first counted process did not execute this Cargo command')
    if observe is None:
        roots = executed_compilers(trace)
    w.save(out/'rustcs.json', roots)
    rows = [json.loads(s) for s in (out/'stdout').read_bytes().splitlines() if s]
    finished = [r['success'] for r in rows if r['reason'] == 'build-finished']
    w.need(finished == [not invalid], ('incomplete Cargo verdict', name))
    diagnostics = []
    for r in rows:
        if r['reason'] == 'compiler-message':
            d = r['message']
            diagnostics.append((d['level'], (d.get('code') or {}).get('code',''), d['message']))
            if invalid and d['level'] == 'error' and (d.get('code') or {}).get('code') == 'E0308':
                w.need(any(s['file_name'].endswith(w.SOURCE) and INVALID in str(s['text']) for s in d['spans']),
                       'invalid verdict refers to another edit')
    w.need(any(d[1]=='E0308' for d in diagnostics) == invalid, 'missing requested type verdict')
    w.need(b'internal compiler error' not in (out/'stderr').read_bytes().lower(), 'compiler ICE')
    counts = dict(sorted(Counter(r['crate'] for r in roots).items()))
    summary = {'revision': state, 'counts': counts, 'diagnostics': sorted(diagnostics)}
    if not invalid:
        arts = [r for r in rows if r['reason']=='compiler-artifact']
        workspace, witnesses, summary['workspace_crates'] = metadata_outputs(arts)
        inventory = []
        for a in arts:
            t = a['target']
            inventory.append([a['package_id'], t['name'], t['kind'], sorted(a['features']),
                              json.dumps(a['profile'], sort_keys=True), sorted(Path(f).name for f in a['filenames'])])
        summary['workspace_rmeta'] = {k:w.sha(p) for k,p in sorted(workspace.items())}
        summary['inventory'] = sorted(inventory)
        if preserve:
            dest = out/'witness-rmeta.tar.zst'
            with dest.open('xb') as body, subprocess.Popen(['/usr/bin/zstd','-q','-1','-c'], stdin=subprocess.PIPE, stdout=body) as pack:
                with tarfile.open(fileobj=pack.stdin, mode='w|') as archive:
                    for k in sorted(WITNESSES):
                        p=witnesses[k]
                        w.need(1024 < p.stat().st_size < 64*(1<<20), 'unexpected witness size')
                        archive.add(p, arcname=k+'.rmeta', recursive=False)
                pack.stdin.close()
                w.need(pack.wait()==0, 'incomplete witness archive')
            summary['witness_archive_sha'] = w.sha(dest)
    w.save(out/'phase.json', summary)
    print(name, counts, flush=True)
    return summary


def main(*, phase=phase):
    w.checked_head()
    w.source(w.NEW)
    w.fresh_state()
    w.checkout(w.OLD)
    old = phase('old', w.OLD, preserve=True)
    before = phase('old-unchanged', w.OLD)
    w.checkout(w.NEW)
    edited = phase('edited', w.NEW, preserve=True)
    after = phase('new-unchanged', w.NEW)
    src = w.SRC/w.SOURCE
    original = src.read_bytes()
    try:
        src.write_bytes(original + b'\n' + INVALID.encode() + b'\n')
        phase('invalid', w.NEW, invalid=True)
    finally:
        src.write_bytes(original)
    w.source(w.NEW)
    repair = phase('repair', w.NEW)
    w.fresh_state()
    clean = phase('clean', w.NEW, preserve=True)
    w.need(all(r['inventory']==edited['inventory'] for r in (old,before,after,repair,clean)),
           'the ordinary library target graph changed')
    w.need(all(r['diagnostics']==clean['diagnostics'] for r in (edited,after,repair)),
           'the clean and warm NEW verdicts differ')
    w.need(PRODUCER in edited['counts'], 'source edit did not invoke its compiler')
    floor = set(before['counts']) | set(after['counts'])
    indirect = set(edited['counts']).intersection(edited['workspace_crates']) - DIRECT - {PRODUCER} - floor
    w.save(w.OUT/'terminal.json', {'head': os.environ['REVIEWED_HEAD'], 'old': w.OLD, 'new': w.NEW,
           'edited': edited['counts'], 'old_noop': before['counts'], 'new_noop': after['counts'],
           'indirect_beyond_noop': sorted(indirect), 'clean_verdict': clean['diagnostics'],
           'clean_metadata_differences': sorted(k for k,h in clean['workspace_rmeta'].items() if edited['workspace_rmeta'][k]!=h)})


if __name__ == '__main__':
    main()
