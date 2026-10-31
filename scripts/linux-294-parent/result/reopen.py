"""Reopen portable native receipts using the prospective source verifier, with no Cargo, network or linker."""
import ast,collections,gzip,hashlib,json,re,sys,tempfile,zipfile
from pathlib import Path
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent))
import verify
def j(p):return json.loads(p.read_bytes())
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def records():
    products={}
    for stem in ('builder-completed','builder-rejected','combined-seal'):
        meta=j(D/(stem+'.json'));p=D/(stem+'.zip')
        assert 'sha256:'+sha(p)==meta['digest'] and p.stat().st_size==meta['size_in_bytes']
        with zipfile.ZipFile(p) as z:
            if stem=='builder-completed':
                for name,commit in [('parent','7277e6cdaba44c43294a07c0661fc8e69fd8e3e7'),('matched294','2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c')]:
                    version=z.read('reports/'+name+'-version.txt').decode();assert 'commit-hash: '+commit+'\n' in version and 'release: 1.99.0-dev\n' in version
                    rows=[json.loads(l) for l in gzip.decompress(z.read('reports/'+name+'.stdout.gz')).splitlines()]
                    leaf,=[r for r in rows if r['reason']=='compiler-artifact' and r['target']['kind']==['bin'] and r['target']['name']=='cargo'];assert not leaf['fresh'] and {'all-static','ohm-defaults'}<=set(leaf['features'])
                    assert rows[-1]=={'reason':'build-finished','success':True}
                    products[name]=commit
            if stem=='combined-seal':
                m=json.loads(z.read('build.json'))
                assert m['candidate']=='b76dc8006155d48a8cd7d6c5543acb9c18e2ce4b' and m['compiled']==m['delivered']=='f1a88bf5fb2bf431eeea068455d9d4e98dcfbfee3dc381ee47cc7c96df3e128f'
                products['combined']=m['candidate']
    return products
def native_processes(directory,runtime,visit):
    raw=gzip.decompress((directory/'exec-and-provider-open.gz').read_bytes()).decode()
    native=runtime['rustc']['path'];wild=runtime['wild']['path']
    seen={};rustup={};link_images=collections.defaultdict(list)
    for line in raw.splitlines():
        m=re.match(r'^\S+ (\d+) execve\("([^"]+)", (\[.*\]), [^\n]+\)\s+= 0$',line)
        if not m:continue
        pid=int(m[1]);exe=m[2]
        if exe!=native and not exe.endswith('/shims/rustc') and Path(exe).name not in ('ld','ld.bfd','ld.lld','rust-lld','wild','ld.mold','ld.gold'):continue
        args=ast.literal_eval(m[3])
        if exe==native or exe.endswith('/shims/rustc'):
            if '--crate-name' not in args or args[args.index('--crate-name')+1]=='___':continue
            name=args[args.index('--crate-name')+1]
            assert len([s for s in args if s.startswith('--emit=')])==1
            target=seen if exe==native else rustup
            assert pid not in target;target[pid]=(name,tuple(args[1:]))
        else:
            if '-o' in args:
                link_images[pid].append((exe,args[args.index('-o')+1]))
    assert seen==rustup and len(seen)*2==len(visit['rustcs'])
    owned=collections.Counter(v[0] for v in seen.values())
    assert collections.Counter({n:c*2 for n,c in owned.items()})==collections.Counter(visit['rustcs'])
    for chain in link_images.values():
        assert len({o for _,o in chain})==1
        assert [e for e,_ in chain]==[wild] or [Path(e).name for e,_ in chain]==['ld.lld','rust-lld']
    assert sum(len(v) for v in link_images.values())==visit['links']
    return dict(full_rustcs=sorted(v[0] for v in seen.values() if not any(a in ('-Zlink-only','link-only') or a.startswith('-Zlink-only=') for a in v[1])),
                link_only_rustcs=sorted(v[0] for v in seen.values() if any(a in ('-Zlink-only','link-only') or a.startswith('-Zlink-only=') for a in v[1])),
                compiler_pids=sorted(seen),linker_pids=sorted(link_images),
                linkers=[Path(chain[-1][0]).name for chain in link_images.values()])
def reopen(archive):
    products=records();meta=j(D/'native.json')
    assert 'sha256:'+sha(archive)==meta['digest'] and archive.stat().st_size==meta['size_in_bytes']
    root='private/host-unicode-wild-dir-v1/results/'
    with tempfile.TemporaryDirectory(prefix='ohm-provider-read-') as t,zipfile.ZipFile(archive) as z:
        dest=Path(t)
        assert len(set(z.namelist()))==len(z.namelist()) and sum(x.file_size for x in z.infolist())<2*(1<<30)
        for x in z.infolist():
            if x.is_dir():continue
            assert x.filename.startswith(('private/','receipts/','input/','terminal.json')) and '..' not in Path(x.filename).parts
            if not x.filename.startswith(root):continue
            path=dest/x.filename.removeprefix(root);path.parent.mkdir(exist_ok=True,parents=True)
            path.write_bytes(z.read(x))
        result=verify.verify(dest)
        for name,commit in products.items():assert result['roles'][name]['head']==commit
        for name in ('parent','matched294','combined'):
            p=D/(name+'.json');cold=json.loads(z.read('input/'+p.name));assert result['roles'][name]['cargo']==cold['compiled']
        supplied=json.loads(z.read('input/artifacts.json'));assert {d['id'] for d in supplied}=={13023460138,13022058572}
        signed=json.loads(z.read('receipts/21/custody.json'));assert signed['archive_sha256']=='6f550de85f95440a61b5bd1a9d2ab0528d4fcaf674fdc008f5e986d2138be6c4'
        assert result==json.loads(z.read('terminal.json'))
        for role,data in result['roles'].items():
            runtime=json.loads((dest/role/'runtime.json').read_bytes())
            for phase,row in data['visits'].items():
                row['native']=native_processes(dest/role/phase,runtime,row)
                row['basename_rustc_execs_including_rustup']=row.pop('rustcs')
                row['linker_execs_including_driver_shims']=row.pop('links')
        return result
if __name__=='__main__':
    print(json.dumps(reopen(Path(sys.argv[1])),indent=2,sort_keys=True))
