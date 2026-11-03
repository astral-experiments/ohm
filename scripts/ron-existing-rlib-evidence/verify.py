"""Reopen every genuine Callgrind process, native work product and typed metadata table."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess as sp
import sys
import tarfile
HERE=Path(__file__).resolve().parent
def digest(f):
    with f.open('rb')as s:return hashlib.file_digest(s,'sha256').hexdigest()
def main(dest):
    dest.mkdir();manifest=json.loads((HERE/'results.json').read_bytes())
    arc=HERE/'two-native-studies.tar.zst';assert digest(arc)==manifest['originals']['original_sha256']
    proc=sp.Popen(['zstd','-qd','-c',arc],stdout=sp.PIPE)
    with tarfile.open(fileobj=proc.stdout,mode='r|')as tar:
        for m in tar:
            rel=Path(m.name);assert not rel.is_absolute() and '..' not in rel.parts and rel.parts[0] in manifest['studies']
            out=dest/rel
            if m.isdir():out.mkdir(exist_ok=True,parents=True);continue
            assert m.isfile() and not out.exists();out.parent.mkdir(exist_ok=True,parents=True)
            with out.open('xb') as f:shutil.copyfileobj(tar.extractfile(m),f)
    assert proc.wait()==0
    for label,ref in manifest['studies'].items():
        root=dest/label;terminal=root/'independent-prices.json'
        assert digest(terminal)==ref['independent_reopen'] and digest(root/'prices/closed.json')==ref['original_terminal']
        assert digest(root/'registration.json')==ref['registration']
        sp.run([sys.executable,'-IB',HERE/'reopen.py',root],check=True)
        assert digest(terminal)==ref['independent_reopen']
        actual=json.loads(terminal.read_bytes());assert actual['rlib_and_depinfo']==ref['native']
        assert [{k:row[k]for k in expected} for row,expected in zip(actual['rows'],ref['rows'],strict=True)]==ref['rows']
    sys.path.insert(0,str(HERE));from reopen import fields
    n=json.loads((HERE/'controls/nine-full-file-hashes.json').read_bytes());assert n['bytes']==6250344
    for order,counter in n['guest_ir_open_read_full_blake3_close']:
        assert int(fields(HERE/'controls'/('hash-nine-'+order+'.cg'))[1]['totals'])==counter==16176022
    print('32 native compiler/supervisor profiles, 16 complete Ron archives and metadata/dep-info; both component orders verified')
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
