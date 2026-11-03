"""Independently derive the ordinary full-Ruff ceiling and two kernel ELF-generation controls."""
from pathlib import Path
from collections import Counter
import copy
import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
def digest(b):return hashlib.sha256(b).hexdigest()
def budget(tree,records,argv):
    epochs=[l.split()for l in records.decode().splitlines()]
    whole,=[e for e in epochs if e[0]=='W']
    assert list(map(int,whole[1:]))==tree['outer'] and int(whole[2])==int(whole[3])>0 and whole[-1]=='0'
    roles=[r for r in tree['roles']if r['trigger']=='exec']
    roster=Counter(r['mode']for r in roles)
    full={r['crate']:r for r in roles if r['mode']=='full'}
    assert set(full)=={'ron','insta','insta_cmd'} and roster['Wild']==roster['link-only']==50
    result={}
    for name,r in full.items():
        args=argv[r['argv']]
        assert digest(args)==r['argv_sha256']
        a=args.split(b'\0');assert a[-1]==b'' and a[a.index(b'--crate-name')+1].decode()==name
        counters=[list(map(int,e[4:]))for e in epochs if e[0]=='C'and int(e[1])==r['epoch'] and int(e[2])==r['pid']]
        totals=list(map(sum,zip(*counters,strict=True)))
        assert totals==r['counter'] and totals[1]==totals[2]>0 and totals[0]>0
        result[name]=totals[0]
    n=int(whole[1]);x=result['ron']
    return {'whole':n,'full':result,'links':roster['Wild'],'ron_share':x/n,'maximum_if_ron_were_free':n/(n-x)}

def default(ordinary,ids,gate,binding,fds):
    assert gate.split()[:2]==['loaded-generation-refused','70']
    rejected=[l.split()for l in binding.splitlines()]
    assert rejected[0][0]=='refused'and len(rejected)==4 and len(ordinary['samples'])>0
    assert fds['limit']==[131072,131072]and len({tuple(fds['descriptors'][str(x)])for x in range(190,212)})==22
    out={}
    for row in rejected[1:]:
        i,device,ino,size,leased,segments=map(int,row)
        current,=[k for k in ordinary['files']if k[2]==ino and k[3]==size]
        assert leased==1 and segments==0 and current[1]=='00:20'and device==33
        name=Path(current[0]).name;rel=next(k for k in ids if Path(k).name==name)
        assert ids[rel][0]==current[-1] and ids[rel][2:]==[device,ino]
        out[name]={'ino':ino,'bytes':size,'fstat':device,'mapped':32}
    assert len(out)==3
    return out

def ext4(sample,library):
    info=sample['maps'];assert len(info)==12 and len(sample['owners'])==1
    rows={}
    for name,row in info.items():
        f=row['physical']
        assert row['dev']==row['held_dev']==f['dev']==[253,1] and row['ino']==row['held_ino']==f['ino'] and f['fstype']==0xef53
        if row['uid']!=1000:
            assert f['verity']==[-1,95]and f['seals']==[-1,22]
            rows[Path(name).name]=row['sha256']
    assert len(rows)==9 and 'libc.so.6'in rows and rows['libz.so.1.3']!=library['libz.so.1.3'][-1]
    return rows

