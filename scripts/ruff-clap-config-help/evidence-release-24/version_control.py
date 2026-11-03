"""Run the real retained release-built CLI, outside every compiler counter."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
zpath,expected,out=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3])
with zpath.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
assert shutil.disk_usage(out.parent).free>15*2**30
env=dict(os.environ,LC_ALL='C',NO_COLOR='1',RUFF_NO_CACHE='true')
data={}
with zipfile.ZipFile(zpath)as z,tempfile.TemporaryDirectory(dir=out.parent)as d:
  exe=Path(d)/'ruff'
  for phase in ('old','edit','independent-clean-new'):
    product=json.loads(z.read(phase+'/products.json'))['elf']
    with z.open('bodies/'+product['sha256']+'.zst')as src, exe.open('wb')as f:
        proc=subprocess.Popen(['zstd','-dcq'],stdin=subprocess.PIPE,stdout=f)
        with proc.stdin as dest:shutil.copyfileobj(src,dest,65536)
        assert proc.wait(timeout=60)==0 and f.tell()==product['size']
    with exe.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==product['sha256']
    exe.chmod(0o755)
    results={}
    for args in [['--version'],['version','--output-format','json']]:
        p=subprocess.run([exe,*args],cwd=d,env=env,capture_output=True,timeout=12)
        results[' '.join(args)]={'status':p.returncode,'stdout':p.stdout.decode(),'stderr':p.stderr.decode()}
    data[phase]={'elf':product['sha256'],'results':results}
assert data['old']['results']['--version']['status']==data['edit']['results']['--version']['status']==0
assert data['edit']==data['independent-clean-new']
out.write_text(json.dumps(data,sort_keys=True,indent=1)+'\n')
for k,v in data.items():print(k,str(v['results'])[:225])
