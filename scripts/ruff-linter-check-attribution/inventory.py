"""Record the real downstream work after the Origin::path edit in Ruff #27470."""
import ast
from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worker as w


EXEC = re.compile(r'^execve\(("(?:\\.|[^"\\])*"), (\[.*?\]), .*\)\s+= 0$')
PRODUCER = 'ruff_annotate_snippets'
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


def phase(name, state, *, preserve=False, invalid=False):
    """Compare complete Cargo verdicts separately from native compiler process inventories."""
    trace = w.ROOT/'traces'/name
    trace.mkdir(parents=True)
    out = w.OUT/name
    cmd = ['/usr/bin/strace', '-ff', '-qq', '-s', '131072', '-e', 'trace=execve,execveat',
           '-o', trace/'exec', '--', *w.CMD]
    w.run(cmd, w.environment(), out, expected=101 if invalid else 0)
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
        workspace = {}
        inventory = []
        for a in arts:
            t = a['target']
            inventory.append([a['package_id'], t['name'], t['kind'], sorted(a['features']),
                              json.dumps(a['profile'], sort_keys=True), sorted(Path(f).name for f in a['filenames'])])
            if not a['package_id'].startswith('path+file:') or t['kind'] != ['lib']:
                continue
            files = [Path(f) for f in a['filenames'] if Path(f).suffix=='.rmeta']
            if files:
                w.need(len(files)==1 and t['name'] not in workspace, 'ambiguous local metadata')
                workspace[t['name']] = files[0]
        w.need(WITNESSES <= workspace.keys(), ('missing enrolled crate', sorted(WITNESSES-workspace.keys())))
        summary['workspace_rmeta'] = {k:w.sha(p) for k,p in sorted(workspace.items())}
        summary['inventory'] = sorted(inventory)
        if preserve:
            dest = out/'witness-rmeta.tar.zst'
            with dest.open('xb') as body, subprocess.Popen(['/usr/bin/zstd','-q','-1','-c'], stdin=subprocess.PIPE, stdout=body) as pack:
                with tarfile.open(fileobj=pack.stdin, mode='w|') as archive:
                    for k in sorted(WITNESSES):
                        p=workspace[k]
                        w.need(1024 < p.stat().st_size < 64*(1<<20), 'unexpected witness size')
                        archive.add(p, arcname=k+'.rmeta', recursive=False)
                pack.stdin.close()
                w.need(pack.wait()==0, 'incomplete witness archive')
            summary['witness_archive_sha'] = w.sha(dest)
    w.save(out/'phase.json', summary)
    print(name, counts, flush=True)
    return summary


def main():
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
    indirect = set(edited['counts']).intersection(edited['workspace_rmeta']) - DIRECT - {PRODUCER} - floor
    w.save(w.OUT/'terminal.json', {'head': os.environ['REVIEWED_HEAD'], 'old': w.OLD, 'new': w.NEW,
           'edited': edited['counts'], 'old_noop': before['counts'], 'new_noop': after['counts'],
           'indirect_beyond_noop': sorted(indirect), 'clean_verdict': clean['diagnostics'],
           'clean_metadata_differences': sorted(k for k,h in clean['workspace_rmeta'].items() if edited['workspace_rmeta'][k]!=h)})


if __name__ == '__main__':
    main()
