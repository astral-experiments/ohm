"""Recompute the twelve paired results from the archived per-process instruction counts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent

def main():
    for line in (HERE / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        with (HERE / name).open('rb') as f:
            assert hashlib.file_digest(f, 'sha256').hexdigest() == expected, name
    with tempfile.TemporaryDirectory() as work:
        output = Path(work) / 'paired.json'
        subprocess.run([sys.executable, '-IB', HERE / 'compose_final_counter.py', HERE / 'counts',
                        HERE / 'counts/hosted-decision.json', output], check=True)
        decision = json.loads(output.read_text())
    for phase in ('first-real-edit', 'immediate-repeat'):
        assert decision['endpoints'][phase]['passes']
    guarded = json.loads((HERE / 'final-guarded-cgu-independent-native-readback.json').read_text())
    assert len(guarded['sdk_changes']) == 1 and guarded['sdk_changes'][0].startswith('lib/librustc_driver')
    for role, physical in [('P', (95, 95)), ('C', (2, 1))]:
        compiles = guarded['profile'][role]
        assert [compiles[p]['LLVM_units'] for p in ('edit', 'repeat-1')] == list(physical)
        assert all(compiles[p]['total'] == 95 for p in ('edit', 'repeat-1'))
    print('Verified 12 paired blocks, all four monitored processes per command, and both LLVM-unit counts.')

if __name__ == '__main__':
    main()
