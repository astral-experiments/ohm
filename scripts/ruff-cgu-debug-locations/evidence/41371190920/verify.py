"""Reconstruct selected original ELF objects and optionally reopen all three rlibs from the original run."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
from types import ModuleType
import zipfile

HERE = Path(__file__).resolve().parent
SEALED = 'ded3f5947b96cb4be3ea5d3894c27b9f7afa1e77f1b1cacbf2064d563d5c8b62'
PACKET = '670b48fb6cbcaa2a122bf7b0d496b11991c365b3f475d431deac91b32e1d6573'
ZIP_SHA = '53ede61bc14ac8e524813b6cac9d1cfbbcd595b5380fae363e681406aa7b404b'
SOURCE = 'crates/ruff_workspace/src/options.rs'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_encoder(h):
    # Keep the exact frozen emitter. It imported only these three helpers from its acquisition module.
    require(sha((HERE / 'patch_dwarf.py').read_bytes()) == h, 'frozen emitter changed')
    helpers = ModuleType('old_inputs')
    helpers.PR, helpers.check, helpers.sha = SOURCE, require, sha
    sys.modules['old_inputs'] = helpers
    sys.path.insert(0, str(HERE))
    import patch_dwarf
    return patch_dwarf


def original_members(zipfile_, prefix, roster, expected):
    plan = json.loads(zipfile_.read(prefix + '/cgus.json'))['ruff_workspace']
    a = plan['archive']
    n = a['stat'][2]
    require(a['sha256'] == expected and n < 28_000_000, 'wrong native archive manifest')
    with zipfile_.open('cgu-originals/' + expected + '.gz') as input_, gzip.GzipFile(fileobj=input_) as r:
        raw = r.read(n + 1)
    require(len(raw) == n and sha(raw) == expected and raw.startswith(b'!<arch>\n'), 'native archive differed')
    pos = 8
    strings = b''
    result = {}
    member_names = set()
    while pos < n:
        header = raw[pos:pos + 60]
        require(len(header) == 60 and header[-2:] == b'`\n', 'malformed ar header')
        size = int(header[48:58])
        start = pos + 60
        require(0 <= size <= n - start, 'invalid ar extent')
        name = header[:16].decode('ascii').rstrip()
        if name == '//':
            strings = raw[start:start + size]
        elif re.fullmatch(r'/[0-9]+', name):
            off = int(name[1:])
            end = strings.index(b'/\n', off)
            name = strings[off:end].decode('ascii')
        require(name not in member_names, 'duplicate native member')
        member_names.add(name)
        obj = re.fullmatch(r'ruff_workspace-([0-9a-f]{16})\.([a-z0-9]{25})(?:\.[a-z0-9]{7})?\.rcgu\.o', name)
        if obj:
            key = 'ruff_workspace.' + obj[1] + '.' + obj[2]
            if key in roster:
                require(key not in result, 'duplicate stable CGU')
                result[key] = raw[start:start + size]
        pos = start + size + size % 2
    require(pos == n and set(result) == roster, 'incomplete CGU archive')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, help='authenticated GitHub artifact 13109144871 ZIP')
    options = parser.parse_args()
    path = HERE / 'raw-controls.tar.gz'
    require(sha(path.read_bytes()) == PACKET, 'compact packet differs')
    with tarfile.open(path) as tar:
        raw = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}
    case_index = json.loads(raw['case-index.json'])
    require(all(sha(raw[k]) == v for k, v in case_index['sha'].items()), 'raw member changed')
    frozen = json.loads(raw['predictions.json'])
    cmp = json.loads(raw['oracle.json'])
    require(sha(raw['predictions.json']) == SEALED == cmp['predictions_sha256'], 'prediction differs')
    for name in ('old_inputs.py', 'predict.py', 'roster.txt'):
        require(sha(raw[name]) == frozen['predictor_sha256'][name], 'input code differed')
    emitter = load_encoder(frozen['predictor_sha256']['patch_dwarf.py'])
    src = frozen['physical_source']
    source_old = raw['source/old-options.rs']
    old = source_old.splitlines(keepends=True)
    inserts = json.loads(raw['source/inserts.json'])
    edited = list(old)
    for line, text in reversed(inserts):
        edited[line:line] = [s.encode('utf8') for s in text]
    require((sha(source_old), sha(b''.join(edited))) == (src['old_sha'], src['new_sha']), 'Ruff source bytes differed')
    mapping = {i: i + sum(len(add) for line, add in inserts if i > line) for i in range(1, len(old) + 1)}
    transform = emitter.SourceMap(SOURCE, mapping, old, edited)
    identity = emitter.SourceMap(SOURCE, {i:i for i in range(1, len(old) + 1)}, old, old)
    roster = set(frozen['rows'])
    require(len(roster) == 21 and set(cmp['rows']) == roster, 'wrong unit inventory')
    expected = cmp['totals']
    require((expected['actual_matching_full_elf'], expected['exact_rewritten'], expected['exact_changed_line_rows'], expected['exact_changed_die_source_attrs']) == (19, 15, 16560, 11474), 'registered controls differ')
    old_objs = {k: raw['old/' + k + '.o'] for k in case_index['selected']}
    warm_objs = clean_objs = None
    if options.original:
        with options.original.open('rb') as f:
            require(hashlib.file_digest(f, 'sha256').hexdigest() == ZIP_SHA, 'original archive changed')
        with zipfile.ZipFile(options.original) as z:
            old_objs = original_members(z, 'capture/old', roster, frozen['old_archive_sha256'])
            warm_objs = original_members(z, 'capture/new', roster, cmp['warm_archive'])
            clean_objs = original_members(z, 'capture-empty/new', roster, cmp['clean_archive'])
    matches = refuses = differ = 0
    for k, old_obj in sorted(old_objs.items()):
        pred, verdict = frozen['rows'][k], cmp['rows'][k]
        require(sha(old_obj) == pred['old_elf_sha'] == verdict['old'], 'wrong OLD member')
        require(emitter.reconstruct(old_obj, identity)[0] == old_obj, 'full OLD identity failed')
        if warm_objs is not None:
            require(warm_objs[k] == clean_objs[k] and sha(warm_objs[k]) == verdict['warm'] == verdict['clean'], 'warm and clean differ')
        try:
            rebuilt, proof = emitter.reconstruct(old_obj, transform)
        except (ValueError, OverflowError) as exc:
            require(str(exc) == pred.get('refusal') == verdict.get('refusal'), 'unregistered guard refusal')
            refuses += 1
            continue
        require(sha(rebuilt) == pred['predicted_elf_sha'] == verdict['predicted'], 'Old-only prediction differed')
        exact = sha(rebuilt) == verdict['warm'] == verdict['clean']
        require(verdict['complete_byte_equality'] == exact, 'wrong native outcome')
        if warm_objs is not None:
            require(exact == (rebuilt == warm_objs[k] and rebuilt == clean_objs[k]), 'whole ELF differs')
        require(proof['line']['mapped_rows'] == verdict['debug_line_rows'] and proof['die'].get('call_changed', 0) + proof['die'].get('decl_changed', 0) == verdict['debug_die_attrs'], 'debugger row counts differed')
        matches += exact
        differ += not exact
    if 'debugger.json' in raw:
        dbg = json.loads(raw['debugger.json'])
        require(dbg['predictor_seal'] == SEALED and dbg['totals']['changed_rows'] == 16560 and dbg['totals']['call_changed'] == 11474 and len(dbg['units']) == 19, 'independent debugger results differ')
    print(f'{len(old_objs)} physical old inputs reopened: {matches} match both recorded New ELFs, {differ} native mismatch, {refuses} conservative refusal.')
    if options.original:
        require((matches, differ, refuses) == (19, 1, 1), 'full original outcomes differ')
        print('All warm and independently clean New object bytes physically verified.')


if __name__ == '__main__':
    main()
