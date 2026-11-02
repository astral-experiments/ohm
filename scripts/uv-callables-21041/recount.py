"""Recount the actual v9 rustc provider intervals for each registered owner and recheck binary and diagnostic outcomes."""
from pathlib import Path,PurePosixPath
from zipfile import ZipFile
import collections,hashlib,json,runpy,struct
H=Path(__file__).resolve().parent;SRC=H
OWNERS=('only_named','only_ctor','only_assoc','only_closure')
def sha(data):return hashlib.sha256(data).hexdigest()
def actual(source,role):
    assert role in ('candidate','control')
    parsefile=SRC/'profile_v9.py'
    assert sha(parsefile.read_bytes())==json.loads((SRC/'source-role.json').read_bytes())['sha256']['profile_v9.py']
    parser=runpy.run_path(str(parsefile))['Profile']
    if source.is_file():
        with ZipFile(source)as z:
            infos=z.infolist();names=[v.filename for v in infos]
            assert len(names)==len(set(names))<256 and sum(v.file_size for v in infos)<64<<20
            assert all(not PurePosixPath(n).is_absolute()and '..'not in PurePosixPath(n).parts and '\\'not in n for n in names)and z.testzip()is None
            members={n:z.read(n)for n in names}
    else:
        members={f.relative_to(source).as_posix():f.read_bytes()for f in source.rglob('*')if f.is_file()and(f.suffix in ('.mm_profdata','.json')or f.name.endswith('.stderr'))}
    proof=json.loads(members['qualified.json']);log=json.loads(members['observed.json'])
    assert proof['receipt_sha256']==sha(members['observed.json'])and proof['role']==log['role']==role
    phases=log['runs'];assert set(phases)=={'a','cold','same','toggle','toggle-plain','signature','signature-cold'}
    counted={}
    for name,count in [('a',1),('cold',1),('same',0),('toggle',int(role=='control'))]:
        row=phases[name]['read'];profile,=[v for k,v in members.items() if k.startswith(name+'/profile/')and k.endswith('.mm_profdata')]
        assert sha(profile)==row['sha256']
        p=parser(profile);frequency=collections.Counter();activity=0
        for t,i,tid,lo,hi,flags in struct.iter_unpack('<QQIIII',memoryview(p.entries)[8:]):
            start=lo|((flags&0xffff0000)<<16);end=hi|((flags&0xffff)<<32)
            if not start<end<0xfffffffffffe:continue
            kind=p.label(t)
            if kind=='GenericActivity':activity+=1
            if kind=='Query':
                label=p.label(i)
                if label.startswith('typeck_root\x1e'):frequency[label]+=1
        selected={key:frequency['typeck_root\x1ereader::'+key]for key in OWNERS}
        assert activity>0 and dict(frequency)==row['counts'] and selected==row['selected']==dict.fromkeys(OWNERS,count),(name,selected)
        counted[name]={'selected':selected,'actual_queries':sum(frequency.values()),'profile_sha256':sha(profile)}
    for k in ('binary','value'):assert phases['cold'][k]==phases['toggle'][k]==phases['toggle-plain'][k]
    for k in ('signature','signature-cold'):
        v=phases[k]['reader'];assert v['returncode']!=0 and v['codes']==['E0061']
    assert phases['signature']['reader']['stderr_sha256']==phases['signature-cold']['reader']['stderr_sha256']
    assert proof['unrelated_typeck_provider_count']==counted['toggle']['selected'] and proof['warm_cold_binary']==phases['cold']['binary'] and proof['genuine_signature_diagnostic']=='E0061'
    return {'role':role,'profiles':counted,'behavior':phases['toggle']['value'],'warm_cold_binary':proof['warm_cold_binary'],'genuine_E0061':phases['signature']['reader']['stderr_sha256'],'source_qualified_sha256':sha(members['qualified.json'])}
if __name__=='__main__':
    import sys
    src,role=Path(sys.argv[1]),sys.argv[2];print(json.dumps(actual(src,role),sort_keys=True))
