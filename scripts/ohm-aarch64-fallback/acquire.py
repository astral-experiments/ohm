"""Read the immutable Linux Cargo build and its original kernel and compiler records."""
import ast, gzip, hashlib, io, json, os, re, subprocess, sys, tarfile, zipfile
from collections import Counter
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
REPO='astral-experiments/ohm'
RUN=41076211398
QA='a353e77b789ca2e944037ee9b99ccc74b82e1877'
COMMIT='735e1528ed741015c57676dccf05dbdc0ff7bed1'
PRODUCT='869a24e83ff84cca6e9d6cb35eb62f149aa48555cf8bb7ee9b94d44ad90d2914'
MANIFEST='e854e38e4d75c4f86e8f40608eaa4fd7d62d7cfff71c2eeb7179b06dee437afd'
ARTIFACTS={
 'linux-cargo293-exact-product':(12986698993,17663555,'7f18258eec5dbff3d284e06a0a42ff0b740c0110c2711ceff0b6698fe1620a49'),
 'linux-cargo293-source-build-receipts':(12987123276,2862219,'be7857efbb897ccc5f83a0dec9481a1bce72bac2815ee0488e95123afe0f795d')}
def acquire(gh,output,install=None):
 def get(path):return subprocess.check_output([gh,'api',f'repos/{REPO}/'+path])
 workflow=json.loads(get(f'actions/runs/{RUN}'))
 assert (workflow['status'],workflow['conclusion'],workflow['head_sha'])==('completed','success',QA)
 artifacts=json.loads(get(f'actions/runs/{RUN}/artifacts'))['artifacts']
 assert set(ARTIFACTS)=={x['name'] for x in artifacts}
 zips={}
 for a in artifacts:
  id,size,sha=ARTIFACTS[a['name']]
  assert not a['expired'] and (a['id'],a['size_in_bytes'],a['digest'])==(id,size,'sha256:'+sha)
  wire=get(f'actions/artifacts/{id}/zip');assert len(wire)==size and H(wire)==sha
  z=zipfile.ZipFile(io.BytesIO(wire));assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None;zips[a['name']]=z
 z=zips['linux-cargo293-exact-product'];n=zips['linux-cargo293-source-build-receipts']
 assert set(z.namelist())=={'product.json','cargo'}
 manifest=z.read('product.json');binary=z.read('cargo')
 assert H(manifest)==MANIFEST and manifest==n.read('cargo-293-source/verified.json') and H(binary)==PRODUCT
 j=json.loads(manifest);source=json.loads(n.read('cargo-293-source/source.json'))
 assert j['source']==source and source['commit']==j['git']==COMMIT and source['tree']==j['tree']=='9cb7035b7adc52ecac48495666b95ba857ed3cdd'
 assert source['entries']==3114 and source['parent']=='98d431a99779ccfbcfe42dfa74dd541de3a92d05' and source['source_pack']=='775494565d10143c9f34679ad21d90020ed9c82518f774fde923f4d5ef90ea4b'
 assert j['cargo_sha256']==PRODUCT and len(binary)==j['raw_bytes']==50945312 and j['mode']==0o755 and binary[:6]==b'\x7fELF\x02\x01' and int.from_bytes(binary[18:20],'little')==62
 assert j['features']=='ohm-defaults,all-static' and j['source_workflow']==QA and j['builder']=='abf43741c6c75f7fd4a3bcbf1db0cfc29824a07727bde4a3974b3ea44b379c1a' and j['SDK_driver']=='a51424740c111a4cfdfc67b39bf498907eb396b4b1f0800c27c4fcafc9e6eb72'
 prefix='cargo-293-source/'
 assert gzip.decompress(n.read(prefix+'product-version/stdout.gz')).decode()==j['version'] and COMMIT in j['version']
 output_rows=list(map(json.loads,gzip.decompress(n.read(prefix+'construction/stdout.gz')).splitlines()))
 assert output_rows[-1]=={'reason':'build-finished','success':True}
 assert sum(r.get('reason')=='compiler-artifact' for r in output_rows)==j['typed_units']==389
 raw=n.read(prefix+'native-exec.tar.gz');assert H(raw)==j['native_trace']
 successful=Counter();roots=[];driver=0
 with tarfile.open(fileobj=io.BytesIO(raw)) as t:
  for f in t:
   if not f.isfile():continue
   for line in t.extractfile(f).read().splitlines():
    if not (line.startswith(b'execve(') and line.endswith(b'= 0')):continue
    m=re.fullmatch(rb'execve\(("(?:[^"\\]|\\.)*"), (\[.*\]), (?:NULL|0x[^)]*)\)\s+= 0',line);assert m,line[:200]
    name,argv=(ast.literal_eval(v.decode()) for v in m.groups());leaf=Path(name).name
    if leaf in ('cargo','rustc'):successful[leaf]+=1
    if name.endswith('/rustup/toolchains/ohm/bin/cargo') and argv[1:]==j['command'][2:]:driver+=1
    if name.endswith('/rustup/toolchains/ohm/bin/rustc') and '--crate-name' in argv and argv[argv.index('--crate-name')+1]=='cargo':roots.append(argv)
 assert sum(successful.values())==422==j['native_physical_cargo_rustc_events'] and driver==1
 assert sorted(roots)==sorted(j['compiler_root_argv']) and any(a[a.index('--crate-type')+1]=='bin' for a in roots)
 if install is not None:
  install.mkdir();exe=install/'cargo';exe.open('xb').write(binary);exe.chmod(j['mode']);(install/'product.json').open('xb').write(manifest)
  assert hashlib.file_digest(exe.open('rb'),'sha256').hexdigest()==PRODUCT
 receipt={'run':RUN,'QA':QA,'cargo':PRODUCT,'source':source,'physical_x86_64_ELF_bytes':len(binary),'manifest':MANIFEST,'artifacts':ARTIFACTS,'trace':H(raw),
          'full_successful_cargo_and_rustc_execs':successful,'cargo_compiler_root_argv_sha256':[H(json.dumps(v,separators=(',',':')).encode()) for v in roots],
          'compiler_driver':j['SDK_driver'],'signed_builder':j['builder'],'version':j['version'],'typed':j['typed_units']}
 output.open('xb').write((json.dumps(receipt,sort_keys=True,indent=2)+'\n').encode());print(COMMIT,PRODUCT,receipt['typed'],dict(successful))
if __name__=='__main__':
 if len(sys.argv)>1:acquire(sys.argv[1],Path(sys.argv[2]))
 else:
  root=Path(os.environ['QA_ROOT']);acquire('gh',root/'receipts/cargo-293-readback.json',root/'inputs/fixed')
