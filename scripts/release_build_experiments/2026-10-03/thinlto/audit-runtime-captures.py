#!/usr/bin/env python3
"""Post hoc strict audit of retained runtime captures; never runs measured binaries."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('runtime', type=Path)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
sha = lambda value: hashlib.sha256(value).hexdigest()
rows = []
for path in sorted(args.runtime.glob('*.json')):
    value = json.loads(path.read_text())
    if isinstance(value, dict) and isinstance(value.get('index'), int) and 'elapsed_s' in value:
        rows.append(value)
assert len(rows) == 240, len(rows)
receipt = {'audit': 'Post hoc audit; measured harness and binaries unchanged', 'workloads': {}, 'captures': []}
for repo, workload in [('uv', 'jupyter'), ('uv', 'trio'), ('ruff', 'cpython'), ('ruff', 'format')]:
    selected = [row for row in rows if row['repo'] == repo and row['workload'] == workload]
    assert len(selected) == 60
    assert Counter(row['variant'] for row in selected) == {'fat': 20, 'off': 20, 'on': 20}
    expected_stdout = expected_stderr = expected_status = expected_warnings = expected_output = None
    for row in selected:
        stem = f"{repo}-{workload}-{row['index']}-{row['variant']}"
        stdout = (args.runtime / (stem + '.stdout')).read_bytes()
        stderr = (args.runtime / (stem + '.stderr')).read_bytes()
        canonical_stdout = stdout
        canonical_stderr = stderr
        if repo == 'uv':
            # Exactly one resolver duration is replaced. Every other byte stays in order.
            lines = stderr.splitlines(keepends=True)
            positions = [i for i, line in enumerate(lines) if line.startswith(b'Resolved ')]
            assert len(positions) == 1, (stem, positions)
            index = positions[0]
            match = re.fullmatch(rb'(Resolved [0-9]+ packages? in )((?:[0-9]+(?:\.[0-9]+)?(?:ms|us|ns|\xc2\xb5s|s|m|h) ?)+)\n', lines[index])
            assert match, (stem, lines[index])
            lines[index] = match[1] + b'<TIME>\n'
            canonical_stderr = b''.join(lines)
            expected_output = expected_output or row['output_sha256']
            assert row['output_sha256'] == expected_output, stem
        elif workload == 'cpython':
            # Validate the exact full warning multiset before sorting warning positions.
            lines = stderr.splitlines(keepends=True)
            positions = [i for i, line in enumerate(lines) if line.startswith(b'warning: ')]
            warnings = Counter(lines[i] for i in positions)
            if expected_warnings is None:
                expected_warnings = warnings
            assert warnings == expected_warnings, (stem, warnings, expected_warnings)
            for i, line in zip(positions, sorted(lines[i] for i in positions)):
                lines[i] = line
            canonical_stderr = b''.join(lines)
        else:
            assert not stderr, (stem, stderr)
            lines = stdout.splitlines(keepends=True)
            positions = [i for i, line in enumerate(lines) if line.startswith(b'Would reformat: ')]
            for i, line in zip(positions, sorted(lines[i] for i in positions)):
                lines[i] = line
            canonical_stdout = b''.join(lines)
        if expected_status is None:
            expected_status = row['exit_code']
            expected_stdout = canonical_stdout
            expected_stderr = canonical_stderr
        assert row['exit_code'] in ([0, 1] if workload == 'format' else [0]), stem
        assert row['exit_code'] == expected_status, stem
        assert canonical_stdout == expected_stdout, (stem, 'stdout')
        assert canonical_stderr == expected_stderr, (stem, 'stderr')
        receipt['captures'].append({'stem': stem, 'exit_code': row['exit_code'], 'raw_stdout_sha256': sha(stdout), 'raw_stderr_sha256': sha(stderr), 'canonical_stdout_sha256': sha(canonical_stdout), 'canonical_stderr_sha256': sha(canonical_stderr), 'output_file_sha256': row['output_sha256'] if repo == 'uv' else None})
    info = {'samples': 60, 'exit_code': expected_status, 'stdout_sha256': sha(expected_stdout), 'stderr_sha256': sha(expected_stderr)}
    if repo == 'uv':
        info.update(normalization='Exactly one anchored Resolved N packages duration; no other byte changes', output_file_sha256=expected_output, stdout_compared_separately=True)
    elif workload == 'cpython':
        info.update(normalization='Only exact warning-line multiset order; every other stderr byte retains its position', warning_multiset=[{'line': line.decode(), 'count': count} for line, count in sorted(expected_warnings.items())])
    else:
        non_path_lines = [line for line in expected_stdout.splitlines(keepends=True) if not line.startswith(b'Would reformat: ')]
        info.update(normalization='Only Would reformat path-line order; every non-path stdout line retains its position', stderr_empty=True, normalized_path_line_count=len(expected_stdout.splitlines())-len(non_path_lines), preserved_non_path_line_count=len(non_path_lines), preserved_non_path_sha256=sha(b''.join(non_path_lines)), preserved_stdout_footer=expected_stdout.splitlines(keepends=True)[-1].decode())
    receipt['workloads'][f'{repo}-{workload}'] = info
args.output.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'captures': len(receipt['captures']), 'workloads': list(receipt['workloads']), 'receipt_sha256_original_bytes': sha(args.output.read_bytes())}))
