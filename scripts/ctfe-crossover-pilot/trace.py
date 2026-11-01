"""Observe separately selected ordinary Cargo visits with the qualified Linux exec collector."""

from functools import cache
import registration as reg
import gzip
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PILOT = HERE.parent / 'branch-return-pmu'
KERNEL = reg.OBSERVER
PROJECTOR = '5e91ed3974c0964a912fd38049946f647891dcb2'
COMPILER_TREES = {'E': '89dcac9002ea6a0307d6fef82c0652b15c85dcca',
                  'C': '37bae6b16cbb4858b2dd597f70048cb7f2dc041c'}


def load(path, imports=None):
    """Keep the two historical packages' same-named modules out of the active worker."""
    spec = importlib.util.spec_from_file_location('ctfe_trace_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, imports or {}), patch.object(sys, 'path', [str(path.parent), *sys.path]):
        spec.loader.exec_module(module)
    return module


def record(path):
    return json.loads(path.read_bytes())


@cache
def packages():
    # pilot.py has already selected the measured worker. Reuse its environment and exact Cargo argv.
    with patch.object(sys, 'path', [str(PILOT), *sys.path]):
        import worker as ordinary
    b = ordinary.b
    b.need(Path(ordinary.__file__).resolve() == PILOT / 'worker.py', 'foreign ordinary Cargo worker')
    kernel_root = Path(os.environ['CTFE_EXECS_SOURCE']).resolve(strict=True)
    projector_root = Path(os.environ['CTFE_EXECS_PROJECTOR']).resolve(strict=True)
    for repo, head, prefix in ((kernel_root, KERNEL, 'scripts/branch-return-execstop'),
                               (kernel_root, KERNEL, 'scripts/branch-return-pmu'),
                               (projector_root, PROJECTOR, 'scripts/branch-return-pmu')):
        b.prepare_checkout(repo, head, prefix)
    kernel = kernel_root / 'scripts/branch-return-execstop'
    prior = projector_root / 'scripts/branch-return-pmu'
    for package in (kernel, prior):
        subprocess.run(['sha256sum', '--strict', '--check', '--status', 'SHA256SUMS'], cwd=package, check=True)
    old_b = load(prior / 'bindings.py')
    contact = load(prior / 'kernel_contact.py', {'bindings': old_b})
    processes = load(prior / 'processes.py', {'bindings': old_b})
    events = load(prior / 'kernel_events.py', {'bindings': old_b, 'kernel_contact': contact, 'processes': processes})
    history = load(kernel / 'history.py')
    images = load(kernel / 'images.py', {'history': history})
    reader = load(kernel / 'kernel/read_events.py')
    # The previously exercised invocation owns the exact subprocess, exit, raw streams and E0308 check.
    # Only its per-visit source and expected phase roster change for this distinct E/C history.
    adapter = SimpleNamespace(wrap=wrap, inventory=inventory, preserve=events.preserve, timeout=events.timeout)
    capture = load(prior / 'worker.py', {'bindings': b, 'kernel_contact': contact, 'kernel_events': adapter,
                                         'processes': processes, 'full_cli': ordinary.historical, 'study': ordinary.kit})
    b.need(capture.CARGO == ordinary.CARGO and capture.kit.TREE == ordinary.kit.TREE
           and old_b.ROOT == b.ROOT and old_b.SDK == b.SDK, 'different Cargo command or physical roots')
    return SimpleNamespace(b=b, subjects=load(HERE / 'subjects.py'), kernel=kernel, prior=prior, contact=contact,
                           events=events, images=images, reader=reader, capture=capture)


def prepare(mode, host, prior=None):
    p = packages()
    b, contact = p.b, p.contact
    seal, audit, root_audit = contact.spec()
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    contact.fresh_boot(boot, audit)
    reg.host(host)
    b.need(boot == host['boot'], 'different fixture and visit boot')
    if mode == 'full-pilot':
        b.need(record(b.OUT / 'meter-ready.json')['boot'] == boot and prior, 'unqualified prior contact or hardware boot')
        reg.fresh(boot, [prior['boot']])
    else:
        b.need(mode == 'contact' and prior is None and not (b.OUT/'meter-ready.json').exists(), 'unexpected PMU setup')
    contact.WORK.mkdir()
    contact.OUT.mkdir()
    fixtures = contact.OUT / 'fixtures'
    tool = p.kernel / 'group_fixtures.py'
    b.need(b.sha(p.kernel/'kernel/observe.c') == reg.SOURCE and b.sha(p.kernel/'kernel/read_events.py') == reg.READER,
           'wrong source or schema-2 reader')
    subprocess.run([sys.executable, '-IB', tool, 'run', contact.WORK/'tools', fixtures, b.SDK / b.WILD], check=True)
    physical = record(fixtures/'qualified.json')
    group = record(fixtures/'group-v2/qualified.json')
    reopened = json.loads(subprocess.check_output([sys.executable,'-IB',tool,'reopen',fixtures]))
    b.need(group == reopened and group['qualified'] is True and group['schema'] == 2 and group['boot'] == boot
           and group['stock_wild_sha256'] == b.WILD_ELF and physical['qualified'] is True
           and b.sha(contact.OBSERVER) == b.sha(fixtures/'observe.elf') == physical['observer_sha256'],
           'unqualified actual host observer and native fixtures')
    # Identify the source and executable separately. A contact binary is not a substitute for host qualification.
    if prior:
        b.need(prior['observer_source'] == KERNEL and prior['observer_sha256'] == physical['observer_sha256'],
               'activated observer differs from independently reopened v2 contact')
    b.save(contact.OUT/'binding.json', {'official':seal, 'independent':audit, 'root_independent':root_audit,
           'mode':mode, 'source':str(p.kernel), 'source_head':KERNEL, 'projector':str(p.prior),
           'projector_head':PROJECTOR, 'observer':str(contact.OBSERVER), 'observer_sha256':physical['observer_sha256'],
           'boot':boot, 'fixtures_sha256':b.sha(fixtures/'qualified.json'),
           'group_fixtures_sha256':b.sha(fixtures/'group-v2/qualified.json'),
           'prior_v2':None if prior is None else prior['official']})


def catalog(arm, rows, where, env):
    p = packages()
    b = p.b
    b.need(arm in p.subjects.ARMS and set(rows) == {'E', 'C'}, 'unexpected structural role')
    paths = {'cargo': b.SDK / 'bin/cargo', 'rustc': b.SDK / 'bin/rustc', 'wild': b.SDK / b.WILD,
             'proxy': b.PROXIES / 'rustup', 'sysld': Path('/usr/bin/ld')}
    tools = {name: {'path': str(path), 'resolved': str(path.resolve(strict=True)), 'identity': [b.sha(path), *b.numbers(path)]}
             for name, path in paths.items()}
    b.need(len({tuple(t['identity'][1:3]) for t in tools.values()}) == 5
           and all(tools[k]['identity'] == rows[arm[0]][str(paths[k].relative_to(b.SDK))] for k in ('rustc', 'cargo', 'wild'))
           and all(paths['proxy'].samefile(b.PROXIES / name) for name in ('cargo', 'rustc', 'rustdoc'))
           and tools['proxy']['identity'][0] == record(b.OUT / 'sdk/proxy.json')['sha256'],
           'different active SDK executable or rustup proxy')
    b.save(where / 'catalog.json', tools)
    loader = p.events.loader_driver(paths['rustc'], b.SDK / p.subjects.DRIVER, env, where)
    b.need(loader['driver_identity'] == rows[arm[0]][p.subjects.DRIVER], 'wrong resolved driver')
    b.save(where / 'loader.json', loader)


def source(where, arm, env, stage):
    p = packages()
    b, subjects = p.b, p.subjects
    enrolled = record(where.parent / 'arm.json')
    role = arm[0]
    path = b.SDK / subjects.DRIVER
    driver = [b.sha(path), *b.numbers(path)]
    native = record(b.OUT / 'sdk/ctfe-native-source.json')
    side = {'E': 'old', 'C': 'new'}[role]
    commit = {'E': subjects.E, 'C': subjects.C}[role]
    b.need(arm in subjects.ARMS and (enrolled['arm'], enrolled['role'], enrolled['sdk']) == (arm, role, str(b.SDK))
           and native[side] == commit and native['driver'] == subjects.DRIVER
           and native[side + '_driver'] == [driver[0], driver[4], driver[3]]
           and driver == enrolled['files'][subjects.DRIVER] == record(where.parent / 'loader.json')['driver_identity']
           and enrolled['source_manifest'] == subjects.MANIFEST[role]
           and env == enrolled['env'] == b.environment(arm, permitted=subjects.ARMS)
           and env['LD_LIBRARY_PATH'] == str(b.SDK / 'lib'), 'wrong source, dynamic driver or Cargo environment')
    for tool in record(where.parent / 'catalog.json').values():
        obj = Path(tool['path'])
        b.need(str(obj.resolve(strict=True)) == tool['resolved'] and b.numbers(obj) == tool['identity'][1:],
               ('changed native executable', obj))
    proof = {'source': commit, 'compiler_tree': COMPILER_TREES[role], 'driver': str(path), 'driver_identity': driver,
             'source_manifest': enrolled['source_manifest']}
    if stage == 'after':
        b.need(proof == record(where / 'source-before.json'), 'active compiler changed during ordinary Cargo')
    b.save(where / ('source-' + stage + '.json'), proof)


def wrap(where, arm, env):
    source(where, arm, env, 'before')
    return [str(packages().contact.OBSERVER), str(where / 'kernel.tsv'), '--']


def inventory(where, arm, rc, env):
    p = packages()
    source(where, arm, env, 'after')
    path = where / 'kernel.tsv'
    family = p.reader.read(path, expected_code=rc, expected_schema=2)
    p.b.save(where / 'lifecycle.json', {k: len(v) if isinstance(v, list) else v for k, v in family.items()})
    with gzip.open(where / 'cargo.json.gz') as stream:
        call = json.load(stream)
    command = p.capture.CARGO
    p.b.need(call['observer_argv'] == [str(p.contact.OBSERVER), str(path), '--', *command]
             and call['argv'] == command and call['env'] == env and call['exit'] == call['expected'] == rc
             and call['cwd'] == str(p.capture.kit.TREE), 'wrong wrapped ordinary Cargo')
    native = p.events.project(path, family, record(where.parent / 'catalog.json'), arm, p.images, command)
    p.b.save(where/'wild-helpers.json', reg.wild_helpers(path.read_bytes(), native['wild_processes']))
    if rc == 101:
        parser, = (r for r in native['rustcs'] if (r['crate'], r['mode']) == ('ruff_python_parser', 'full'))
        # Raw exit events and final waits are already paired by lifetime, PID and wait status in read().
        last = next(e for e in reversed(family['execs']) if e['lifetime'] == parser['lifetime'])
        p.b.need(last['ordinal'] == parser['event'], 'failing parser rustc replaced its image before exit')
        prefix = f"T\t{parser['lifetime']}\t{parser['pid']}\t".encode()
        with path.open('rb') as raw:
            statuses = [int(line[len(prefix):]) for line in raw if line.startswith(prefix)]
        p.b.need(len(statuses) == 1 and os.waitstatus_to_exitcode(statuses[0]) == 1, 'invalid edit did not fail in parser rustc')
    return native


def invocation(where, env, rc, arm):
    """Return the ordinary Cargo messages, no hardware count, and complete positive native exec rows."""
    return packages().capture.invocation(where, env, 'structural', rc, arm)
