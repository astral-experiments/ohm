"""Collect the unchanged original benchmark and native control records into a small archival packet."""
from pathlib import Path
import gzip,hashlib,io,json,re,tarfile,zipfile
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest() if p.stat().st_size<16<<20 else large(p)
def large(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def add(t,n,data):
 x=tarfile.TarInfo(n);x.size=len(data);x.mode=0o644;t.addfile(x,io.BytesIO(data))
def build():
 proof=json.loads((ROOT/'reopened.json').read_bytes());prov=json.loads((ROOT/'github-provenance.json').read_bytes());assert len(proof['prices'])==6;small=[ROOT/n for n in ('README.md','github-provenance.json','reopened.json','compact.py','fetch.py')]+[p for p in (ROOT/'reader').rglob('*') if p.is_file()and '__pycache__'not in p.parts];archive=ROOT/'ruff-27470-confirmation-raw-controls.tar.gz';raw=[ROOT/v['file']for v in prov['slots'].values()];enc=ROOT/'SHA256SUMS';enc.write_text(''.join(sha(p)+'  '+str(p.relative_to(ROOT))+'\n'for p in sorted(small+raw)));small.append(enc)
 with archive.open('wb')as out,gzip.GzipFile(fileobj=out,mode='wb',filename='',mtime=0,compresslevel=9)as gz,tarfile.open(fileobj=gz,mode='w|')as t:
  for p in sorted(small):add(t,str(p.relative_to(ROOT)),p.read_bytes())
  for slot,s in sorted(prov['slots'].items()):
   with zipfile.ZipFile(ROOT/s['file'])as z,z.open('matched-heldout-proof.tar')as f,tarfile.open(fileobj=f,mode='r:')as original:
    for m in original:
     if not m.isfile():continue
     key=m.name.removeprefix('receipt/');name=Path(key).name
     if key.startswith('native/')or name.endswith(('.gz','.zst'))or name in ('plan.json','query.json','prefetch.stderr','oracle-link.stderr'):continue
     allowed=key.startswith('meter/calibration/')or name in {'objects.json','renderer-object-hashes.json','provider-folds.json','unchanged-physical.json','clock.json','process.json','visit.json','registry.json','storage.json','summary.json','setup.json','heldout-worker.json','factory.json','compiler-installations.json','hardware-binding.json','hardware-confirmation.json','confirmation-registration.json','terminal.json','cargo.stdout','cargo.stderr','tests.list','test-0.stdout','test-1.stdout','test-0.stderr','test-1.stderr','multiple_insertions.stdout','multiple_insertions.stderr','snippet_with_cell.stderr','snippet_with_cell.stdout'}
     if allowed:add(t,'raw-controls/slot-'+slot+'/'+key,original.extractfile(m).read())
 (ROOT/'COMPACT-SHA256').write_text(large(archive)+'  '+archive.name+'\n');print(archive,archive.stat().st_size,large(archive),flush=True)
if __name__=='__main__':build()
