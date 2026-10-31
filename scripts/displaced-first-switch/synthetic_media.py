"""Construct clearly labeled synthetic two-ZIP media to exercise every endpoint of the offline reader."""
import gzip,hashlib,json,os,shutil,subprocess,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import acquire,review,tables as t
import mount_evidence as m

def test(base,initial,old,first,shadow,out):
    here=base/'synthetic-media';here.mkdir();payloads=here/'streams'
    manifest=acquire.materialize(base,shadow,first,out,payloads)
    gz=lambda o:gzip.compress(json.dumps(o).encode(),mtime=0)
    text=lambda o:json.dumps(o)
    src=here/'receipts.zip';stream=here/'streams.zip'
    archive={str(p.relative_to(shadow)):t.shape(p.lstat()) for p in [shadow,*shadow.rglob('*')]}
    inputs={tuple(r[:2]):r[4]*512 for r in first.values()}
    allocated=sum(inputs.values());peak=t.allocated_tree(shadow);by_size={}
    with zipfile.ZipFile(src,'x',zipfile.ZIP_DEFLATED) as z:
        def store(n, data):z.writestr(n,data)
        full_a=full_b=typed=None
        for image in ('true','false','echo'):
            p=Path('/usr/bin')/image
            digest=t.sha(p);by_size[image]=dict(whole=digest,size=p.stat().st_size)
            store('native-bodies/'+digest+'.zst',subprocess.check_output(['zstd','-q','-c',p]))
        visit={}
        for phase,num,kind in [('cold-A',375,'true'),('empty-B',375,'false'),('first-B',20,'false')]:
            desc=by_size[kind];reader=by_size['echo']
            visit[phase]={'allocated':allocated,'dirty':num,'cli':desc['whole'],'reader':reader['whole']}
            store(phase+'/visit.json',text(visit[phase]))
            store(phase+'/cargo.json.gz',gz({'exit':0,'observer_argv':None}))
            typed="Expr="+("64" if phase=="cold-A" else "56")+" valid=1 rejected"
            store(phase+'/native.json.gz',gz({'cli':desc,'reader':reader,'typed':typed}))
            store(phase+'/reader-run.stdout.gz',gzip.compress((typed+"\n").encode()))
            store(phase+'/roster.json.gz',gz({'dirty':list(range(num)),'members':list(range(375))}))
        for phase,led in [('cold-A',initial),('first-B',first),('post-shadow',first)]:store(phase+'/path-inodes.json.gz',gz(led))
        mount=m.capture(base,shadow,first)
        store('mount-inodes.json.gz',gz(mount));store('mount-admission.json',text(m.validate(mount,first,archive)))
        store('shadow-find.txt',subprocess.check_output(['/usr/bin/find',shadow,'-printf','%D %i %b\\n']))
        store('shadow-inodes.json.gz',gz(archive));store('pre-switch-cold-source.json',text(old));store('tables.json',text(out))
        du=subprocess.check_output(['/usr/bin/du','-sB1','--total','--',base/'target',base/'build',shadow],text=True)
        store('coexistence-du.txt',du)
        store('complete.json',text(dict(qualified=True,cold=visit['cold-A'],empty=visit['empty-B'],first=visit['first-B'],shadow_allocated=peak,post_original=allocated,stream_index_sha256=t.sha(payloads/'streams.json'),du_coexistence=du)))
    with zipfile.ZipFile(stream,'x') as z:
        for p in payloads.rglob('*'):
            if p.is_file():z.write(p,str(p.relative_to(payloads)))
    result=review.read(src,stream)
    assert result['native_complete_images']==3 and result['real_displaced_crates']==20 and result['decoded_older']==40 and result['native_current']==40
    copied=here/'changed.zip'
    with zipfile.ZipFile(stream) as z, zipfile.ZipFile(copied,'x') as y:
        name=next(iter(manifest))
        for n in z.namelist():
            data=z.read(n)
            if n==name: data=data[:-2]+bytes([data[-2]^1,data[-1]])
            y.writestr(n,data)
    try:review.read(src,copied)
    except ValueError as e:assert 'stream hash' in str(e)
    else:raise AssertionError('unrecorded replacement bytes accepted')
    return {'positive':result,'stored-byte-tamper-rejected':True}
