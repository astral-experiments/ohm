"""Reopen compiler-emitted coordinates, verify flat/delta sizes, and reconstruct the native output without Ruff source."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ordinal_guard import certify
from ordinal_wire import pack, unpack

def load_json(name, digest, compressed=True):
    data = (HERE / name).read_bytes()
    raw = gzip.decompress(data) if compressed else data
    assert hashlib.sha256(raw).hexdigest() == digest, name
    return json.loads(raw)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original', type=Path, help='signed artifact 13109144871 ZIP')
    args = p.parse_args()
    loader = importlib.util.spec_from_file_location('prior_receipt', HERE.parent / 'verify.py')
    base = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(base)
    packet = HERE.parent / 'raw-controls.tar.gz'
    assert base.sha(packet.read_bytes()) == base.PACKET
    with tarfile.open(packet) as t:
        seal = json.loads(t.extractfile('predictions.json').read())
        index = json.loads(t.extractfile('case-index.json').read())
        objects = {k:t.extractfile('old/' + k + '.o').read() for k in index['selected']}
    emitter = base.load_encoder(seal['predictor_sha256']['patch_dwarf.py'])
    from rebase import Coordinates, logical_cwd
    inputs = load_json('ordinal-tables.json.gz', '443598856887e4c19397b8bbf3687081a36572b948e03f616333af2971c4cd44')
    signatures = load_json('ordinal-file-signatures.json.gz', 'e41583ecd68ac881763a1571a1ad3efc5f3608ac5facd2056310892db26a5b9f')['modules']
    frozen = load_json('bridge-predictions.json.gz', 'cea6110a6de2303ffcf7c09fca55a473c567a6c034830dc016665ee34b1ee3cc')
    joined = load_json('bridge-oracle.json.gz', '8b087896f2cfd944693a42a55e551669140bea8004e378d2be2dc40335784d20')
    assert joined['sealed_input_only_predictions'] == 'cea6110a6de2303ffcf7c09fca55a473c567a6c034830dc016665ee34b1ee3cc'
    expected = joined['rows']
    roster = set(expected)
    assert roster == set(inputs['modules']) == set(signatures) == set(frozen['modules']) and len(roster) == 21
    warm = empty = None
    original = zipfile.ZipFile(args.original) if args.original else None
    if original:
        with args.original.open('rb') as f:
            assert hashlib.file_digest(f,'sha256').hexdigest() == base.ZIP_SHA
        objects = base.original_members(original,'capture/old',roster,seal['old_archive_sha256'])
    projected = {}
    admitted = set()
    sizes = {'flat':0,'delta':0}
    for k, m in inputs['modules'].items():
        roles = {}
        for stage in ('old','new'):
            s = m[stage]
            assert base.sha(json.dumps(s['files'], sort_keys=True).encode()) == s['tables_sha256']
            for flat, style in ((True,'flat'),(False,'delta')):
                blob, pieces = pack(s['comparison_key'],s['files'],signatures[k][stage],flat)
                meta = frozen['modules'][k]['wire'][stage][style]
                assert len(blob) == meta['total'] and pieces == meta['parts'] and base.sha(blob) == meta['sha256']
                roles[stage] = unpack(blob)
                assert roles[stage] == (s['comparison_key'],{f:lines for f,lines in s['files'].items() if lines},signatures[k][stage])
                if stage == 'old': sizes[style] += len(blob)
        old, new = roles['old'], roles['new']
        if old[0] != new[0]:
            assert expected[k]['status'] == 'fallthrough: unequal semantic key'
            continue
        better, why = certify(old[1], new[1])
        assert better == expected[k]['global_line_order_preserved'] and why == expected[k]['line_order_reason']
        if better: admitted.add(k)
        if k not in objects: continue
        old_obj = objects[k]
        assert base.sha(old_obj) == expected[k]['old_sha']
        mapping = Coordinates(logical_cwd(emitter.Image(old_obj)),old,new)
        body, p = emitter.reconstruct(old_obj,mapping)
        assert base.sha(body) == frozen['modules'][k]['predicted'] == expected[k]['projected_sha'] == expected[k]['warm_sha'] == expected[k]['empty_sha']
        assert p['line']['mapped_rows'] == frozen['modules'][k]['line_rows']
        projected[k] = body
    assert sizes == {'flat':147023,'delta':113071} and len(admitted) == 15
    if original:
        warm = base.original_members(original,'capture/new',roster,joined['warm_native_archive'])
        empty = base.original_members(original,'capture-empty/new',roster,joined['independent_empty_native_archive'])
        assert len(projected) == 19 and all(warm[k] == empty[k] and base.sha(warm[k]) == expected[k]['warm_sha'] for k in roster)
        assert all(body == warm[k] == empty[k] for k,body in projected.items())
        original.close()
    cross = {'/source/a.rs':[1,70,91,92],'/source/b.rs':[70]}
    a,b = ({**cross,'/source/b.rs':[n]} for n in (71,72))
    assert not certify(cross,a)[0] and certify(a,b)[0]
    print(f'All 42 records round-trip. {len(projected)} physical old inputs reproduced both recorded output digests. 19 semantic matches; 15 keep global physical order. Prior maps: {sizes}.')
    if original: print('19 complete independently reproduced objects equal both actual New archives.')

if __name__ == '__main__': main()
