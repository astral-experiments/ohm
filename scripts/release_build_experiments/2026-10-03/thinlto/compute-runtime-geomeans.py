"""Compute paired runtime ratios and seeded percentile-bootstrap intervals."""
import json
import math
from pathlib import Path
import random
import statistics
import sys

source = json.loads(Path(sys.argv[1]).read_text())
rows = [r for r in source['runtime_samples'] if isinstance(r['index'], int)]
output = {}
for key in sorted({(r['repo'], r['workload']) for r in rows}):
    group = [r for r in rows if (r['repo'], r['workload']) == key]
    output['-'.join(key)] = {}
    for baseline in ['off', 'fat']:
        ratios = []
        for index in range(1, 21):
            control = next(r for r in group if r['index'] == index and r['variant'] == baseline)
            candidate = next(r for r in group if r['index'] == index and r['variant'] == 'on')
            ratios.append(candidate['elapsed_s'] / control['elapsed_s'])
        # Restart seed 0 for each comparison. Resample complete paired log ratios.
        rng = random.Random(0)
        logs = list(map(math.log, ratios))
        bootstrap = sorted(
            math.exp(sum(rng.choices(logs, k=20)) / 20) for _ in range(20000)
        )
        output['-'.join(key)]['on_over_' + baseline] = {
            'geomean': statistics.geometric_mean(ratios),
            # Zero-based empirical order statistics; no interpolated quantile.
            'paired_bootstrap_95_percent': [bootstrap[500], bootstrap[19499]],
            'ratios': ratios,
        }
Path(sys.argv[2]).write_text(json.dumps(output, indent=2) + '\n')
