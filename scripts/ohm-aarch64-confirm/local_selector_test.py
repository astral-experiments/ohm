"""Exercise parent-directory selection, including a genuine rejected physical argv and accepted controls."""
import copy,gzip,hashlib,json,os,runpy,shutil,sys,tempfile,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
Parked=runpy.run_path(str(HERE/'parked.py'))['Parked']
H=lambda b:hashlib.sha256(b).hexdigest()
def loc(testdir):
    store=testdir/'donors';store.mkdir()
    driver='lib/librustc_driver-fixture.so';names=['bin/rustc',driver,'lib/libunrelated.rlib']
    subjects={}
    for k in 'ANM':
        subject=store/k;subjects[k]={}
        for n in names:
            data=(n+(k if n==driver else '')).encode()*73;p=subject/n;p.parent.mkdir(exist_ok=True,parents=True)
            p.write_bytes(data);p.chmod(0o755 if n.startswith('bin/') else 0o644)
            subjects[k][n]=[H(data),len(data),p.stat().st_mode&0o777]
    active=Parked(testdir/'parking',testdir/'visible',subjects,{k:store/k for k in 'ANM'},driver)
    for k in 'AANNMMAMNA':assert active.select(k)['files']==active.initial[k]
    keep=active.initial['A'][driver];p=active.visible/driver;tmp=p.with_name('new')
    shutil.copyfile(p,tmp);tmp.chmod(keep['mode']);os.replace(tmp,p)
    assert H(p.read_bytes())==keep['sha256'] and p.stat().st_ino!=keep['ino']
    try:active.select('A')
    except AssertionError:pass
    else:raise AssertionError('damaged the active file, yet selection admitted it')
def evidence(d):
    rejected=json.loads((d/'run-41069158147/physical-namespace-mismatch-02.json').read_bytes())
    bad=rejected['profiles']['first-real-edit']['real_compilers']
    assert {k:len(s['only_changes']) for k,s in bad.items()}=={'zmij':2,'compact_str':13,'ruff_python_ast':42}
    for k,r in bad.items():
        expect=' '.join(r['original_argv']);got=r['actual_complete_callgrind_cmd'];assert expect!=got
        assert expect.replace('/v2-'+r['prior_namespace']+'/','/v2-'+r['counted_namespace']+'/')==got
    observed=0
    for archive in ('run-41058986651/gnu-register-ruff-screen.zip','run-41064927474/gnu-compact-input-ruff-complete.zip'):
        with zipfile.ZipFile(d/archive) as z:
            for lab in ('mirror1-P','mirror1-C','mirror2-C','mirror2-P'):
                cases=[(lab+'/counter/whole','unchanged-1')]
                if '41064927474' in archive:cases+=[(lab+'-edit-cycle/first-real-edit','edit'),(lab+'-edit-cycle/immediate-repeat','unchanged-1')]
                for prefix,phase in cases:
                    native=json.loads(z.read(lab+'/'+phase+'/native.json'));want={'cargo':native['cargo'][0]['argv']}|{r['crate']:r['argv'] for r in native['rustcs']}
                    seen=json.loads(z.read(prefix+'/observed.json'))['processes'];assert set(want)==set(seen)
                    for r,s in seen.items():
                        with gzip.open(z.open(prefix+'/profiles/cg.'+str(s['pid'])+'.gz')) as f:
                            cmd=next(l[4:].decode().strip() for l in f if l.startswith(b'cmd:'))
                        assert cmd==' '.join(want[r])==' '.join(s['argv']);observed+=1
    return observed
if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='ohm-parked-selector-') as tmp:loc(Path(tmp))
    print('every physical role/self transition passed; same-byte inode replacement rejected')
    if len(sys.argv)>1:print('exact previous raw process tuples accepted',evidence(Path(sys.argv[1])), 'three original failing tuples rejected')
