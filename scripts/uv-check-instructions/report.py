"""Summarize matched hardware-instruction receipts from workload.py."""
from collections import defaultdict
import json
from pathlib import Path
from statistics import median
import sys

from diagnostics import normalize


def load(path):
    return json.loads(path.read_text())


def instructions(path, crate=''):
    rows = [row.split('\t') for row in path.read_text().splitlines()]
    return sum(int(row[3]) for row in rows if not crate or row[1] == crate)


def tree(path):
    return int(path.read_text().split()[0])


def history(path):
    rows = load(path/'results.json')
    assert len(rows) == 21 and rows[-1]['commit'].startswith('c99faeee')
    prime = path/'0'
    report = {'Prime (rustc)':instructions(prime/'prime.tsv'),
              'Prime (command)':tree(prime/'prime.tsv.tree')}
    sums = defaultdict(int)
    for step, row in enumerate(rows[1:],1):
        folder = path/str(step)
        assert not instructions(folder/'noop.tsv')
        assert row['total'] == instructions(folder/'units.tsv')
        group = '4 dependency updates' if step in (4,5,9,18) else '16 other edits'
        for label in ('20 edits',group):
            sums[label+' (rustc)'] += row['total']
            sums[label+' (command)'] += tree(folder/'units.tsv.tree')
            sums[label+' (invocations)'] += len(row['units'])
        if row['total']:
            report[row['title']] = row['total']
            sums['Edits launching rustc'] += 1
    return {**sums, **report}


def codex(path,op):
    rows = {}
    total = defaultdict(int)
    for i,name in enumerate(['Prime','#38657','#39864']):
        folder = path/str(i)/op
        result = load(folder/'result.json')
        own = instructions(folder/'units.tsv','codex_tui')
        assert own, folder
        if i:
            total['Two edits (command)'] += result['tree']
            total['Two edits (TUI compiler)'] += own
        rows[name+' (command)'] = result['tree']
        rows[name+' (TUI compiler)'] = own
        rows[name+' (TUI incremental bytes)'] = result['tui_incremental_bytes']
    return {**total, **rows}


def mixed(path):
    rows = {}
    for i,label in [(0,'Prime'),(1,'Dependency update')]:
        total = 0
        for op in ('check','clippy','test'):
            folder = path/str(i)/op
            result = load(folder/'result.json')
            total += result['tree']
            rows[f'{label} {op} (command)'] = result['tree']
            own = instructions(folder/'units.tsv','uv_client')
            if own:
                rows[f'{label} {op} (uv-client compiler)'] = own
            if 'tests' in result:
                rows[f'{label} tests passed'] = len(result['tests'])
        rows[f'{label} check + Clippy + test preparation (command)'] = total
    return rows


def audit_history(path):
    count = byte_count = byte_diff = diag_diff = 0
    differences = {}
    audits = list(path.glob('*/audit.json'))
    for receipt in audits:
        row = load(receipt)
        diag_diff += row['warm_diagnostics'] != row['fresh_diagnostics']
        for name,rec in row['outputs'].items():
            a,b = rec['warm'],rec['fresh']
            byte_count += 1
            byte_diff += a != b
            key = 'sha' if name.endswith('public-api-hash') else 'public'
            count += b[key] is not None
            if a[key] != b[key]:
                differences.setdefault(receipt.parent.name,[]).append(name)
    return dict(steps=len(audits), fingerprints=count, public_mismatches=differences,
                files=byte_count, byte_mismatches=byte_diff, differing_diagnostics=diag_diff)


def audit_package(path):
    steps = count = bytes_count = bytes_diff = raw = msgs = 0
    mismatch = {}
    for receipt in path.glob('fresh-*/*/result.json'):
        revision,op,_ = receipt.relative_to(path).parts
        if op.endswith('-noop'):
            continue
        series = revision[6:]+'/'+op
        a,b = load(path/series/'result.json'),load(receipt)
        assert a.get('tests') == b.get('tests')
        assert normalize(a['diags']) == normalize(b['diags']), receipt
        raw += a['diags'] != b['diags']
        msgs += len(a['diags'])
        assert set(a['metadata']) == set(b['metadata'])
        for name,v in a['metadata'].items():
            other = b['metadata'][name]
            bytes_count += 1
            bytes_diff += v != other
            count += other['public'] is not None
            if v['public'] != other['public']:
                mismatch.setdefault(series,[]).append(name)
        steps += 1
    return dict(steps=steps,fingerprints=count,public_mismatches=mismatch,
                files=bytes_count,byte_mismatches=bytes_diff,differing_diagnostics=0,
                warnings=msgs,steps_moving_one_time_notes=raw)


