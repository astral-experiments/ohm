"""Summarize the matched default and opt-in measurements after their audits."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reports', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
names = ('workflow', 'sessions', 'historical', 'developer-workflows',
         'ablation-overlap', 'constructed-overlap', 'disk-ready-tests', 'ty-worktree')
reports = {name: json.loads((args.reports / (name + '.json')).read_text()) for name in names}
for report in reports.values():
    assert report.get('ohm_release', report.get('release', report.get('ohm'))) == 'ohm-1.99.0-6'
assert reports['constructed-overlap']['methodology']['test_threads_per_executable'] == 1

def saved(default, enabled):
    assert all(math.isfinite(value) and value > 0 for value in (default, enabled))
    return 100 * (default - enabled) / default

comparisons = []
for suite in ('workflow', 'developer-workflows'):
    for row in reports[suite]['comparisons']:
        default, enabled = row['ohm_seconds'], row['ready_tests_seconds']
        default_failures = row.get('ohm_failures', 0)
        enabled_failures = row.get('ready_tests_failures', 0)
        assert (default is None) == bool(default_failures)
        assert (enabled is None) == bool(enabled_failures)
        comparisons.append({
            'suite': suite, 'project': row['project'], 'workflow': row['workflow'],
            'phase': row.get('phase'), 'default_seconds': default,
            'ready_tests_seconds': enabled,
            'default_failures': default_failures, 'ready_tests_failures': enabled_failures,
            'percent_saved': (saved(default, enabled)
                              if default is not None and enabled is not None else None),
            'samples_per_configuration': row.get('samples', reports[suite]['repetitions']),
            'aggregation': 'median',
        })
for suite in ('sessions', 'historical', 'ablation-overlap', 'constructed-overlap'):
    report = reports[suite]
    field = 'timed_session_seconds' if suite == 'sessions' else 'timed_command_seconds'
    aggregate = statistics.mean if suite == 'sessions' else statistics.median
    for project, values in report[field].items():
        default, enabled = values['ohm'], values['ohm-ready-tests']
        assert len(default) == len(enabled) == report['repetitions']
        before, after = aggregate(default), aggregate(enabled)
        comparisons.append({
            'suite': suite, 'project': project, 'default_seconds': before,
            'phase': 'after edit' if suite == 'constructed-overlap' else None,
            'ready_tests_seconds': after, 'percent_saved': saved(before, after),
            'default_samples': default, 'ready_tests_samples': enabled,
            'samples_per_configuration': len(default),
            'aggregation': ('mean of full replay totals, including edits and runner overhead; warmup excluded'
                            if suite == 'sessions' else
                            'median of each replay\'s timed-command total; edits and warmup excluded'),
        })
        if suite == 'constructed-overlap':
            assert len(report['warmups'][project]) == 1
            cold = report['untimed_warmup_seconds'][project]
            default, enabled = cold['ohm'], cold['ohm-ready-tests']
            assert len(default) == len(enabled) == report['repetitions']
            before, after = statistics.median(default), statistics.median(enabled)
            comparisons.append({
                'suite': suite, 'project': project, 'phase': 'cold baseline',
                'default_seconds': before, 'ready_tests_seconds': after,
                'percent_saved': saved(before, after),
                'default_samples': default, 'ready_tests_samples': enabled,
                'samples_per_configuration': len(default),
                'aggregation': 'median wall time of the recorded baseline test command, starting from fresh artifacts; reported separately from the edited replay',
            })
ty = reports['ty-worktree']['session']
ty_default, ty_enabled = ty['ohm']['total']['samples'], ty['ohm-ready-tests']['total']['samples']
assert len(ty_default) == len(ty_enabled) == 4
before, after = statistics.mean(ty_default), statistics.mean(ty_enabled)
comparisons.append({
    'suite': 'ty-session', 'project': 'ty', 'default_seconds': before,
    'ready_tests_seconds': after, 'percent_saved': saved(before, after),
    'default_samples': ty_default, 'ready_tests_samples': ty_enabled,
    'samples_per_configuration': 4,
    'aggregation': 'mean of session totals, including edits and runner overhead; initial CLI build excluded',
})

activation = {}
for suite in names:
    for row in reports[suite].get('overlap_observations', []):
        key = (suite, row['project'], row['toolchain'], 'timed' if row['measured'] else 'warmup')
        counts = activation.setdefault(key, collections.Counter())
        counts['commands'] += 1
        counts['commands_with_test_launches'] += int(bool(row['logged_test_launches']))
        counts['commands_with_uncovered_test_executables'] += int(bool(row['uncovered_test_executables']))
        counts['early_test_output'] += int(row['running_before_build_finished'])
        counts['test_result_before_finished_message'] += int(row['test_result_before_build_finished'])
        counts['sampled_compiler_test_concurrency'] += int(bool(row['matched_process_observations']))
activation = [{'suite': key[0], 'project': key[1], 'toolchain': key[2], 'phase': key[3], **counts}
              for key, counts in sorted(activation.items())]
result = {
    'release': 'ohm-1.99.0-6',
    'option': 'CARGO_UNSTABLE_OHM_READY_TESTS=true',
    'comparisons': comparisons, 'disk_comparisons': reports['disk-ready-tests']['comparisons'],
    'activation': activation,
    'methodology': {
        'paired_ohm_binaries_identical': True,
        'other_settings_unchanged_within_each_suite': True,
        'suite_settings': {
            'individual_commands': 'Existing profiles; no procedural-macro or native-tool trust overrides',
            'generic_replays': 'Shared build state; procedural-macro trust all; native-tool trust none',
            'developer_workflows_ty_and_disk': 'Shared build state and both trust options all',
        },
        'interpretation': 'Positive percentages mean the overlap option saved time or retained space.',
        'coverage': 'The parser-edit comparison repeats the existing ablation fixture with three configurations; the separate four-way feature ablation is unchanged.',
        'constructed_cold_baseline': 'The workspace workload records its baseline cargo test command from fresh artifacts. Its duration is reported separately; it remains excluded from the edited replay total.',
        'constructed_test_threads': 'RUST_TEST_THREADS=1 in every configuration of the constructed workspace workload avoids a process-global certificate-environment race in uv-client tests. Cargo may still overlap test executables with compilation. The earlier parallel-libtest attempt is excluded in full and retained in the raw evidence.',
        'worktree_scope': 'The worktree startup study retains stock, shared-build, and trusted-clone configurations. Nextest builds with --no-run, which disables early Cargo test execution.',
        'sampling_limit': 'Two-second sampling can miss short overlap. The original monitor recognizes only deps-directory executables and misses Ohm private outputs. The supplemental parser-edit run records all owned executables. Early test output alone does not prove simultaneous compiler execution.',
        'log_analysis': 'Cargo messages interleaved with partial libtest output are recovered from the saved logs. The constructed-workload report records each correction and its log hash; timings and test counts are unchanged.',
        'causal_scope': 'Same-release option comparison; historical releases are not a controlled comparison.',
    },
    'input_sha256': {name: hashlib.sha256((args.reports / (name + '.json')).read_bytes()).hexdigest()
                     for name in names},
    'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
args.output.mkdir(parents=True, exist_ok=True)
(args.output / 'ready-tests.json').write_text(json.dumps(result, indent=2) + '\n')

lines = [
    '# Test/build overlap', '',
    'We compare the published Ohm 1.99.0-6 binary with the overlap option unset and with '
    '`CARGO_UNSTABLE_OHM_READY_TESTS=true`. Each pair uses the same source, commands, profiles, '
    'and cache settings on the same host. Linux timing runs rotate and reverse the configuration '
    'order. APFS allocation cohorts run with the option unset first, then enabled.', '',
    'Positive percentages mean the option saved time. Small differences, especially with two '
    'repetitions or a single cold build, may reflect measurement variation.', '',
    'The option applies to Cargo’s test runner. Cargo '
    '[disables it for `--no-run` and JSON build output](https://github.com/astral-sh/ohm-cargo/blob/5e5d271d763d7beb38b48755e22bd59e93f02b97/src/ops/cargo_test/mod.rs#L70-L78), '
    'which Nextest uses to build its test executables. Ruff/ty and Codex use Nextest in these '
    'workflows, so their timings provide a control. UV uses `cargo test`; the constructed '
    'workspace workload selects multiple test executables that can overlap with remaining builds.', '',
]
workspace = next(row for row in comparisons if row['suite'] == 'constructed-overlap' and row['phase'] == 'after edit')
recorded_uv = next(row for row in comparisons if row['suite'] == 'sessions' and row['project'] == 'uv')
lines[4:4] = [
    f"With {workspace['samples_per_configuration']} repetitions, overlap reduced the median edited test command "
    f"in the constructed uv workspace workload from {workspace['default_seconds']:.2f} s to "
    f"{workspace['ready_tests_seconds']:.2f} s ({workspace['percent_saved']:.1f}%). "
    f"The recorded uv session changed from a mean of {recorded_uv['default_seconds']:.2f} s to "
    f"{recorded_uv['ready_tests_seconds']:.2f} s ({recorded_uv['percent_saved']:.1f}%, "
    f"{recorded_uv['samples_per_configuration']} repetitions); interpret that smaller difference alongside the Nextest controls.",
    '',
]
titles = {'developer-workflows': 'Developer workflows', 'sessions': 'Session replays',
          'historical': 'Historical session', 'ty-session': 'ty session',
          'ablation-overlap': 'Parser-edit benchmark', 'constructed-overlap': 'Constructed workspace test workload',
          'workflow': 'Individual commands'}

def timing(row, key):
    failures = row.get(key + '_failures', 0)
    if failures:
        return f"Failed ({failures}/{row['samples_per_configuration']})"
    value = row[key + '_seconds']
    return f"{value:.3f} s" if value < 1 else f"{value:.2f} s"

workflow_labels = {
    'edit-test': 'edit → focused test',
    'dependency-test': 'edit dependency → downstream test',
    'edit-check-test-check': 'edit → check → test → check',
    'check-build-check': 'check → build → check',
    'edit-fmt-clippy-test': 'edit → format → Clippy → test',
    'build-check': 'build → check',
    'shared-build': 'shared build',
}
phase_labels = {'noop': 'no edit', 'direct': 'direct edit', 'dependency': 'dependency edit'}

for suite, title in titles.items():
    rows = [row for row in comparisons if row['suite'] == suite]
    lines += ['## ' + title, '', '| Workload | Overlap off | Overlap on | Time saved | Repetitions |',
              '| --- | ---: | ---: | ---: | ---: |']
    for row in rows:
        project = {'codex-core': 'Codex core', 'codex': 'Codex', 'ruff': 'Ruff/ty'}.get(row['project'], row['project'])
        parts = [project]
        if row.get('workflow'):
            parts.append(workflow_labels.get(row['workflow'], row['workflow']))
        if row.get('phase'):
            parts.append(phase_labels.get(row['phase'], row['phase']))
        label = ' / '.join(parts)
        percentage = f"{row['percent_saved']:+.1f}%" if row['percent_saved'] is not None else '—'
        lines.append(f"| {label} | {timing(row, 'default')} | {timing(row, 'ready_tests')} | "
                     f"{percentage} | {row['samples_per_configuration']} |")
    aggregations = list(dict.fromkeys(row['aggregation'] for row in rows))
    lines += ['', 'Aggregation: ' + '. '.join(aggregations) + '.', '']
    if any(row['percent_saved'] is None for row in rows):
        lines += ['A failed configuration shows its failure count and has no speedup.', '']
    if suite == 'constructed-overlap':
        lines += [result['methodology']['constructed_test_threads'], '']
    source = 'ty-worktree' if suite == 'ty-session' else suite
    lines += [f'Source: [{source}.json]({source}.json).', '']
lines += ['## Observed execution', '',
          'The JSON report separates timed commands from warmups and retains all three configurations. '
          'Early test output means Cargo printed a test launch before its first test-build completion '
          'message. Sampled concurrency requires a matching test executable and a compiler outside '
          'test process trees in the same observation. The original process monitor misses Ohm’s '
          'private executable paths; those entries are marked “not covered.” The supplemental '
          'parser-edit run records all owned executables. Two-second sampling can still miss short '
          'overlap, so zero samples do not establish its absence.', '',
          result['methodology']['log_analysis'], '',
          '| Workload | Phase | Commands | Early test output | Sampled compiler/test concurrency |',
          '| --- | --- | ---: | ---: | ---: |']
for row in activation:
    if row['toolchain'] == 'ohm-ready-tests':
        concurrency = ('not covered' if row['commands_with_uncovered_test_executables']
                       else str(row['sampled_compiler_test_concurrency']))
        lines.append(f"| {row['suite']} / {row['project']} | {row['phase']} | {row['commands']} | "
                     f"{row['early_test_output']} | {concurrency} |")
lines += ['', '## Retained APFS space', '',
          'Each entry is one completed allocation cohort. These are retained-space measurements.', '',
          '| Workload | Overlap off | Overlap on | Space saved |', '| --- | ---: | ---: | ---: |']
for row in result['disk_comparisons']:
    lines.append(f"| {row['project']} / {row['cohort']} | {row['default_bytes']/1024**3:.2f} GiB | "
                 f"{row['ready_tests_bytes']/1024**3:.2f} GiB | {row['ready_tests_percent_saved']:+.1f}% |")
lines += ['', 'Source: [disk-ready-tests.json](disk-ready-tests.json).', '', '## Scope', '',
          'The constructed workspace workload explicitly selects multiple library-test executables. '
          'The parser-edit comparison uses the existing feature-ablation fixture. Neither is presented '
          'as an additional recorded developer session.', '',
          result['methodology']['worktree_scope'], '',
          'Cache and trust settings follow each suite’s existing method. The individual-command suite '
          'sets neither trust override; generic replays enable procedural-macro trust; developer '
          'workflows, ty, and disk cohorts enable both trust options. Only the ready-tests option changes '
          'within each Ohm pair.', '',
          'See [the machine-readable comparison](ready-tests.json) and the linked source reports for '
          'individual measurements and archived evidence.', '']
(args.output / 'ready-tests.md').write_text('\n'.join(lines))
print(json.dumps({'comparisons': len(comparisons), 'activation_groups': len(activation)}))
