"""Bind an ordinary developer environment and kernel-observed Rust incremental work products."""
import json
import os
from pathlib import Path
import stat

from study import digest, need, save, sha

HOST_KEYS = {'HOME', 'PATH', 'TMPDIR', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'TERM', 'DEVELOPER_DIR'}
STUDY_KEYS = {'RUSTUP_HOME', 'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_BUILD_BUILD_DIR',
              'CARGO_NET_OFFLINE', 'CARGO_TERM_COLOR', 'CARGO_CACHE_AUTO_CLEAN_FREQUENCY', 'LC_ALL', 'TZ'}


def developer_environment(host):
    return {key: host[key] for key in HOST_KEYS if key in host}


def environment_receipt(env):
    need(({'HOME', 'PATH'} | STUDY_KEYS) <= env.keys() <= (HOST_KEYS | STUDY_KEYS),
         'unexpected or missing developer command environment')
    return {key: digest(os.fsencode(env[key])) for key in sorted(env)}


def local_path(work, path):
    work = work.resolve(strict=True)
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'nonabsolute or ambiguous compiler incremental directory')
    physical = path.resolve(strict=False)
    # Darwin resolves /var and /tmp to /private/var and /private/tmp. Relative names below
    # the actual enrolled target/build roots must remain identical on both spellings.
    for name in ('target', 'shared'):
        base = work / name
        if physical.is_relative_to(base):
            need(physical != base and not base.is_symlink(), 'unexpected incremental root')
            return str(physical.relative_to(work))
    raise RuntimeError('compiler wrote incremental state outside the enrolled target or build root')


def increment_dirs(argv):
    flags = [b for a,b in zip(argv, argv[1:]) if a == '-C']
    flags.extend(a[2:] for a in argv if a.startswith('-C') and a != '-C')
    return [s[len('incremental='):] for s in flags if s.startswith('incremental=')]


def preparation(work):
    for name in ('target', 'shared'):
        d = work / name
        need(d.is_dir() and not d.is_symlink() and not any(d.iterdir()), 'nonempty selected cold installation')
    return {'target_entries': 0, 'shared_entries': 0}


def census(work, relative, crate_name="ty_vendored"):
    base = work / relative
    need(local_path(work, base) == relative and base.is_dir(), 'missing actual rustc incremental root')
    candidates = [base] if base.name.startswith(crate_name+'-') else sorted(base.glob(crate_name+'-*'))
    files = []
    for crate in candidates:
        if not crate.is_dir() or crate.is_symlink():
            continue
        for session in sorted(crate.glob('s-*')):
            if not session.is_dir() or session.is_symlink() or session.name.endswith('-working'):
                continue
            for path in sorted(session.rglob('*')):
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode):
                    continue
                files.append([str(path.relative_to(work)), st.st_dev, st.st_ino, st.st_size, st.st_blocks,
                              sha(path) if path.name in {'work-products.bin','dep-graph.bin'} or path.suffix == '.o' else None])
    unique = {(r[1],r[2]): r for r in files}
    return {'root':relative, 'files':files, 'allocated':512*sum(r[4] for r in unique.values()),
            'logical':sum(r[3] for r in unique.values()), 'objects':sum(Path(r[0]).suffix == '.o' and r[3] > 0 for r in files),
            'work_products':sum(Path(r[0]).name == 'work-products.bin' and r[3] > 0 for r in files),
            'dep_graphs':sum(Path(r[0]).name == 'dep-graph.bin' and r[3] > 0 for r in files)}


def check_cache(cache):
    need(all(cache[n] > 0 for n in ('objects','work_products','dep_graphs','allocated','logical')),
         'actual compiler incremental directory has no complete native work-product generation')


def observed(work, sdk, env, out, events, step, *, crate_name="ty_vendored", test=True):
    rustc = sdk / 'bin/rustc'
    emitters = []
    for event in events:
        args = event['argv']
        if not (('--test' in args) == test and '--crate-name' in args and args[args.index('--crate-name')+1] == crate_name):
            continue
        path = Path(event['path'])
        if not path.is_file() or not path.samefile(rustc) or any('link-only' in a for a in args):
            continue
        emits = [a.removeprefix('--emit=') for a in args if a.startswith('--emit=')]
        emits.extend(b for a,b in zip(args,args[1:]) if a == '--emit')
        need(any('link' in x.split(',') for x in emits), 'unexpected non-codegen root compiler')
        actual = increment_dirs(args)
        emitters.append({'pid':event['pid'], 'compiler':str(path), 'cdhash':event.get('cdhash'),
                         'args_sha256':digest(json.dumps(args,separators=(',',':')).encode()), 'incremental':actual})
    report = {'environment':environment_receipt(env), 'step':step, 'emitters':emitters, 'cache':None}
    roots = {local_path(work,r) for e in emitters for r in e['incremental']}
    if not emitters and step in ('repeat-1','repeat-2'):
        from study import load
        prior = load(out.parent/('edit' if step=='repeat-1' else 'repeat-1')/'local-incremental.json')
        roots = {prior['cache']['root']}
        report['previous_root'] = next(iter(roots))
    if len(roots) == 1:
        rel, = roots
        if (work/rel).is_dir():
            report['cache'] = census(work, rel, crate_name)
    save(out/'local-incremental.json', report)
    need((not emitters and step in ('repeat-1','repeat-2') or len(emitters)==1 and len(emitters[0]['incremental'])==1) and len(roots)==1,
         f'actual local {crate_name} full compiler did not receive exactly one -C incremental')
    if step != 'invalid':
        need(report['cache'] is not None,'missing rustc incremental output')
        check_cache(report['cache'])
    return report
