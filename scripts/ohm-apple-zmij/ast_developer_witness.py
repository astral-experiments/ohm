"""Identify the real local AST compiler and its concrete work-product generation."""
from pathlib import Path

from local_incremental import environment_receipt, observed
from study import load, need, save


def runtime(env):
    environment_receipt(env)
    work=Path(env['CARGO_TARGET_DIR']).parent.resolve(strict=True)
    sdk=(Path(env['RUSTUP_HOME'])/'toolchains/ohm').resolve(strict=True)
    need(sdk.name=='native' and Path(env['CARGO_BUILD_BUILD_DIR']).resolve()==work/'shared', 'non-enrolled developer environment')
    return work,sdk


def before(work):
    generations={}
    for root in (work/'target',work/'shared'):
        for crate in root.rglob('ruff_python_ast-*'):
            if not crate.is_dir() or crate.is_symlink():continue
            for session in crate.glob('s-*'):
                work_products=session/'work-products.bin'
                if not session.is_dir() or session.is_symlink() or not work_products.is_file():continue
                st=work_products.stat()
                generations[str(session.relative_to(work))]=[st.st_dev,st.st_ino,st.st_size]
    return generations


def after(host, env, out, events, previous, verb):
    work,sdk=host;step=out.name
    report=observed(work,sdk,env,out,events,step,crate_name='ruff_python_ast',test=verb=='test')
    current=before(work)
    delta={name:stamp for name,stamp in current.items() if previous.get(name)!=stamp}
    save(out/'ast-generations.json',{'before':previous,'after':current,'new_or_changed':delta})
    if step.startswith('clean') or step=='cold':
        need(not previous and delta,'cold compiler has no independent AST generation')
    if step=='edit':
        need(delta,'real source edit did not write a distinct AST generation')
    if step!='invalid':
        cache=report['cache']
        sessions={str(Path(row[0]).parent) for row in cache['files'] if row[0].endswith('/work-products.bin')}
        need(bool(sessions) and sessions<=current.keys(),'cache is not the compiler-selected AST work')
        if step.startswith('clean') or step in ('cold','edit'):
            need(bool(sessions & delta.keys()),'observed compiler and new on-disk AST generation disagree')


def timed_final(work, out):
    generations=before(work)
    need(generations,'no physical Ruff AST session after ordinary clocks')
    census={}
    from local_incremental import census as read_cache, check_cache, local_path
    for directory in sorted({(work/path).parent.parent for path in generations}):
        row=read_cache(work,local_path(work,directory),'ruff_python_ast')
        check_cache(row)
        census[str(directory.relative_to(work))]=row
    save(out/'timed-final-ast-cache.json',{'generations':generations,'census':census})
