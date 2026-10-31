"""Run the positive and rejection controls with the actual source-extracted fast encoder."""
import collections, io, json, os, stat, sys, zlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import tables as t

def ledger(root):
    return {str(p.relative_to(root)):t.shape(p.lstat()) for top in [root/'target',root/'build'] for p in (top,*top.rglob('*'))}

def main(exe,base):
    base.mkdir();(base/'target').mkdir();(base/'build').mkdir()
    prefix=base/'target/debug/incremental/test';prefix.mkdir(parents=True)
    (base/'detached').mkdir()
    units=[]
    for ix,name in enumerate(sorted(t.UNITS.elements())):
        u=prefix/(name+'-'+str(ix));a=u/'s-ax-_00000000000000aa_sa-zz';a.mkdir(parents=True)
        units.append((ix,u,a))
        for k,stem in t.KINDS.items():
            data=b'RSIC'+bytes([ix+32,ord(k)])*34600
            p=a/(stem+'.bin');p.write_bytes(data);os.link(p,a/('ohm-build-'+stem+'.bin'))
    initial=ledger(base);old=t.cold(base,initial)
    for ix,u,a in units:
        b=u/'s-bx-_00000000000000bb_sb-yy';b.mkdir()
        for k,stem in t.KINDS.items():
            source=base/'detached'/(u.name+stem)
            source.write_bytes(b'RSIC'+bytes([ix+65,ord(k)])*34400)
            with source.open('rb') as f: t.encode(exe,f,k,b.name.rsplit('-',1)[0],b/('ohm-packed-'+stem+'.bin'))
    first=ledger(base); shadow=base/'displaced-shadow';tmp=base/'scratch'
    out=t.observe(base,initial,first,old,shadow,tmp,exe)
    assert len(out)==20 and len(list(shadow.glob('*/*.bin')))==40 and ledger(base)==first
    report={'synthetic_only':True,'real_rust_fast_encoder':t.sha(exe),'old_encoded_and_roundtripped':40,'current_reencoded_byte_identically':40,'peak_shadow_allocated':t.allocated_tree(shadow),'rejections':[]}
    from synthetic_media import test
    report["offline_two_zip_fixture"]=test(base,initial,old,first,shadow,out)
    def reject(name,op):
        try:op()
        except (ValueError,zlib.error,FileNotFoundError,subprocess.SubprocessError):
            report['rejections'].append(name);return
        raise AssertionError(name)
    import subprocess
    firstunit=sorted(out)[0];r=out[firstunit];o=r['streams']['G']
    f=shadow/o['shadow'];body=f.read_bytes();tag=Path(r['A']).name.rsplit('-',1)[0]
    for n,changed,kind,session in [('trailing',body+b'x','G',tag),('truncated',body[:-1],'G',tag),('second stream',body+body,'G',tag),('wrong G/Q',body,'Q',tag),('wrong producer',body,'G',tag+'a')]:
        reject(n,lambda:t.decode(io.BytesIO(changed),kind,session))
    data=zlib.decompress(body)
    for ix,byte,reason in [(0,2,'version'),(2,5,'alias mask'),(3,0,'decoded length')]:
        corrupt=bytearray(data);corrupt[ix]=byte
        if bytes(corrupt)==data: corrupt[ix]^=1
        reject(reason,lambda:t.decode(io.BytesIO(zlib.compress(corrupt)), 'G',tag))
    row=first[o['native_B']['path']]; t.need(row[2]==1,'test current')
    foreign=base/'target/foreign';os.link(base/o['raw']['path'],foreign)
    reject('external hardlink',lambda:t.physical_raw(base,ledger(base),t.names(ledger(base)),r['A'],'G'))
    foreign.unlink()
    p=base/o['native_B']['path'];p.write_bytes(zlib.compress(zlib.decompress(p.read_bytes()),9))
    reject('independent zlib backend disagrees with real B',lambda:t.observe(base,initial,ledger(base),old,base/'shadow-bad',base/'scratch-bad',exe))
    target=base/o['raw']['path']
    with target.open('r+b') as raw:raw.seek(10);raw.write(b'x')
    reject('A replaced while B was built',lambda:t.observe(base,initial,ledger(base),old,base/'shadow-changed',base/'scratch-changed',exe))
    print(json.dumps(report,sort_keys=True))
if __name__=='__main__':main(*map(Path,sys.argv[1:]))
