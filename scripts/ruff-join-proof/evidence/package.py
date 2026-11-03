"""Extract and deduplicate the original raw Cargo phase evidence."""
from pathlib import Path
import hashlib,io,json,subprocess,sys,tarfile,zipfile

runs = {'41593423160':'d7153c048a0d42aea3ef43b461b66bcc1ca7c491cffeb95c393ca893e5311b5f',
        '41597635908':'232eef164c9273cf8e475c69d253f74c80d8fd3912e898060ab71168d60bbace'}
root, dst = map(Path,sys.argv[1:])
manifest = {}; bodies = {}
for run, digest in runs.items():
    origin = root/('run-'+run)
    archive = origin/'original.zip'
    asset, = json.loads((origin/'api.json').read_bytes())['artifacts']
    assert hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()==digest==asset['digest'][7:]
    assert archive.stat().st_size == asset['size_in_bytes']
    members = {}
    with zipfile.ZipFile(archive) as z:
        for item in sorted(z.infolist(),key=lambda x:x.filename):
            name = item.filename
            if item.is_dir() or (name.split('/')[0] not in {'shipped','fixed','upstream','shipped-defaults-off','bodies','no-checksums'} and (name.endswith('stdout') and not name.startswith('cargo-tests-') or not name.endswith(('.json','.toml','stdout')))):
                continue
            assert not Path(name).is_absolute() and '..' not in Path(name).parts and name not in members
            payload = z.read(item)
            assert len(payload) <= 15*2**20
            key = hashlib.sha256(payload).hexdigest()
            members[name] = key
            assert key not in bodies or bodies[key]==payload
            bodies[key] = payload
    manifest[run] = {'source':asset,'members':members}
with dst.open('xb') as out:
    z = subprocess.Popen(['zstd','-9','-q','-c','-T1'],stdin=subprocess.PIPE,stdout=out)
    with tarfile.open(fileobj=z.stdin,mode='w|') as tar:
        def add(name,body):
            item=tarfile.TarInfo(name);item.size=len(body);tar.addfile(item,io.BytesIO(body))
        add('manifest.json',json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
        for key,body in sorted(bodies.items()):add('blobs/'+key,body)
    z.stdin.close();assert z.wait()==0
print('archive:',dst.stat().st_size,hashlib.file_digest(dst.open('rb'),'sha256').hexdigest(),'unique bodies:',len(bodies))
