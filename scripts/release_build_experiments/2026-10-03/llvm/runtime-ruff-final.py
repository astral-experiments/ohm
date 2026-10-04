#!/usr/bin/env python3
"""Compare Ruff CLI correctness and throughput on a pinned CPython corpus."""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

root = Path('/tmp/ohm-release-campaign/llvm')
output = root / 'evidence/runtime-ruff-final'
output.mkdir(exist_ok=True)
variants = ['baseline', 'merge']
corpus = root / 'cpython/Lib'
commands = {
    'check': ['check', '--isolated', '--no-cache', '--exit-zero', '--output-format', 'concise', str(corpus)],
    'format-check': ['format', '--isolated', '--no-cache', '--check', str(corpus)],
}
results = []
for workload, arguments in commands.items():
    # Warm filesystem state once for every executable before counterbalancing.
    for variant in variants:
        result = subprocess.run([str(root / f'evidence/binaries/{variant}-ruff'), *arguments], cwd=root / 'cpython', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert result.stdout, (workload, variant, result.stderr.decode(errors='replace'))
        if workload == 'check':
            assert result.returncode == 0, result.stderr.decode(errors='replace')
        for stream in ['stdout', 'stderr']:
            (output / f'{workload}-{variant}.{stream}').write_bytes(getattr(result, stream))
    for repetition in range(24):
        order = variants if repetition % 2 == 0 else list(reversed(variants))
        for variant in order:
            started = time.perf_counter()
            result = subprocess.run([str(root / f'evidence/binaries/{variant}-ruff'), *arguments], cwd=root / 'cpython', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            wall = time.perf_counter() - started
            row = {'workload': workload, 'variant': variant, 'repetition': repetition, 'wall_seconds': wall, 'returncode': result.returncode,
                'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(), 'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()}
            # Two independent warnings are emitted by parallel lint workers.
            # Retain each raw stream and compare the full warning-line multiset.
            for stream in ['stdout', 'stderr']:
                (output / f'{workload}-{repetition}-{variant}.{stream}').write_bytes(getattr(result, stream))
            if workload == 'check':
                expected = [b'warning: Docstring at Lib/test/test_getpath.py:390:9 contains implicit string concatenation; ignoring...', b'warning: Unexpected `# ruff: noqa` directive at Lib/test/test_with.py:177. File-level suppression comments must appear on their own line. For line-level suppression, omit the `ruff:` prefix.']
                assert sorted(result.stderr.splitlines()) == sorted(expected)
            else:
                assert result.stderr == b''
            row['stderr_normalized_sha256'] = hashlib.sha256(b'\n'.join(sorted(result.stderr.splitlines()))).hexdigest()
            results.append(row)
            (output / 'samples.json').write_text(json.dumps(results, indent=2) + '\n')
for workload in commands:
    rows = [r for r in results if r['workload'] == workload]
    assert len({(r['returncode'], r['stdout_sha256'], r['stderr_normalized_sha256']) for r in rows}) == 1, f'{workload} output mismatch'
    print(workload, {v: statistics.median(r['wall_seconds'] for r in rows if r['variant'] == v) for v in variants}, flush=True)