def aggregate(root):
    groups = defaultdict(dict)
    reviews = {}
    sdk = {}
    for p in sorted(root.iterdir()):
        if not (p/'config.json').is_file():
            continue
        config=load(p/'config.json')
        case = config['case']
        roles = {}
        for role in ('control','candidate'):
            if not (p/role).is_dir():
                continue
            proof = load(p/(role+'-sdk.json'))
            assert sdk.setdefault(role,proof) == proof
            path = p/role
            if case.startswith('audit-'):
                reviews[case] = audit_history(path)
                continue
            if case == 'history':
                roles[role] = history(path)
            elif case.startswith('codex-'):
                roles[role] = codex(path,case[6:])
            elif case == 'mixed':
                roles[role] = mixed(path)
            if config['pair']==1 and case!='history':
                reviews[case+' '+role] = audit_package(path)
        if len(roles)==2:
            groups[case][config['pair']]=roles
            for receipt in (p/'control').glob('[0-9]*/*/result.json'):
                a,b = load(receipt),load(p/'candidate'/receipt.relative_to(p/'control'))
                assert a.get('tests') == b.get('tests')
                assert normalize(a['diags']) == normalize(b['diags']), receipt
    result={}
    for case,pairs in groups.items():
        data = {}
        keys = list(dict.fromkeys(k for pair in pairs.values() for values in pair.values() for k in values))
        for k in keys:
            raw = [(r['control'].get(k,0),r['candidate'].get(k,0)) for r in pairs.values()]
            pct = [100*(b/a-1) for a,b in raw if a]
            data[k] = dict(raw=raw, control=median(a for a,b in raw),
                           candidate=median(b for a,b in raw),delta=median(pct) if pct else None,
                           range=[min(pct),max(pct)] if pct else None)
        result[case] = data
    return dict(provenance=sdk,measurements=result,audits=reviews)


def format_count(x):
    if abs(x) >= 1e9:
        return f'{x/1e9:.3f}B'
    if abs(x) >= 1e6:
        return f'{x/1e6:.2f}M'
    return f'{x:g}'


def summary(result):
    for k,v in result['provenance'].items():
        if 'proof' in v:
            rev=v['proof']['sources']['rust']['revision']
            label='distribution'
        else:
            rev=v['rust']
            label='stage 1'
        print(f'{k.title()} {label} with rustc `{rev}` and archive SHA-256 `{v["archive"]}`.\n')
    if result['measurements']:
        print('Measurements count userspace hardware instructions. Command totals include Cargo and its descendants. Compiler totals include all threads of the selected compiler images. Each pair replays both compilers from empty targets on the same Linux runner, alternating which compiler goes first. Ranges span the paired changes.\n')
    for case,data in result['measurements'].items():
        n=len(next(iter(data.values()))['raw'])
        print(f'## {case} ({n} pairs)\n')
        if case=='history':
            print('After the prime, each workspace check builds on the preceding check. Rows for individual merges count rustc instructions.\n')
        if case.startswith('codex-'):
            print('The two TUI edits build on the previous compilation, with other sources frozen and the archived allocative dependency updated for Rust 1.100.\n')
        if case=='codex-clippy':
            print('Clippy caps historical deny lints at warning level in both arms.\n')
        if case=='mixed':
            print('The mixed workload runs check, Clippy and test preparation for the uv-client library, applies the certificate update, then repeats the sequence. The test binary runs outside the counter.\n')
        print('| Metric | Control | Candidate | Change | Range |')
        print('|---|---:|---:|---:|---:|')
        for name,row in data.items():
            a,b=format_count(row['control']),format_count(row['candidate'])
            if row['delta'] is not None:
                low,high=row['range']
                v=f'{row["delta"]:+.2f}% | {low:+.2f}% … {high:+.2f}%'
            else:
                v='— | —'
            print(f'| {name} | {a} | {b} | {v} |')
        print()
    if result['audits']:
        print('## Fresh comparisons\n')
        print('The uv history rebuilds all workspace packages at each source revision that launched rustc and checks both metadata headers and Cargo fingerprints. The mixed replay restores the original mixed target with all query caches cleared before applying the dependency update. The TUI replay cleans the selected package before rebuilding each edit. Diagnostic comparisons preserve all source locations, count one-time command-line notes per lint and allow such a note to follow a different warning for the same lint.\n')
        print('| Case | Steps | Public hashes | Differing hashes | Differing files | Steps with differing diagnostics |')
        print('|---|---:|---:|---:|---:|---:|')
        for key,rec in result['audits'].items():
            dif=sum(len(v) for v in rec['public_mismatches'].values())
            print(f'| {key} | {rec["steps"]} | {rec["fingerprints"]} | {dif} | {rec["byte_mismatches"]} / {rec["files"]} | {rec["differing_diagnostics"]} |')


if __name__=='__main__':
    root=Path(sys.argv[1])
    result=aggregate(root)
    (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    summary(result)
