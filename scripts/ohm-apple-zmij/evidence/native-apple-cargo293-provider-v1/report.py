"""Summarize the reopened native ledger without treating a fallback as a verified cache hit."""
import gzip,json,sys
from pathlib import Path
d=json.loads(gzip.decompress(Path(sys.argv[1]).read_bytes()))
main=d['provider'];out=d['summary']
def v(r):
    ret=str(r['status']) if r['status'] else ' '.join(map(str,r['answer']))
    return f"{ret} ({len(r['full'])}/{len(r['link_only'])}/{r['final']};{r['driver_processes']}/{r['dependency_info']}/{len(r['seals'])})"
print('Provider outcome (full rustc / link-only rustc / final Xcode ld; Cargo-link-driver / ld reports / seals)')
for key,rows in main.items():
    source=['unchanged-lower','higher-no-rust','malformed-no-rust','missing-no-rust','restored-unchanged']
    if 'stamp-' in key:source=['original-higher','repeat-higher','overwrite-same-stamp','repeat-replacement','restore-same-stamp']
    print(key, ' ; '.join(v(rows[k]['warm']) for k in source))
    if key.startswith('R') and 'unwatched-default' in key: print('  warm discrepancies', [k for k,r in rows.items() if not r['same_verdict']], 'whole image discrepancies among correct', [k for k,r in rows.items() if r['same_verdict'] and r['same_raw'] is False])
if d['ruff']:
    print('Ruff full rustc / link-only / Xcode ld with Cargo drivers, reports and seals')
    for path,r in d['ruff'].items():
        if '/visit/' in path: print(path,r['status'],r['full'],r['link_only'],r['ld'],r['driver_processes'],r['dependency_info'],len(r['seals']),r.get('tests'))
print('Native host',out['host'],'Xcode subjects',out['stock_linkers'])
print('Native operations',out['commands'],'+ Ruff',out['ruff_commands'],'images',out['distinct_native_images'])
