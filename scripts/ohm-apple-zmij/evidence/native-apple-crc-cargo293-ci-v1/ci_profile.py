"""Verify whether the actual test-emitting rustc processes received an incremental directory."""
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile


def commitment(value):
    return hashlib.sha256(value).hexdigest()


def inspect(archive):
    with ZipFile(archive) as z:
        rows = []
        names = {p for p in z.namelist() if p.endswith('/exec.json.gz') and (
            p.startswith('crc-clock-before/') or p.startswith('crc-clock-confirmation/terminal-clean/'))}
        for name in sorted(names):
            body = gzip.decompress(z.read(name)); hashes=[]
            for e in json.loads(body):
                a = e['argv']
                if not e['path'].endswith('/native/bin/rustc') or '--crate-name' not in a or a[a.index('--crate-name')+1] != 'ty_vendored' or '--test' not in a:
                    continue
                assert any(v.startswith('--emit=') and 'link' in v[7:].split(',') for v in a) and not any('link-only' in v for v in a)
                flags=[b for k,b in zip(a,a[1:]) if k=='-C']+[s[2:] for s in a if s.startswith('-C') and s!='-C']
                assert not any(s.startswith('incremental=') for s in flags)
                hashes.append([e['pid'],e['cdhash'],commitment(json.dumps(a,separators=(',',':')).encode())])
            assert len(hashes)==1,name
            rows.append({'phase':name.removesuffix('/exec.json.gz'),'exec_sha256':commitment(body),'emitter':hashes[0],'incremental':False})
        assert len(rows)==34 and sum(r['phase'].startswith('crc-clock-before/') for r in rows)==32
        return {'ordinary_profile':'hosted CI, Cargo disables incremental','preliminary_emitters':32,'terminal_emitters':2,'incremental_emitters':0,'raw':rows}

if __name__=='__main__':
    import sys
    result=inspect(Path(sys.argv[1]));expected=json.loads(Path(sys.argv[2]).read_bytes());assert result==expected
    print('Reopened all 34 actual root compiler commands; none carried -C incremental.')
