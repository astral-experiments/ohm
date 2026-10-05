#!/usr/bin/env python3
"""Independently audit the complete shipping matrix and produce paired decisions.

Run with the downloaded shipping receipts root and an output JSON path. This
reads recorded files only and never invokes a compiler or mutates evidence.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import statistics

PROJECTS = ('uv', 'ruff')
MODES = ('baseline', 'standard', 'compact-raw', 'compact-archive')
SEQUENCE = [('clean', 0, 0, 0), ('noop', 0, 0, 0)]
SEQUENCE += [('direct-edit', n, 0, 0) for n in range(1, 4)]
SEQUENCE += [('restore', 0, 0, 0)]
SEQUENCE += [('library-edit', 0, n, 0) for n in range(1, 4)]
SEQUENCE += [('inline-edit', 0, 3, n) for n in range(1, 4)]
SEQUENCE += [('noop-final', 0, 3, 3)]
PAIRINGS = (('baseline', 'standard'), ('standard', 'compact-raw'),
            ('standard', 'compact-archive'), ('baseline', 'compact-archive'),
            ('compact-raw', 'compact-archive'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ident(row):
    return (row['project'], row['round'], row['phase'], row['direct_value'],
            row['library_value'], row['inline_value'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('receipts', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = args.receipts / 'evidence'
    matrix = evidence / 'line-matrix'
    count = 0

    def check(test, context):
        nonlocal count
        count += 1
        if not test:
            raise AssertionError(context)

    def equal_number(a, b, context):
        check(math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9), (context, a, b))

    manifest = json.loads((evidence / 'benchmark-transfer-manifest.json').read_text())
    for relative, record in manifest['files'].items():
        file = args.receipts / relative
        check(file.is_file() and not file.is_symlink(), relative)
        check(file.stat().st_size == record['bytes'], ('size', relative))
        check(sha(file) == record['sha256'], ('digest', relative))
    inventory = set()
    for relative in manifest['paths']:
        path = args.receipts / relative
        for file in path.rglob('*') if path.is_dir() else [path]:
            if file.is_file():
                inventory.add(str(file.relative_to(args.receipts)))
    check(inventory == set(manifest['files']), 'complete transferred path inventory')
    status = json.loads((matrix / 'status.json').read_text())
    check(status['status'] == 'completed' and status['samples'] == 312, status)
    rows = [json.loads(line) for line in (matrix / 'samples.jsonl').read_text().splitlines()]
    check(len(rows) == 312, ('rows', len(rows)))
    expected = {(p, m, r, *s) for p, m, r, s in itertools.product(PROJECTS, MODES, range(3), SEQUENCE)}
    actual = [(r['project'], r['mode'], r['round'], r['phase'], r['direct_value'], r['library_value'], r['inline_value']) for r in rows]
    check(len(set(actual)) == 312 and set(actual) == expected, 'full unique factorial matrix')
    preflight = json.loads((evidence / 'benchmark-preflight.json').read_text())
    check(preflight['no_outside_compiler_at_launch'], 'preflight process gate')
    check(all(v is None for v in preflight['logger_environment'].values()), 'logger absence')
    check('RUSTC_LOG' in preflight['logger_environment'], 'logger receipt scope')
    check(preflight['argv'] == json.loads((args.receipts / 'control/benchmark-args.json').read_text()), 'preflight exact launcher arguments')
    for name, digest in preflight['correctness_receipt_sha256'].items():
        check(sha(evidence / (name + '.json')) == digest, ('tested admission receipt', name))
    check(preflight['harness_sha256']['harness/benchmark_shipping.py'] == 'cb972b8f75c9e89a98e76e7e244a39fb616a6c341129650e3745e73df56faad2', 'frozen shipping wrapper')
    check(preflight['harness_sha256']['harness/summarize_shipping.py'] == '12caf0eb9867f0198db8ff754fccb59bf9886e6f425001ba244e5a7bc2f251eb', 'frozen shipping summarizer')
    provenance = json.loads((matrix / 'provenance.json').read_text())
    check(provenance['script_sha256'] == 'ea7867f9f9a0f19ceb7d9c558aa7aa6758ae3e254878685fbc58768c65713cef', 'frozen core')
    settings = provenance['settings']
    check(settings['rounds'] == 3 and settings['edits'] == 3 and settings['jobs'] == 8, 'matrix settings')
    check(settings['profile'] == 'line' and not settings['online'] and not settings['sample_disk'], 'accepted profile')
    check(settings['modes'] == list(MODES) and settings['projects'] == list(PROJECTS), 'matrix modes/projects')
    for name in ('baseline', 'candidate'):
        toolchain = provenance['toolchains'][name]
        expected_wild = provenance['baseline_wild' if name == 'baseline' else 'wild']['sha256']
        check(toolchain['bundled_wild_sha256'] == expected_wild, ('bundled linker', name))
    baseline_drivers = set(provenance['toolchains']['baseline']['driver_sha256'].values())
    candidate_drivers = set(provenance['toolchains']['candidate']['driver_sha256'].values())
    check(len(baseline_drivers) == len(candidate_drivers) == 1 and baseline_drivers.isdisjoint(candidate_drivers), 'distinct matched compiler bytes')
    compiler_receipt = json.loads((evidence / 'compiler-shipping-final.json').read_text())
    check(compiler_receipt['passed'] and compiler_receipt['sources'] == preflight['sources'], 'compiled shipping source pins')
    for name, head in preflight['sources'].items():
        check((evidence / f'shipping-build-provenance/{name}-head.txt').read_text().strip() == head, ('unchanged remote source head', name))
        check(not (evidence / f'shipping-build-provenance/{name}-status.txt').read_text().strip(), ('clean remote source worktree', name))
    check(candidate_drivers == set(compiler_receipt['drivers'].values()), 'measured compiler is validated distribution driver')
    check(provenance['wild']['sha256'] == compiler_receipt['wild_sha256'], 'measured fork Wild is validated distribution linker')
    check(compiler_receipt['production_pgo_bolt'] is False, 'explicit non-PGO/BOLT compiler scope')
    baseline_receipt = json.loads((evidence / 'shipping-build-provenance/baseline-driver-match.json').read_text())
    check(baseline_drivers == set(baseline_receipt['drivers'].values()), 'measured baseline is original matched compiler driver')
    check(baseline_receipt['source_base'] == '348339ddae4288ebb3af97d204b19479fef8f5f2', 'pinned baseline source')
    check((evidence / 'shipping-build-provenance/baseline-bootstrap.toml').read_bytes() == (evidence / 'shipping-build-provenance/candidate-bootstrap.toml').read_bytes(), 'byte-identical matched compiler build configurations')
    check('018a2b934' in provenance['cargo']['version']['stdout'], 'one installed Cargo control across modes')
    check(settings['compression_profile'] == 'fast', 'frozen compression profile')
    plans = {(c['project'], c['mode'], c['round']): c for c in provenance['plan']}
    check(len(plans) == 24, '24 fresh cells')
    for key, cell in plans.items():
        env = cell['env']; mode = cell['mode']
        check(env['CARGO_INCREMENTAL'] == '1' and env['CARGO_PROFILE_DEV_DEBUG'] == 'line-tables-only', ('profile', key))
        check(env['RUSTC'] == settings['baseline' if mode == 'baseline' else 'candidate'] + '/bin/rustc', ('compiler', key))
        check(env['CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST'] == 'all' and env['CARGO_UNSTABLE_OHM_NATIVE_TOOL_TRUST'] == 'all', ('trust', key))
        check(env.get('CARGO_PROFILE_DEV_OPT_LEVEL') == ('1' if key[0] == 'ruff' else None), ('optimization profile', key))
        check(env.get('CARGO_UNSTABLE_EMBED_METADATA') == ('true' if mode == 'compact-archive' else None), ('full metadata control', key))
        check(env['CARGO_ENCODED_RUSTFLAGS'] == '\x1f'.join(cell['flags']), ('flags', key))
        expected_flags = [] if mode == 'baseline' else ['-Zcompress-incremental=no', '-Zartifact-compression-profile=fast']
        if mode == 'compact-raw':
            expected_flags += ['-Zcompact-artifact-store=' + cell['lane'] + '/store', '-Zcompact-artifact-raw-metadata=yes']
        elif mode == 'compact-archive':
            expected_flags += ['-Zcompact-artifacts=yes']
        check(cell['flags'] == expected_flags, ('exact arm controls', key))
        check(all(str(Path(env[n])).startswith(cell['lane'] + '/') for n in ('CARGO_TARGET_DIR', 'CARGO_BUILD_BUILD_DIR', 'TMPDIR')), ('whole lane accounting', key))

    grouped = defaultdict(list)
    format_counts = {}; relinks = []; interference = []
    for row in rows:
        key = (row['project'], row['mode'], row['round'])
        grouped[key].append(row)
        context = key + (row['phase'], row['direct_value'], row['library_value'], row['inline_value'])
        check(row['accepted'] and row['returncode'] == 0 and row['oracle']['passed'], ('accepted', context))
        check(not row['unrelated_compilers'] and len(row['outside_cpu_intervals']) < 3, ('interference gate', context))
        check(not row['disk_reserve_failed'] and not row['instrumented_disk'] and row['sampled_peak_allocated_bytes'] is None, ('uninstrumented', context))
        check(row['flags'] == plans[key]['flags'], ('cell flags', context))
        check(row['wall_seconds'] > 0 and row['user_seconds'] >= 0 and row['system_seconds'] >= 0, ('time', context))
        check('--offline' in row['argv'] and '-vv' in row['argv'] and '--locked' in row['argv'], ('cargo controls', context))
        original = Path(row['log'])
        local = matrix / original.parent.name / original.name
        monitor = json.loads(local.with_suffix('.monitor.json').read_text())
        check(row['sampled_process_tree_peak_rss_bytes'] == max(x['rss'] for x in monitor), ('recorded tree RSS peak', context))
        resources = local.with_suffix('.time').read_text()
        for label, field, multiplier in (('User time (seconds)', 'user_seconds', 1),
                                          ('System time (seconds)', 'system_seconds', 1),
                                          ('Maximum resident set size (kbytes)', 'max_child_rss_bytes', 1024)):
            match = re.search(r'^\s*' + re.escape(label) + r':\s*(\S+)', resources, re.M)
            check(match is not None and float(match[1]) * multiplier == row[field], ('GNU time resource receipt', context, field))
        oracle = json.loads(local.with_suffix('.oracle.json').read_text())
        check(oracle == row['oracle'], ('oracle receipt', context))
        expected_value = row['direct_value'] + row['library_value'] + row['inline_value']
        check(oracle['expected_probe'] == expected_value and oracle['probe_stdout'].strip() == str(expected_value), ('semantic value', context))
        check(oracle['probe_returncode'] == 0 and oracle['version']['returncode'] == 0 and oracle['help']['returncode'] == 0, ('runtime', context))
        census = row['census']
        for field in ('allocated', 'logical'):
            check(census[field] == sum(c[field] for c in census['categories'].values()), ('census category sum', context, field))
        check(census['files'] + census['directories'] == sum(c['entries'] for c in census['categories'].values()), ('census entries', context))
        store = census['categories'].get('compact-store', {}).get('allocated', 0)
        check((store > 0) == (row['mode'] == 'compact-raw'), ('store counted only external arm', context))
        if row['outside_cpu_intervals']:
            positions = []
            for spike in row['outside_cpu_intervals']:
                i = min(range(len(monitor)), key=lambda i: abs(monitor[i]['time'] - spike['time']))
                equal_number(spike['cores'], monitor[i]['outside_user_cpu_cores'], ('outside CPU recorded sample', context))
                positions.append({'index': i, 'samples': len(monitor), 'terminal': i == len(monitor)-1,
                                  'processes': monitor[i]['processes'], 'rss': monitor[i]['rss']})
            interference.append({'cell': key, 'phase': row['phase'], 'direct_value': row['direct_value'],
                                 'library_value': row['library_value'], 'inline_value': row['inline_value'],
                                 'intervals': row['outside_cpu_intervals'], 'sample_positions': positions})
        if row['phase'] == 'clean':
            fmt = row['formats']; check(fmt['passed'], ('format gate', key))
            check(fmt['metadata_formats']['raw'] > 0 and fmt['metadata_formats']['packed'] == 0 and fmt['metadata_formats']['other'] == 0, ('ordinary metadata', key))
            if row['mode'] == 'compact-archive':
                check(fmt['archive_member_formats']['compact'] > 0 and not fmt['counts'].get('manifest', 0) and not fmt['counts'].get('wrapper', 0), ('self-contained ar', key))
            elif row['mode'] == 'compact-raw':
                check(fmt['counts'].get('manifest', 0) > 0 and fmt['counts'].get('object', 0) > 0 and not fmt['counts'].get('wrapper', 0), ('manifest objects', key))
            else:
                check(fmt['archive_member_formats']['compact'] == 0 and not any(fmt['counts'].get(k, 0) for k in ('object', 'manifest', 'wrapper')), ('ordinary formats', key))
            format_counts['/'.join(map(str, key))] = fmt
        if row['phase'] in ('direct-edit', 'library-edit', 'inline-edit'):
            commands = []
            for line in local.read_text(errors='replace').splitlines():
                if 'Running `' not in line or '/bin/rustc ' not in line:
                    continue
                def field(flag):
                    match = re.search(r'(?:^|\s)' + re.escape(flag) + r'\s+(\S+)', line)
                    return match[1] if match else None
                commands.append({'crate': field('--crate-name'), 'kind': field('--crate-type'), 'link_only': bool(re.search(r'-Z(?:\s+|=)?link-only\b', line))})
            selected = [c for c in commands if c['crate'] == row['project']]
            bins = [c for c in selected if c['kind'] == 'bin']; libs = [c for c in selected if c['kind'] == 'lib']
            check(len(bins) == 1 and len(libs) == (row['phase'] != 'direct-edit'), ('edit compiler scope', context, selected))
            check(bins[0]['link_only'] == (row['phase'] == 'library-edit'), ('edit relink semantics', context, bins))
            relinks.append({'cell': key, 'phase': row['phase'], 'log_sha256': sha(local), 'commands': selected})
    for key, cell in grouped.items():
        check([(r['phase'], r['direct_value'], r['library_value'], r['inline_value']) for r in cell] == SEQUENCE, ('cell history', key))
        for i in (1, 12):
            check(not cell[i]['compiler_crates'] and cell[i]['oracle']['sha256'] == cell[i-1]['oracle']['sha256'], ('no-op identity', key, i))

    summary = json.loads((matrix / 'shipping-summary.json').read_text())
    check(summary['accepted_samples'] == 312 and summary['excluded_samples'] == 0 and summary['total_samples'] == 312, 'summary totals')
    check(len(summary['comparisons']) == 70 and len(summary['storage']) == 20, 'five pairings, two projects, seven phases')
    def summary_key(group):
        return (group['reference'], group['candidate'], group['project'], group['phase'])
    expected_comparisons = {(a, b, p, phase) for (a, b), p, phase in itertools.product(PAIRINGS, PROJECTS, {s[0] for s in SEQUENCE})}
    expected_storage = {(a, b, p, phase) for (a, b), p, phase in itertools.product(PAIRINGS, PROJECTS, ('clean', 'noop-final'))}
    check({summary_key(g) for g in summary['comparisons']} == expected_comparisons, 'every unique summary comparison')
    check({summary_key(g) for g in summary['storage']} == expected_storage, 'every unique storage comparison')
    index = {(r['mode'], ident(r)): r for r in rows}

    def raw_pairs(reference, candidate, project, phase, round_index=None):
        return [(a, index[(candidate, ident(a))]) for a in rows if a['mode'] == reference and a['project'] == project and a['phase'] == phase and (round_index is None or a['round'] == round_index)]

    metrics = {'wall_seconds': lambda r: r['wall_seconds'], 'cpu_seconds': lambda r: r['user_seconds'] + r['system_seconds'], 'sampled_tree_rss_bytes': lambda r: r['sampled_process_tree_peak_rss_bytes'], 'allocated_bytes': lambda r: r['census']['allocated'], 'logical_bytes': lambda r: r['census']['logical']}

    def compare(pairs, metric):
        left, right = ([metric(a) for a, b in pairs], [metric(b) for a, b in pairs])
        percentages = [100*(b/a-1) for a, b in zip(left, right)]
        return {'reference_mean': sum(left)/len(left), 'candidate_mean': sum(right)/len(right), 'delta_mean': sum(b-a for a,b in zip(left,right))/len(left), 'ratio_of_means_percent': 100*(sum(right)/sum(left)-1), 'paired_percent_median': statistics.median(percentages), 'paired_percent_range': [min(percentages), max(percentages)], 'increased_pairs': sum(b>a for a,b in zip(left,right))}

    def verify_metrics(actual, wanted, context):
        check(set(actual) == set(wanted), ('metric fields', context))
        for field, value in wanted.items():
            if isinstance(value, list):
                for a,b in zip(actual[field],value):equal_number(a,b,(context,field))
            else:equal_number(actual[field],value,(context,field))

    for group in summary['comparisons']:
        pairs = raw_pairs(group['reference'], group['candidate'], group['project'], group['phase'])
        check(group['n'] == len(pairs) == (9 if group['phase'].endswith('-edit') else 3), ('pair count',group['project'],group['phase']))
        for metric in ('wall_seconds','cpu_seconds','sampled_tree_rss_bytes'):
            verify_metrics(group[metric],compare(pairs,metrics[metric]),(group['project'],group['phase'],metric))
        check(len(group['rounds']) == 3, 'three round summaries')
        check({r['round'] for r in group['rounds']} == {0, 1, 2}, 'every fresh round')
        for round_result in group['rounds']:
            subset = [(a,b) for a,b in pairs if a['round'] == round_result['round']]
            check(round_result['n'] == len(subset), 'round size')
            verify_metrics(round_result['wall_seconds'],compare(subset,metrics['wall_seconds']),'per-round wall')
    for group in summary['storage']:
        pairs=raw_pairs(group['reference'],group['candidate'],group['project'],group['phase'])
        check(group['n'] == len(pairs) == 3,'storage fresh rounds')
        for metric in ('allocated_bytes','logical_bytes'):
            verify_metrics(group[metric],compare(pairs,metrics[metric]),'storage '+metric)
    baseline_raw = []
    for project,phase in itertools.product(PROJECTS, ('clean','direct-edit','library-edit','inline-edit','noop-final')):
        pairs=raw_pairs('baseline','compact-raw',project,phase)
        baseline_raw.append({'project':project,'phase':phase,'reference':'baseline','candidate':'compact-raw','n':len(pairs),'wall_seconds':compare(pairs,metrics['wall_seconds']),'allocated_bytes':compare(pairs,metrics['allocated_bytes']),'rounds':[{'round':i,'wall_seconds':compare([(a,b) for a,b in pairs if a['round']==i],metrics['wall_seconds'])} for i in range(3)]})
    result={'passed':True,'checks':count,'matrix_sha256':sha(matrix/'samples.jsonl'),'transfer_verified_files':len(manifest['files']),'transfer_verified_bytes':sum(x['bytes'] for x in manifest['files'].values()),'commands':312,'fresh_cells':24,'runtime_oracles':312,'format_cells':24,'no_op_checks':48,'edit_log_checks':len(relinks),'source_heads':preflight['sources'],'additional_baseline_raw_comparisons':baseline_raw,'outside_cpu_flags':interference,'relink_checks':relinks,'format_checks':format_counts,'scope':'Nine sequential edit observations are grouped in three independent fresh-target rounds. Tree RSS is summed process RSS, not PSS. Allocated bytes deduplicate ext4 inodes across the entire lane, including store/build/target/scratch; they are post-command allocation, not peak disk or CoW unique extents. No retrospective exclusions or runtime/harness changes.'}
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('additional_baseline_raw_comparisons','outside_cpu_flags','relink_checks','format_checks')},indent=2))


if __name__ == '__main__':
    main()
