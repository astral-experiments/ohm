"""Reopen both original release-integration Apple artifacts without network access or a compiler."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
SIGNED='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
MERGED='fd55a13d0220748794ba3c7c9556ef8ceed8591f'
ARCHIVES={'cargo':'c8776e7c63df7ad25fb4089809d41953b8016082949c83eacdbf90198462a94d','unicode':'112db9cd4e1d29c1b0b3d8a8cb9b82d8ede9cad45bd25ba193fa1d87f0a30e67'}
H=lambda b:hashlib.sha256(b).hexdigest()
LOAD=lambda z,k:json.loads(z.read(k))
def checkfile(path,expected):
    with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==expected
def verify(cargo,unicode):
    checkfile(cargo,ARCHIVES['cargo']);checkfile(unicode,ARCHIVES['unicode'])
    with ZipFile(cargo) as z:
        assert z.testzip() is None and set(z.namelist())=={'cargo.gz','manifest.json','build.json'}
        mf=LOAD(z,'manifest.json');s=LOAD(z,'build.json');raw=gzip.decompress(z.read('cargo.gz'))
        assert mf['source']==s['source']['commit']==MERGED and s['source']['parents']==[SIGNED,'c18e91b514b2c4e4966c9ab03232c804af3e1b57']
        assert s['source']['entries']==3114 and s['source']['tree']=='fc9358ddef14d790c6bc6d69f2dc7d465a413ef3'
        assert mf['compressed_sha256']==H(z.read('cargo.gz')) and mf['build_sha256']==H(z.read('build.json'))
        assert mf['sha256']==s['binary']['sha256']==H(raw)=='9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d'
        assert raw[:8]==bytes.fromhex('cffaedfe0c000001') and mf['bytes']==len(raw)==40700864
        assert 'aarch64-apple-darwin' in s['version'] and MERGED in s['version'] and SIGNED in s['builder'] and set(s['features'])>={'all-static','ohm-defaults'}
        published={'cargo':H(raw),'source-tree':s['source']['tree'],'packaged_compiler':s['builder_rustc']['sha256'],'signed_builder':s['builder_cargo']['sha256']}
    with ZipFile(unicode) as z:
        assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))==337
        t=LOAD(z,'unicode/terminal.json')
        assert H(z.read('unicode/terminal.json'))=='f2f5f4dd389cda6b1c8687d67b83a9953e6e36d20253417236bde6bc7741b2b7'
        assert t['signed']==SIGNED and t['integrated']==MERGED and t['cases']==32
        orders={'cold':(16,1),'first':(0,0),'repeat':(0,0),'edit':(2,1),'edit-repeat':(0,0),'empty-edit':(16,1),'bad':(1,0),'repair':(2,1)}
        rows={};files={}
        for selection,phases in t['assignments'].items():
            assert selection in {f'{c}-{target}' for c in ('signed','integrated') for target in ('host','explicit')}
            out={};rows[selection]=out
            for phase in orders:
                prefix=f'unicode/{selection}/{phase}/'
                q=LOAD(z,prefix+'verified.json');assert H(z.read(prefix+'verified.json'))==phases[phase]
                gz=lambda n:gzip.decompress(z.read(prefix+n+'.gz'))
                so,err,events=gz('stdout'),gz('stderr'),gz('exec.json')
                assert q['streams']['streams']=={'stdout':H(so),'stderr':H(err),'native_events':H(events)}
                jobs=json.loads(events);typed=list(map(json.loads,so.splitlines()));exe=[]
                for event in jobs:
                    argv=event['argv']
                    if PurePosixPath(event['path']).name=='rustc' and '--crate-name' in argv:
                        crate=argv[argv.index('--crate-name')+1]
                        if crate!='___':exe.append([crate,'link-only' if any('link-only' in q for q in argv) else 'full'])
                ld=[q for q in jobs if PurePosixPath(q['path']).name in ('ld','ld-prime','ld64','ld-classic')]
                assert sorted([n for n,t in exe if t=='full'])==q['work']['full'] and sorted([n for n,t in exe if t=='link-only'])==q['work']['link_only']==[]
                assert [j['argv'] for j in ld]==[v['argv'] for v in q['work']['linkers']] and all('/Xcode' in j['path'] and x['stock'] for j,x in zip(ld,q['work']['linkers']))
                assert (len(exe),len(ld))==orders[phase] and q['status']==(101 if phase=='bad' else 0) and typed[-1]=={'reason':'build-finished','success':phase!='bad'}
                if phase=='bad':assert any((m['message'].get('code') or {}).get('code')=='E0425' for m in typed if m['reason']=='compiler-message')
                else:
                    want=b'None\nSome(0)\nSome(0)\n' if phase in ('edit','edit-repeat','empty-edit') else b'Some(0)\nNone\nSome(0)\n'
                    assert q['reader_exit']==0 and gz('reader.stdout')==want and not gz('reader.stderr')
                    assert len(q['generated'])==3 and q['typed']==sum(x['reason']=='compiler-artifact' for x in typed)
                    files[selection,phase]=q['generated']
                if phase in ('first','repeat','edit-repeat'):assert not q['dirty'] and not exe and not ld
                out[phase]={'full':[n for n,k in exe],'stock_links':len(ld),'cargo_status':q['status'],'typed':q.get('typed'),'cargo_stdout':H(so),'cargo_stderr':H(err),'kernel_exec':H(events)}
            baseline=files[selection,'cold'];edited=files[selection,'edit']
            assert all(files[selection,p]==baseline for p in ('first','repeat','repair')) and all(files[selection,p]==edited for p in ('edit-repeat','empty-edit'))
            assert sorted(k for k in baseline if baseline[k]!=edited[k])==['generated_alias.rs']
        assert len(rows)==4
        return {'images':published,'commands':32,'rows':rows,'intake':41108831046}
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('cargo',type=Path);parser.add_argument('unicode',type=Path);parser.add_argument('--output',type=Path)
    p=parser.parse_args();result=verify(p.cargo,p.unicode);data=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
    if p.output:
        if p.output.exists():assert p.output.read_bytes()==data
        else:p.output.write_bytes(data)
    print('Verified %d ordinary Cargo commands, all source-product switches and both native inputs.'%result['commands'])
