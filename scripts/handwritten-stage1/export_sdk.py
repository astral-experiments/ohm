"""Ship regular stage-built compiler, driver, LLVM and rustlib products as an authenticated SDK."""
import hashlib,json,os,re,shutil,stat,subprocess,tarfile
from pathlib import Path
import gate as g

HOST="x86_64-unknown-linux-gnu"
def files(sdk,ident):
    ns={p.relative_to(sdk).as_posix():p for d in [sdk/'lib/rustlib'/HOST/'lib',sdk/'lib/rustlib'/HOST/'bin'] for p in d.rglob('*') if p.is_file()}
    ns.update({n:sdk/n for n in ('bin/rustc','bin/rustdoc')})
    ns.update({p.relative_to(sdk).as_posix():p for p in (sdk/'lib').iterdir() if p.is_file() and (p.name.endswith('.so') or '.so.' in p.name)})
    libs=subprocess.check_output(['ldd',sdk/'bin/rustc'],env={'PATH':'/usr/bin:/bin','LC_ALL':'C','LD_LIBRARY_PATH':str(sdk/'lib')},text=True)
    for lib,fp in re.findall(r'(?m)^\s*(libLLVM\S+) => (\S+)',libs):
        assert lib in ident['resolved_llvm'] and g.file_hash(Path(fp))==ident['resolved_llvm'][lib]
        ns['lib/'+lib]=Path(fp)
    assert len(ident['resolved_llvm'])==1 and set(ident['resolved_llvm'])<={Path(n).name for n in ns}
    assert ns['lib/'+ident['driver']].samefile(sdk/'lib'/ident['driver']) and 30<=len(ns)<=250
    assert sum(p.stat().st_size for p in ns.values())<4<<30
    for crate in ('alloc','core','std','test','proc_macro'):
        assert any(n.startswith('lib/rustlib/'+HOST+'/lib/lib'+crate+'-') and n.endswith('.rlib') for n in ns)
    return ns

def run(role,sdk,context,arm,bundle,qa,w,ident):
    # Build and relocation include every target .rlib/.rmeta and source-native libstd/driver.
    rows={};paths=files(sdk,ident);out=w/'stage1-capsule';out.mkdir()
    archive=out/'sdk.tar.zst'
    with archive.open('xb') as f:
        compressor=subprocess.Popen(['zstd','-q','-3','-T2','-c'],stdin=subprocess.PIPE,stdout=f)
        assert compressor.stdin is not None
        with tarfile.open(fileobj=compressor.stdin,mode='w|',format=tarfile.PAX_FORMAT) as t:
            for name,p in sorted(paths.items()):
                fsz=p.stat().st_size;mode=0o755 if p.stat().st_mode&0o111 else 0o644
                assert p.resolve(strict=True).is_file() and 0<fsz<1<<30 and not name.startswith(('/', '../')) and '..' not in Path(name).parts
                row=tarfile.TarInfo(name);row.size=fsz;row.mode=mode
                with p.open('rb') as inp:t.addfile(row,inp)
                rows[name]={'sha256':g.file_hash(p),'bytes':fsz,'mode':mode}
        compressor.stdin.close();assert compressor.wait(timeout=120)==0
    assert 30<<20<archive.stat().st_size<1000<<20
    g.put(qa/'sdk-inventory.json',rows)
    assert rows['lib/'+ident['driver']]['sha256']==ident['driver_sha256'] and rows['bin/rustc']['sha256']==ident['rustc_sha256']
    evidence={p.name:g.file_hash(p)for p in qa.iterdir() if p.is_file()}
    g.put(qa/'role.json',{'role':role,'source':arm,'github':context,'carrier_sha256':bundle,'qa':evidence,'archive_sha256':g.file_hash(archive),'archive_bytes':archive.stat().st_size,'classification':'optimized stage1; PGO, BOLT and compiler LTO disabled'})
    for f in sorted(qa.iterdir()):
        assert f.is_file() and f.stat().st_size<32<<20;shutil.copyfile(f,out/f.name)
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as f:
        f.write('inner='+g.file_hash(archive)+'\n')
