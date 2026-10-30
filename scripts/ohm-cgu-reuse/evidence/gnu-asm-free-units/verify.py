"""Recompute the twelve paired results from the archived per-process instruction counts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
RERUN = HERE / 'source-rerun-41102102686'


def verify_cohort(directory, qa):
    with tempfile.TemporaryDirectory() as work:
        output = Path(work) / 'paired.json'
        subprocess.run([sys.executable, '-IB', HERE / 'compose_final_counter.py', directory / 'counts',
                        directory / 'counts/hosted-decision.json', output, '--qa', qa], check=True)
        decision = json.loads(output.read_text())
    assert all(decision['endpoints'][phase]['passes'] for phase in ('first-real-edit', 'immediate-repeat'))
    return {json.loads(path.read_text())['artifact']
            for path in (directory / 'counts').glob('*.json') if path.name != 'hosted-decision.json'}

def main():
    for line in (HERE / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        with (HERE / name).open('rb') as f:
            assert hashlib.file_digest(f, 'sha256').hexdigest() == expected, name
    first = verify_cohort(HERE, '1f5a25f23bdfabafc1fb2a0b06d33e7095b14115')
    second = verify_cohort(RERUN, '09d6e06d339b23e8785530f22e531fc0e96959ec')
    assert len(first) == len(second) == 13 and first.isdisjoint(second)
    original, rebuilt = [json.loads((directory / 'final-source-built-sdk-manifests.json').read_text())
                         for directory in (HERE, RERUN)]
    assert original['artifact'] != rebuilt['artifact']
    assert original['sdk_file_inventories'] == rebuilt['sdk_file_inventories']
    assert original['changed'] == rebuilt['changed']
    guarded = json.loads((HERE / 'final-guarded-cgu-independent-native-readback.json').read_text())
    assert len(guarded['sdk_changes']) == 1 and guarded['sdk_changes'][0].startswith('lib/librustc_driver')
    for role, physical in [('P', (95, 95)), ('C', (2, 1))]:
        compiles = guarded['profile'][role]
        assert [compiles[p]['LLVM_units'] for p in ('edit', 'repeat-1')] == list(physical)
        assert all(compiles[p]['total'] == 95 for p in ('edit', 'repeat-1'))
    print('Verified two separate 12-pair cohorts, all four monitored processes, both toolchain inventories and the LLVM-unit counts.')

if __name__ == '__main__':
    main()
