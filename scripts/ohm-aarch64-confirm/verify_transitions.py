"""Independently read each native Cargo namespace and all physical runtime identity snapshots."""
from collections import Counter
from hashlib import sha256
import gzip,io,json,re,runpy,sys,tarfile,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
TRACE=runpy.run_path(str(HERE/'complete-native-roster.py'))['inspect']
ORDER='AANNMMAMNA'
H=lambda b:sha256(b).hexdigest()

class Directory:
    def __init__(self,p):self.root=Path(p)
    def read(self,n):return (self.root/n).read_bytes()

def verify(pack):
    get=pack.read
    j=lambda s:json.loads(get(s))
    subjects={k:j('subject-'+k+'.json') for k in 'ANM'}
    original=j('all-named-start-identities.json')
    names=set(subjects['A']['files']);(driver,)= [n for n in names if n.startswith('lib/librustc_driver')]
    assert len(names)==119 and set(original)==set('ANM')
    for k in 'ANM':
        assert set(original[k])==set(subjects[k]['files'])==names
        for n,v in original[k].items():
            assert [v['sha256'],v['size'],v['mode']]==subjects[k]['files'][n]
            assert set(v)=={'dev','ino','ctime_ns','mtime_ns','size','mode','nlink','sha256'}
            if n==driver: assert v['nlink']==1
            else: assert v['nlink']==3 and all(original[other][n]==v for other in 'ANM')
    assert len({(role[driver]['dev'],role[driver]['ino']) for role in original.values()})==3
    log=j('all-nine-actual-transitions.json');observed={};prior=None;rows=[]
    assert log['sequence']==ORDER and len(log['visits'])==len(ORDER)
    for i,(role,v) in enumerate(zip(ORDER,log['visits'])):
        assert v['role']==role and v['from']==prior
        base=f'selector-visits/{i+1:02d}-{role}'
        snap=v['selector']
        state=get(snap['snapshot'])
        assert H(state)==snap['sha256'];state=json.loads(state)
        assert state['to']==role and state['files']==original[role] and state['driver']==original[role][driver]
        assert state['from']==('A' if i==0 else prior)
        assert snap['driver']==state['driver'] and snap['members']==state['members']==119
        args=j(base+'/cargo/command.json');native=j(base+'/native.json')
        assert v['native_stream']==H(get(base+'/native.json')) and v['trace']==H(get(base+'/exec.tar.gz'))
        names_count=TRACE(pack,base,native)
        assert H(gzip.decompress(get(base+'/cargo/stderr.gz')))==args['stderr']
        assert native['cargo'][0]['argv'][1:]==['build','-p','ruff_text_size','--target','aarch64-unknown-linux-gnu','--locked','--offline','-j4','--message-format=json']
        assert native['cargo']==[v['true_cargo']] and args['exit']==0 and native['cargo'][0]['terminal']==[0]
        raw=gzip.decompress(get(base+'/cargo/stdout.gz'));assert H(raw)==args['stdout']
        events=[json.loads(l) for l in raw.splitlines()]
        assert events[-1]=={'reason':'build-finished','success':True}
        result, = [r for r in events if r.get('reason')=='compiler-artifact' and r['target']['name']=='ruff_text_size']
        meta,=[n for n in result['filenames'] if n.endswith('.rmeta')]
        shard,=re.findall(r'/(v2-[0-9a-f]{16})/',meta)
        assert v['actual']==observed.setdefault(role,shard)==shard and v['directory']==str(Path(meta).parent)
        assert H(get('objects/'+v['rmeta']+'.rmeta'))==v['rmeta'] and H(get('objects/'+v['rlib']+'.rlib'))==v['rlib']
        assert [r['crate'] for r in native['rustcs']]==v['physical_rustcs']
        assert all('/'+shard+'/' in r['argv'][r['argv'].index('--out-dir')+1] for r in native['rustcs'] if r['crate']=='ruff_text_size')
        rows.append({'previous':prior,'role':role,'actual':shard,'physical':names_count,'driver':state['driver'],'snapshot':H(get(snap['snapshot']))})
        prior=role
    assert Counter(ORDER[i:i+2] for i in range(len(ORDER)-1))==Counter(a+b for a in 'ANM' for b in 'ANM')
    assert observed==log['namespaces'] and len(set(observed.values()))==3
    return {'order':ORDER,'namespaces':observed,'all_file_inodes_and_times_stable':119,'common_physical_members':118,'visits':rows,
            'initial':H(get('all-named-start-identities.json')),'observations':H(get('all-nine-actual-transitions.json'))}
if __name__=='__main__':
    arg,out=map(Path,sys.argv[1:])
    if arg.is_dir():result=verify(Directory(arg))
    else:
        with zipfile.ZipFile(arg) as z:result=verify(z)
    body=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
    out.open('xb').write(body);print(H(body),result['namespaces'])
