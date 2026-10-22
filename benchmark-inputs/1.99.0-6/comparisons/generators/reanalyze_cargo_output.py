"""Recover Cargo messages interleaved with partial libtest output in saved logs."""
import collections
import copy
import hashlib
import json
from pathlib import Path
import re


# Cargo writes an indented status to stderr while libtest may have an unfinished
# stdout line. Preserve the original line-start matches and also accept these
# indented messages after non-whitespace on the same line.
PREFIX = r'(?m)(?:^\s*|(?<=\S)[ \t]{3,})'
STATUS = r'(?P<action>Compiling|Checking)\s+(?P<crate>[^\s]+)'


def reanalyze_report(path):
    original = json.loads(path.read_text())
    report = copy.deepcopy(original)
    evidence = path.parent.parent
    changes = []
    for observation in report.get('overlap_observations', []):
        remote = observation['log']
        suite = remote.split('/release-1.99.0-6/', 1)[1].split('/')[0]
        local = evidence / 'raw' / suite / 'logs' / remote.split('/logs/', 1)[1]
        assert local.resolve().is_relative_to(evidence.resolve())
        data = local.read_bytes()
        receipt = report['provenance']['input_receipt_sha256'][remote]
        digest = hashlib.sha256(data).hexdigest()
        assert digest == receipt['sha256'] and len(data) == receipt['bytes']
        text = data.decode()
        # All archived runs retain the same launch messages with this change.
        # If a new launch were recovered, process matching would also need to
        # be rerun rather than silently retaining the original process counts.
        assert re.findall(r'(?m)^\s*Running ([^\n]+)', text) == re.findall(
            PREFIX + r'Running ([^\n]+)', text)
        finished = [m.start() for m in re.finditer(PREFIX + r'Finished `test` profile', text)]
        corrected = {
            'test_result_before_build_finished': bool(
                finished and re.search(r'test result: ok\.', text[:finished[0]])),
            'running_before_build_finished': bool(
                finished and any(item['offset'] < finished[0]
                                 for item in observation['logged_test_launches'])),
        }
        changed = {}
        for field, value in corrected.items():
            if observation[field] != value:
                changed[field] = {'before': observation[field], 'after': value}
                observation[field] = value
        before = [m.group('crate') for m in re.finditer(r'(?m)^\s*' + STATUS, text)]
        after = [m.group('crate') for m in re.finditer(PREFIX + STATUS, text)]
        if before != after:
            assert 'commands' in report and 'index' in observation
            field = 'commands' if observation['measured'] else 'warmups'
            command = next(row for row in report[field][observation['project']]
                           if row['index'] == observation['index'])
            values = command['cargo_status_message_counts'][observation['toolchain']]
            assert values[observation['repetition']] == len(before)
            values[observation['repetition']] = len(after)
            assert not collections.Counter(before) - collections.Counter(after)
            changed['cargo_status_message_count'] = {'before': len(before), 'after': len(after)}
            changed['recovered_status_messages'] = dict(collections.Counter(after) - collections.Counter(before))
        if changed:
            changes.append({
                'log': local.relative_to(evidence).as_posix(),
                'sha256': digest,
                'project': observation['project'],
                'toolchain': observation['toolchain'],
                'repetition': observation['repetition'],
                'measured': observation['measured'],
                'changes': changed,
            })
    if changes:
        report['provenance']['log_reanalysis'] = {
            'input_report_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'reason': 'Cargo status and completion messages can occur after a partial libtest line in merged stdout/stderr.',
            'scope': 'Only diagnostic Cargo status counts and early-test log classifications changed. Timings, test counts, process observations, and the original archived reports are unchanged.',
            'changes': changes,
        }
    return report