def main():
    cfg=json.loads((HERE/'members.json').read_bytes());origin=json.loads((HERE/'origins.json').read_bytes())
    raw=subprocess.check_output(['zstd','-qdc',HERE/'platform-originals.tar.zst']);assert len(raw)<50*2**20
    data={}
    with tarfile.open(fileobj=io.BytesIO(raw))as archive:
        for m in archive:
            assert m.isfile()and m.name in cfg and m.name not in data
            v=archive.extractfile(m).read();assert [len(v),digest(v)]==cfg[m.name];data[m.name]=v
    assert set(cfg)==set(data)
    j=lambda k:json.loads(gzip.decompress(data[k])if k.endswith('.gz')else data[k]);report={}
    release=json.loads((HERE.parent/'ron-ordinary-backend/release-compiler.json').read_bytes());assert len(release['members'])==79
    for block in ('PC','CP'):
        p='older-'+block+'/';tree=j(p+'ordinary-repeat/owner-census.json.gz');argv={k.rsplit('/',1)[-1]:v for k,v in data.items()if k.startswith(p+'ordinary-repeat/tasks/')and k.endswith('.nul')}
        records=data[p+'ordinary-repeat/tasks/epochs.tsv'];report['normal-'+block]=budget(tree,records,argv)
        assert j(p+'ordinary-eligibility.json')['typed']==623
        # An authentic compiler's retained owner count cannot drift even one instruction away from the raw per-thread sum.
        broke=copy.deepcopy(tree);next(r for r in broke['roles']if r['trigger']=='exec'and r['mode']=='full'and r['crate']=='ron')['counter'][0]+=1
        try:budget(broke,records,argv)
        except AssertionError:pass
        else:raise AssertionError('changed owner instruction accepted')
        p='overlay-'+block+'/';visit=p+'seed-empty-receipt/ron-visit/';maps=j(p+'ordinary-live-maps.json.gz');ids=j(p+'sdk-24.json')['files']
        assert {k:v[0]for k,v in ids.items()}=={k:v['sha256']for k,v in release['members'].items()}
        report['overlay-'+block]=default(maps,ids,data[visit+'gate.tsv'].decode(),data[visit+'binding.tsv'].decode(),j(visit+'inherited-fd-status.json'))
        p='full-refusal-'+block+'/';assert b'assert [os.major(st.st_dev),os.minor(st.st_dev)]=='in data[p+'honest-stop.txt']
        assert j(p+'kernel-maps.json.gz')['samples']==[]
    topo=data['topology/native.zip'];assert digest(topo)==origin['topology']['sha256']
    with zipfile.ZipFile(io.BytesIO(topo))as z:
        assert z.testzip()is None
        normal=json.loads(z.read('ordinary.json'));held=json.loads(z.read('private.json'))
        assert normal['exit']==held['exit']==0 and normal['sha256']==held['sha256']
        assert len(held['rows'])==3 and all(r[1]==r[3]and r[2]==r[4]and r[-1]=='1'for r in held['rows'])
        assert all(r[1]!=r[3]and r[-1]=='0'for r in normal['rows'])and json.loads(z.read('private-namespace.json'))['writer_blocked']
    report['small_native']={'mappings':3,'same_bytes':normal['sha256'],'writer_blocked':True}
    library={Path(r[0]).name:r for r in maps['files']};platform=j('ext4/result.json')
    assert 'CapEff:\t0000000000000000'in platform['proc_status']
    assert ' - ext4 /dev/vda1 rw,'in platform['mountinfo']
    for label in ('empty','second-empty'):
        s=j('ext4/'+label+'/observed.json');assert digest(data['ext4/'+label+'/observed.json'])==platform['rows'][label]['sha256']
        assert digest(data['ext4/executable'])==s['elf']==platform['program'][label]
        report['ext4-'+label]=ext4(s,library)
        changed=copy.deepcopy(s);next(iter(changed['maps'].values()))['held_ino']+=1
        try:ext4(changed,library)
        except AssertionError:pass
        else:raise AssertionError('different actual inode accepted')
    assert not j('ext4/unchanged/observed.json')['owners']and platform['program']['unchanged']==digest(data['ext4/executable'])
    assert report['ext4-empty']==report['ext4-second-empty']
    for block in ('PC','CP'):
        empty=json.loads((HERE/'empty-originals'/(block+'.json')).read_bytes())
        assert empty['status']==0 and empty['enabled']==empty['running']>0 and empty['instructions']>report['normal-'+block]['whole']
        report['normal-'+block]['independent_empty_work_tree']=empty['instructions']
    print(json.dumps(report,sort_keys=True,indent=2))

if __name__=='__main__':main()
