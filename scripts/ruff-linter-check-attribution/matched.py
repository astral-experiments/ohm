"""Run the real ty_server check on the paired source compilers at one fixed sysroot path."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inv
import visibility_probe
import worker as w


LOADER = '1273cbdd1b8c827ea4d2fc2141348c8e683336ed'
SOURCE = {'P':'259ad7069e47eaf08cf106f187b2b6393f7fd7c2', 'C':'a7fc5bc7f90966e6e9a92f9239e3e304e79b2f3f'}
FACTORY = '3a830cdc9f00b01c7110fac3653d8cd0b305c355'
COUNT_SHA = '096b9e9efb7457ff4c2fd194985f18c4e05520fce46c85e5919b084ae3d823ce'


def acquire():
    loader_repo = w.WS/'scope-loader'
    w.need(w.git(loader_repo, 'rev-parse','HEAD') == LOADER and
           not w.git(loader_repo,'status','--porcelain','--untracked-files=all'), 'different donor loader')
    source = loader_repo/'scripts/ruff-linter-check-attribution'
    spec = importlib.util.spec_from_file_location('qualified_scope_loader', source/'scope_matched.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    w.need(module.w is w, 'donor loader did not use this worker')
    binding = json.loads((w.HERE/'typed-factory-binding.json').read_bytes())
    w.need(binding['run']==41568934075 and binding['head']==FACTORY and binding['source']==SOURCE,
           'different field-visibility source factory')
    kit = module.kit('root', binding)
    arms = {}
    for role, variant in [('P','normal'),('C','defer')]:
        root = Path(kit['arms'][variant]['root'])
        driver, = (root/'lib').glob('librustc_driver-*.so')
        arms[role] = {'root':str(root), 'driver':w.sha(driver), 'rustc':w.sha(root/'bin/rustc'),
                      'cargo':w.sha(root/'bin/cargo'), 'source':SOURCE[role]}
        w.need(arms[role]['driver']==binding['driver'][role], 'unexpected rustc driver')
    w.need(arms['P']['cargo']==arms['C']['cargo'] and arms['P']['driver']!=arms['C']['driver'],
           'expected a compiler-only pair')
    w.save(w.OUT/'matched-arms.json', arms)


def study():
    w.checked_head()
    order = os.environ['ROLE_ORDER']
    w.need(order in ('PC','CP'), 'unknown mirror')
    w.need(w.sha(w.HERE/'whole_count.c') == COUNT_SHA, 'different hardware observer')
    counter = w.ROOT/'whole-count'
    subprocess.run(['/usr/bin/cc','-O2','-Wall','-Wextra','-Werror',w.HERE/'whole_count.c','-o',counter],check=True)
    top = w.OUT
    arms = json.loads((top/'matched-arms.json').read_bytes())
    w.need(w.SDK.parent==w.ROOT and w.SDK.is_dir() and not w.SDK.is_symlink(), 'expected the independent signed SDK')
    w.SDK.rename(w.ROOT/'signed-control-sdk')
    for role in order:
        arm = arms[role]
        if w.SDK.exists():
            w.need(not w.SDK.is_symlink() and w.SDK.parent==w.ROOT, 'unsafe fixed-path replacement')
            shutil.rmtree(w.SDK)
        subprocess.run(['cp','-a','--reflink=auto',arm['root'],w.SDK],check=True)
        driver, = (w.SDK/'lib').glob('librustc_driver-*.so')
        w.need(w.sha(driver)==arm['driver'] and w.sha(w.SDK/'bin/rustc')==arm['rustc'] and
               w.sha(w.SDK/'bin/cargo')==arm['cargo'], 'wrong installed compiler')
        w.OUT = top/role
        w.OUT.mkdir()
        w.save(w.OUT/'compiler.json', dict(arm, rustc_vV=subprocess.check_output(['rustc','+ohm','-vV'],
                                                           cwd=w.SRC,env=w.environment(),text=True)))
        inv.main()
        visibility_probe.probe()
    w.OUT = top
    terminals = {role:json.loads((top/role/'terminal.json').read_bytes()) for role in ('P','C')}
    stages = ('old','old-unchanged','edited','new-unchanged')
    costs = {role:{name:json.loads((top/role/name/'pmu.json').read_bytes()) for name in stages} for role in order}
    w.need(all(terminals[role]['clean_verdict']==[] and terminals[role]['old_noop']=={} and
               terminals[role]['new_noop']=={} for role in order), 'different controls')
    w.need((top/'P/visibility.json').read_bytes()==(top/'C/visibility.json').read_bytes(),
           'compiler roles disagree on the downstream access error')
    w.save(top/'comparison.json', {'order':order,'head':os.environ['REVIEWED_HEAD'],'sources':SOURCE,
           'raw':costs,'terminals':terminals,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
           'scope':'enrolled descriptive mirrored pilot including complete Cargo and descendants'})


if __name__=='__main__':
    {'acquire':acquire, 'study':study}[sys.argv[1]]()
