"""Reproduce LLVM's cross-file is_stmt behavior and count the remaining Ruff units."""

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import ModuleType


HERE = Path(__file__).resolve().parent
TABLES = 'eda01b977063cce3623ffc18ae02328976b9e57ad7a474aebac93a4e850e48bd'
PATCHER = '1beaf3d4dd2a08e02d2c3439a3af27177dd287572697aaa74eaab9a9d7315fc2'


def sha(contents):
    return hashlib.sha256(contents).hexdigest()


def compatible(old, new):
    """Preserve every equality and strict ordering of lines, including cross-file pairs."""
    if old.keys() != new.keys():
        return False
    pairs = [(0, 0), (1, 1)]
    for name, lines in old.items():
        if len(lines) != len(new[name]):
            return False
        pairs.extend(zip(lines, new[name]))
    pairs.sort()
    return all((a == c and b == d) or (a < c and b < d)
               for (a, b), (c, d) in zip(pairs, pairs[1:]))


def ruff_counts(path):
    contents = path.read_bytes()
    assert sha(contents) == TABLES
    records = json.loads(gzip.decompress(contents))['modules']
    comparable = {k: v for k, v in records.items() if v['admitted']}
    accepted = {key: row['fixed_actor_guest_ir'] for key, row in comparable.items()
                if compatible(row['old']['files'], row['new']['files'])}
    assert (len(records), len(comparable), len(accepted)) == (21, 19, 15)
    total = sum(r['fixed_actor_guest_ir'] for r in records.values())
    assert (total, sum(accepted.values())) == (120906271208, 83908903279)
    return {'admitted': accepted, 'declined_after_per_file_match': sorted(comparable.keys() - accepted.keys()),
            'all_backend_guest_instructions': total, 'admitted_backend_guest_instructions': sum(accepted.values())}


class FixtureEdit:
    def __init__(self, old, new):
        self.old, self.new = old, new

    def location(self, name, line, column):
        if Path(name).name == 'b.rs' and line == self.old:
            return self.new
        return line


def lines(value):
    return {'a.rs': [12, 70, 91, 92], 'b.rs': [value]}


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout


def native(folder, args):
    assert sha(args.patcher.read_bytes()) == PATCHER
    # The original one-edit apparatus supplied these three primitives to the rewriter.
    donor = ModuleType('old_inputs')
    donor.PR = 'crates/ruff_workspace/src/options.rs'
    donor.sha = sha

    def require(value, message):
        if not value:
            raise ValueError(message)

    donor.check = require
    sys.modules[donor.__name__] = donor
    spec = importlib.util.spec_from_file_location('old_only_patcher', args.patcher)
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    objects, outcomes = {}, {}
    for line in (70, 71, 72):
        name = f'line-{line}'
        run([sys.executable, '-IB', HERE / 'emit.py', args.llvm, HERE / 'cross-file.ll', str(line), name + '.o'], folder)
        objects[name] = (folder / (name + '.o')).read_bytes()
    for before, after in ((70, 71), (71, 70), (71, 72), (72, 71)):
        name = f'pred-{before}-{after}'
        obj, _ = patcher.reconstruct(objects[f'line-{before}'], FixtureEdit(before, after))
        equal = obj == objects[f'line-{after}']
        accepted = compatible(lines(before), lines(after))
        assert accepted == equal == (min(before, after) > 70)
        (folder / (name + '.o')).write_bytes(obj)
        objects[name] = obj
        outcomes[name] = {'admitted': accepted, 'matches_new_complete_object': equal}
    samples = {}
    for name, obj in objects.items():
        o, exe = name + '.o', name + '.elf'
        run(['cc', '-g', '-no-pie', '-Wl,--build-id=none', HERE / 'caller.c', o, '-o', exe], folder)
        assert run([folder / exe], folder) == b'19 19\n'
        text = run(['objcopy', '--dump-section', '.text=/dev/stdout', o, '/dev/null'], folder)
        assert text.hex() == 'c7070b000000c707130000008b07c3'
        raw = run([args.dwarfdump, '--debug-line', o], folder).decode()
        match, = re.findall(r'^0x0*6\s+(\d+)\s+4\s+2\s+0\s+0\s+0[ \t]*(.*)$', raw, re.M)
        line, flags = int(match[0]), match[1].split()
        original = int(name.split('-')[1])
        assert line == int(name.split('-')[-1]) and ('is_stmt' in flags) == (original != 70)
        sample = {'sha256': sha(obj), 'bytes': len(obj), 'b_rs_line': line, 'is_stmt': 'is_stmt' in flags}
        if args.debugger:
            instructions = ['set debuginfod enabled off', 'set disable-randomization off', 'break probe', 'run', 'step', 'info line *$pc']
            command = ['gdb', '-nx', '-nh', '-batch']
            for instruction in instructions:
                command.extend(('-ex', instruction))
            output = run([*command, exe], folder).decode()
            stopped, = re.findall(r'Line (\d+) of "([ab]\.rs)" starts at address 0x[0-9a-f]+ <probe\+(\d+)>', output)
            expected = (str(line), 'b.rs', '6') if sample['is_stmt'] else ('91', 'a.rs', '12')
            assert stopped == expected, output
            sample['source_step'] = {'file': stopped[1], 'line': int(stopped[0]), 'offset': int(stopped[2])}
        samples[name] = sample
    return {'objects': samples, 'transitions': outcomes, 'native_verdict': '19 19', 'machine_text': text.hex()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--llvm', type=Path, required=True)
    parser.add_argument('--patcher', type=Path, required=True)
    parser.add_argument('--tables', type=Path, required=True)
    parser.add_argument('--dwarfdump', default='llvm-dwarfdump-18')
    parser.add_argument('--debugger', action='store_true')
    args = parser.parse_args()
    args.llvm = args.llvm.resolve(strict=True)
    with tempfile.TemporaryDirectory() as tmp:
        result = {'ruff': ruff_counts(args.tables), 'fixture': native(Path(tmp), args)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
