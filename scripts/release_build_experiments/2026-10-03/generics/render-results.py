#!/usr/bin/env python3
"""Render the per-host paired results without pooling different machines."""
import argparse,json,pathlib
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('summary',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args();data=json.loads(args.summary.read_text())
lines=['# Measured generic-sharing results','', 'Times are wall-clock seconds. Each off/on pair uses the same Cargo executable on the same host, with default concurrency. Off disables the prototype; on enables `-Zohm-lto-share-generics`. Every numeric row below has completed successfully without observed foreign compiler activity or Cargo lock waits. Incomplete stages remain in the machine-readable summary and are omitted from this table.','', '| Workload | Host | LTO | Pair / order | Stage | Off (s) | On (s) | Change |', '|---|---|---|---|---|---:|---:|---:|']
for row in data['pairs']:
    if row['cohort']!='policy' or row['rejection_reasons']:continue
    lines.append(f"| {row['name']} | {row['host']} | {row['lto']} | {row['pair']} / {row['order']} | {row['kind']} | {row['baseline_seconds']:.3f} | {row['candidate_seconds']:.3f} | {(row['candidate_over_baseline']-1)*100:+.2f}% |")
lines += ['', '## Cold executable size', '', '| Workload | Host | LTO | Pair | Off (bytes) | On (bytes) | Change |', '|---|---|---|---|---:|---:|---:|']
for pair in data['pairs']:
    if pair['cohort']!='policy' or pair['kind']!='cold' or pair['rejection_reasons']:continue
    rows={r['variant']:r for r in data['builds'] if all(r[k]==pair[k] for k in ['host','cohort','name','lto','pair','kind'])}
    a,b=rows['default']['binary_size'],rows['policy']['binary_size']
    lines.append(f"| {pair['name']} | {pair['host']} | {pair['lto']} | {pair['pair']} | {a:,} | {b:,} | {(b/a-1)*100:+.2f}% |")
lines += ['', '## Cold CPU time and memory', '', 'GNU time user and system CPU seconds include work charged to the command and its children. Maximum RSS is the process/child high-water figure, not aggregate concurrent compiler memory.', '', '| Program | Host | LTO / pair | Off CPU s (user + sys) | On CPU s (user + sys) | Off / on max RSS (KiB) |', '|---|---|---|---:|---:|---:|']
for pair in data['pairs']:
    if pair['cohort']!='policy' or pair['kind']!='cold' or pair['rejection_reasons']:continue
    rows={r['variant']:r for r in data['builds'] if all(r[k]==pair[k] for k in ['host','cohort','name','lto','pair','kind'])}
    a,b=rows['default']['gnu_time'],rows['policy']['gnu_time']
    if not a or not b:continue
    lines.append(f"| {pair['name']} | {pair['host']} | {pair['lto']} / {pair['pair']} | {a['user_seconds']:.2f} + {a['system_seconds']:.2f} | {b['user_seconds']:.2f} + {b['system_seconds']:.2f} | {a['maximum_rss_kib']:,} / {b['maximum_rss_kib']:,} |")
lines += ['', '## Runtime', '', 'Only cohorts passing the post hoc exit-code, stdout, and diagnostic audit appear below. Each uses 30 randomized pairs after three warmups per executable and workload. The interval bootstraps paired ratios; it describes this corpus and host, not all production use.', '', '| Program | Host | LTO | Workload | Pairs | On/off geomean | 95% interval |', '|---|---|---|---|---:|---:|---|']
for row in data['runtime_aggregates']:
    low,high=row['bootstrap_95_percent_interval']
    lines.append(f"| {row['name']} | {row['host']} | {row['lto']} | {row['workload']} | {row['n']} | {row['geomean']:.4f} | {low:.4f}–{high:.4f} |")
if not data['runtime_aggregates']:lines += ['', 'Runtime cohorts are pending; no runtime conclusion yet.']
lines += ['', '## Exploratory global-flag screen', '', 'These rows use the released Cargo and globally inject `-Zshare-generics=yes`. They are separate from the actual policy above.', '', '| Workload | Host | Stage | Off (s) | Global flag (s) | Change |', '|---|---|---|---:|---:|---:|']
for row in data['pairs']:
    if row['cohort']!='global-screen' or row['rejection_reasons']:continue
    lines.append(f"| {row['name']} | {row['host']} | {row['kind']} | {row['baseline_seconds']:.3f} | {row['candidate_seconds']:.3f} | {(row['candidate_over_baseline']-1)*100:+.2f}% |")
lines += ['', 'The uv global candidate was skipped before launch after the Ruff regression so compute could measure the scoped Cargo policy. Its completed baseline remains in the raw evidence.', '', '## Conditions and scope', '']
lines += ['- '+limit for limit in data['limitations']]
lines += ['- Fat-LTO uv confirmations run on three separate hosts; ratios are reported per host. Ruff uses counterbalanced within-host pairs. ThinLTO is a single-pair exploratory profile screen.', '- Rejected idle preflights are retained. Resumes preserve completed samples, original checkpoints, and stage-specific runner hashes; they do not rerun or replace successful timings.', '- Raw compiler/process logs, Cargo timing reports, and original runtime streams are retained in checksummed host archives. See README.md for pinned inputs and exact reproduction.']
args.output.write_text('\n'.join(lines)+'\n')
