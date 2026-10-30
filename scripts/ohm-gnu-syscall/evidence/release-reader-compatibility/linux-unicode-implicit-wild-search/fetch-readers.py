"""Fetch only the three original QA Cargo artifacts, checking public metadata, ZIP, ELF and size."""
import hashlib,io,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
def sha(x):return hashlib.sha256(x).hexdigest()
q=Path(__file__).resolve().parent
if len(sys.argv)!=2:raise SystemExit('usage: python3 fetch-readers.py NEW_DIRECTORY')
r=Path(sys.argv[1]);r.mkdir();cfg=json.loads((q/'identities.json').read_text());cmd=shutil.which('gh-auto') or shutil.which('gh')
if not cmd:raise SystemExit('gh-auto or gh with read access to QA artifacts is required')
for role,p in cfg['transport'].items():
 api=f"repos/astral-experiments/ohm/actions/artifacts/{p['asset']}"
 meta=json.loads(subprocess.check_output([cmd,'api',api]));assert not meta['expired'] and meta['workflow_run']['id']==p['run'] and meta['digest']=='sha256:'+p['sha256']
 data=subprocess.check_output([cmd,'api',api+'/zip']);assert len(data)==meta['size_in_bytes'] and sha(data)==p['sha256']
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  name,=[i for i in z.infolist() if Path(i.filename).name in ('cargo','cargo.zst')]
  assert name.file_size<128*(1<<20)
  body=z.read(name)
  if name.filename.endswith('.zst'):body=subprocess.check_output(['zstd','-qdc','-M128MB'],input=body)
  assert body.startswith(b'\x7fELF\x02\x01') and sha(body)==cfg['cargo'][role]['sha256']
  dest=r/role;dest.write_bytes(body);dest.chmod(0o755)
  print(role,cfg['cargo'][role]['source'],sha(body))
