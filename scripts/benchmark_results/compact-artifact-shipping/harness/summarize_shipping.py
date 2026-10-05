#!/usr/bin/env python3
"""Summarize matched shipping-candidate timings and whole-lane storage."""
import argparse
import json
from pathlib import Path
import statistics as stats


PAIRS = (
    ('baseline', 'standard'),
    ('standard', 'compact-raw'),
    ('standard', 'compact-archive'),
    ('baseline', 'compact-archive'),
    ('compact-raw', 'compact-archive'),
)


def identity(row):
    return tuple(row[k] for k in (
        'project', 'round', 'phase', 'direct_value', 'library_value', 'inline_value'
    ))


def compare(pairs, metric):
    reference = [metric(a) for a, b in pairs]
    candidate = [metric(b) for a, b in pairs]
    deltas = [b - a for a, b in zip(reference, candidate)]
    ratios = [100 * (b / a - 1) for a, b in zip(reference, candidate) if a]
    reference_mean, candidate_mean = stats.mean(reference), stats.mean(candidate)
    return {
        'reference_mean': reference_mean,
        'candidate_mean': candidate_mean,
        'delta_mean': stats.mean(deltas),
        'ratio_of_means_percent': 100 * (candidate_mean / reference_mean - 1) if reference_mean else None,
        'paired_percent_median': stats.median(ratios) if ratios else None,
        'paired_percent_range': [min(ratios), max(ratios)] if ratios else None,
        'increased_pairs': sum(value > 0 for value in deltas),
    }


def summarize(root):
    rows = [json.loads(line) for line in (root / 'samples.jsonl').read_text().splitlines()]
    status = json.loads((root / 'status.json').read_text()) if (root / 'status.json').exists() else {'status': 'incomplete'}
    identities = [(r['mode'], identity(r)) for r in rows]
    assert len(identities) == len(set(identities)), 'duplicate measurements'
    accepted = [r for r in rows if r['accepted']]
    for row in accepted:
        assert row['returncode'] == 0 and row['oracle']['passed']
        assert not row['unrelated_compilers'] and len(row['outside_cpu_intervals']) < 3
        assert row.get('formats', {'passed': True})['passed']
        if row['mode'] == 'compact-archive':
            assert not row['census']['categories'].get('compact-store', {}).get('allocated', 0)
    result = {
        'source': str(root), 'status': status,
        'total_samples': len(rows), 'accepted_samples': len(accepted),
        'excluded_samples': len(rows) - len(accepted),
        'comparisons': [], 'storage': [],
    }
    for reference, candidate in PAIRS:
        refs = {identity(r): r for r in accepted if r['mode'] == reference}
        candidates = {identity(r): r for r in accepted if r['mode'] == candidate}
        keys = refs.keys() & candidates.keys()
        for project, phase in sorted({(key[0], key[2]) for key in keys}):
            pairs = [(refs[key], candidates[key]) for key in sorted(keys) if (key[0], key[2]) == (project, phase)]
            item = {
                'project': project, 'phase': phase,
                'reference': reference, 'candidate': candidate, 'n': len(pairs),
                'wall_seconds': compare(pairs, lambda r: r['wall_seconds']),
                'cpu_seconds': compare(pairs, lambda r: r['user_seconds'] + r['system_seconds']),
                'sampled_tree_rss_bytes': compare(pairs, lambda r: r['sampled_process_tree_peak_rss_bytes']),
                'rounds': [],
            }
            # Sequential edits within a round share a cache history. Expose round
            # means rather than treating every edit as an independent experiment.
            for index in sorted({a['round'] for a, b in pairs}):
                subset = [(a, b) for a, b in pairs if a['round'] == index]
                item['rounds'].append({'round': index, 'n': len(subset),
                                       'wall_seconds': compare(subset, lambda r: r['wall_seconds'])})
            result['comparisons'].append(item)
            if phase in ('clean', 'noop-final'):
                result['storage'].append({
                    'project': project, 'phase': phase,
                    'reference': reference, 'candidate': candidate, 'n': len(pairs),
                    'allocated_bytes': compare(pairs, lambda r: r['census']['allocated']),
                    'logical_bytes': compare(pairs, lambda r: r['census']['logical']),
                })
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    text = json.dumps(summarize(args.run), indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
