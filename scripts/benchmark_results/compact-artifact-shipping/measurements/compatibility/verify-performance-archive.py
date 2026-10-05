"""Verify package, safely extract into a new directory, and verify every inventory entry."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,tarfile

def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('package',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
package=json.loads(a.package.read_text());assert package['passed'] and sha(a.archive)==package['archive_sha256'] and a.archive.stat().st_size==package['archive_bytes']
assert not a.output.exists();a.output.mkdir(parents=True)
with tarfile.open(a.archive,'r:gz') as tar:
 members=tar.getmembers();names=set()
 for item in members:
  name=PurePosixPath(item.name)
  assert item.isfile() and not name.is_absolute() and '..' not in name.parts and str(name)==item.name and name.parts[0]=='compatibility-proof' and item.name not in names,item.name
  names.add(item.name)
 assert len(names)==package['archive_regular_files']
 tar.extractall(a.output,filter='data')
root=a.output/'compatibility-proof';inv=root/'inventory.json'
assert sha(inv)==package['inventory_sha256'];inventory=json.loads(inv.read_text())
assert len(inventory['files'])==inventory['file_count']==package['payload_files']
assert sum(x['bytes'] for x in inventory['files'])==inventory['total_bytes']==package['payload_bytes']
expected={'compatibility-proof/inventory.json'}
for row in inventory['files']:
 relative=PurePosixPath(row['path']);assert not relative.is_absolute() and '..' not in relative.parts and str(relative)==row['path']
 target=root/row['path'];assert target.resolve().is_relative_to(root.resolve()) and target.is_file() and not target.is_symlink() and target.stat().st_size==row['bytes'] and sha(target)==row['sha256'],row['path']
 expected.add('compatibility-proof/'+row['path'])
assert names==expected
print(json.dumps({'passed':True,'archive_sha256':sha(a.archive),'regular_files_verified':len(names),'payload_bytes':inventory['total_bytes']}))
