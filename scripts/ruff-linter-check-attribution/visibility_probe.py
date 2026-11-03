"""Exercise a warm downstream privacy error on the real Ruff dependency."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inv
import worker as w


CLIENT = 'crates/ruff_db/src/diagnostic/mod.rs'
CLIENT_SHA = '106596aef8474b6d340244abf0b7b1a13ddcb77e628323c22dcf5a6a235310f1'
FIELD = b"pub struct Origin<'a> {\n    pub(crate) path: Option<Cow<'a, str>>,"
PUBLIC = b"pub struct Origin<'a> {\n    pub path: Option<Cow<'a, str>>,"
ACCESS = b"""
#[allow(dead_code)]
fn observe_origin_path_for_visibility(origin: &annotate_snippets::Origin<'_>) {
    let _ = &origin.path;
}
"""


def verdict(out, private):
    """Check the complete Cargo result and every reported error, including its original span."""
    rows = [json.loads(s) for s in (out/'stdout').read_bytes().splitlines() if s]
    w.need([r['success'] for r in rows if r['reason']=='build-finished']==[not private],
           'incomplete visibility verdict')
    errors = [r['message'] for r in rows if r['reason']=='compiler-message' and r['message']['level']=='error']
    verdict = []
    for error in errors:
        spans = [(s['file_name'], s['line_start'], s['line_end'], s['column_start'], s['column_end'])
                 for s in error['spans'] if s['is_primary']]
        w.need((error.get('code') or {}).get('code')=='E0616' and 'is private' in error['message']
               and len(spans)==1 and spans[0][0].endswith(CLIENT)
               and any('let _ = &origin.path;'==line['text'].strip() for s in error['spans']
                       if s['is_primary'] for line in s['text']), 'wrong error or source span')
        verdict.append([error['code']['code'], error['message'], spans])
    w.need(len(verdict)==int(private), 'wrong number of access errors')
    w.need(b'internal compiler error' not in (out/'stderr').read_bytes().lower(), 'compiler ICE')
    return verdict


def check(label, private):
    """Run ordinary Cargo and independently identify the compiler that emitted the error."""
    trace = w.ROOT/'traces'/w.OUT.name/label
    trace.mkdir(parents=True)
    out = w.OUT/label
    cmd = ['/usr/bin/strace', '-ff', '-qq', '-s', '131072', '-e', 'trace=execve,execveat',
           '-o', trace/'exec', '--', *w.CMD]
    w.run(cmd, w.environment(), out, expected=101 if private else 0)
    result = verdict(out, private)
    roots = inv.executed_compilers(trace)
    w.save(out/'rustcs.json', roots)
    if private:
        w.need(any(r['crate']=='ruff_db' for r in roots), 'privacy error did not reach its consumer')
    return result


def probe():
    """Narrow just the producer's field while the consumer and build directory stay in place."""
    w.source(w.NEW)
    owner, client = w.SRC/w.SOURCE, w.SRC/CLIENT
    original, previous = owner.read_bytes(), client.read_bytes()
    w.need(w.sha(client)==CLIENT_SHA and original.count(FIELD)==1 and PUBLIC not in original
           and ACCESS not in previous, 'unregistered visibility input')
    wide = original.replace(FIELD, PUBLIC)
    try:
        client.write_bytes(previous + ACCESS)
        owner.write_bytes(wide)
        check('visibility-public', False)
        owner.write_bytes(original)
        warm = check('visibility-private-warm', True)
        w.fresh_state()
        clean = check('visibility-private-clean', True)
        w.need(warm==clean, 'incremental and empty-state privacy verdicts differ')
        owner.write_bytes(wide)
        check('visibility-public-repaired', False)
        w.save(w.OUT/'visibility.json', {'client':CLIENT, 'client_sha':CLIENT_SHA, 'warm':warm, 'clean':clean})
    finally:
        owner.write_bytes(original)
        client.write_bytes(previous)
    w.source(w.NEW)
