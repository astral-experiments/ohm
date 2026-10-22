"""Compare audited APFS cohorts with the test/build overlap option changed."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FLAG = 'CARGO_UNSTABLE_OHM_READY_TESTS'


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def auditor(variant):
    path = ROOT/variant/'bench/export-disk.py'
    spec = importlib.util.spec_from_file_location(variant.replace('-','_')+'_audit',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helpers(variant):
    result = {}
    for entry in load(ROOT/variant/'disk/tools/verified.json'):
        name = entry['name']
        path = Path(entry['path']) if name == 'python3.12' else ROOT/variant/'disk/tools/bin'/name
        expected = entry.get('binary_sha256') or entry['sha256']
        assert sha(path) == expected, name
        result[name] = {'version':entry['version'], 'sha256':expected}
    return result


def normalized_environment(state, evidence):
    environment = dict(state['environment'])
    environment.pop(FLAG, None)
    mount = Path(load(evidence/'volume.json')['mount'])
    roles = {
        'CARGO_TARGET_DIR':'targets/1', 'CARGO_BUILD_BUILD_DIR':'shared-build',
        'TMPDIR':'tmp', 'UV_CACHE_DIR':'runtime/uv', 'XDG_CACHE_HOME':'runtime/xdg',
        'CARGO_BIN_EXE_uv':'targets/1/debug/uv',
    }
    for name, relative in roles.items():
        if name not in environment:
            assert name == 'CARGO_BIN_EXE_uv' and state['cell'].startswith('ruff-')
            continue
        assert Path(environment[name]) == mount/relative, (state['cell'], name)
        environment[name] = '$COHORT/' + relative
    # The opt-in tools directory points to the verified default helper binaries.
    environment['PATH'] = ':'.join(str(Path(path).resolve())
                                   for path in environment['PATH'].split(':'))
    return environment


def main():
    modules = {name:auditor(name) for name in ('apfs','apfs-ready-tests')}
    for name in modules:
        assert load(ROOT/name/'disk/compatible-controller.json')['state'] == 'complete'
    helper_identity = helpers('apfs')
    assert helpers('apfs-ready-tests') == helper_identity
    reports = []
    for project in ('ruff','uv'):
        for mode in ('single','forks'):
            cell = f'{project}-ohm-{mode}'
            compared = {}
            for variant,module in modules.items():
                evidence = ROOT/variant/'disk/evidence'/cell
                state,receipt = module.audited_cohort(evidence)
                expected = 'true' if variant == 'apfs-ready-tests' else None
                assert state['environment'].get(FLAG) == expected
                compared[variant] = (state,receipt,evidence)
            default,baseline,base_path = compared['apfs']
            ready,opt_in,ready_path = compared['apfs-ready-tests']
            assert default['fixture_sha256'] == ready['fixture_sha256']
            assert default['toolchain_identity'] == ready['toolchain_identity']
            assert default['selector'] == ready['selector'] == 'ohm-1.99.0-6'
            assert normalized_environment(default, base_path) == normalized_environment(ready, ready_path)
            assert baseline['source_proofs'] == opt_in['source_proofs']
            assert baseline['worktrees'] == opt_in['worktrees']
            assert baseline['cargo_commands'] == opt_in['cargo_commands']
            for before,after in zip(baseline['commands'],opt_in['commands'],strict=True):
                for field in ('command','tests_started','worktree','phase','index'):
                    assert before[field] == after[field], (cell,field)
            reports.append({'project':project,'cohort':mode,'worktrees':baseline['worktrees'],
                'default_bytes':baseline['idle_bytes'],'ready_tests_bytes':opt_in['idle_bytes'],
                'ready_tests_percent_saved':100*(baseline['idle_bytes']-opt_in['idle_bytes'])/baseline['idle_bytes'],
                'source_trees_match':True,'commands_and_test_counts_match':True,
                'default_audit_sha256':sha(base_path/'audit.json'),
                'ready_tests_audit_sha256':sha(ready_path/'audit.json'),
                'default_results_sha256':sha(base_path/'results.json'),
                'ready_tests_results_sha256':sha(ready_path/'results.json')})
    report = {'release':'ohm-1.99.0-6','comparisons':reports,
        'methodology':{'metric':'retained bytes after completed cohort and at least 30 seconds idle',
            'elapsed_times_are_performance_measurements':False,'ready_tests_setting':FLAG+'=true',
            'identical_binaries_sources_commands_and_other_explicit_settings':True,
            'sample_count':1,'filesystem':'APFS'},
        'helpers':helper_identity, 'exporter_sha256':sha(Path(__file__))}
    output = ROOT/'reports';output.mkdir(exist_ok=True)
    (output/'disk-ready-tests.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'comparisons':len(reports),'passed':True}))


if __name__ == '__main__':
    main()
