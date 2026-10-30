"""Verify the marginal compiler change across all Ruff workspace test executables and both registry instances."""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import tarfile

HERE=Path(__file__).resolve().parent
TOOLS=HERE.parent/'native-apple-ty-links-v1'
sys.path.insert(0,str(TOOLS))
from read_links import command,file_hash

P='444c0273a2e2bc0b161e988d43c882349bc2d7a6'
C='82911b516fb35608fd70ada4deb6f8429277f410'
OLD='2d253467b5153f82d26c51d49eb8d4156f1768bf'
NEW='aa9a1ff88aa83b3f01360ef5b3cb04b2be187206'
PRIOR='2e1ea0d11155bc8c76fe3837b4fb0b3083825450d903d40bcc15d9b1cac9caf5'
PHASES=('edit','repeat-1','repeat-2')
H=lambda x:hashlib.sha256(x).hexdigest()
class Portable:
    def __init__(self, path, digest):
        self.contents = {}
        with tarfile.open(path, "r|xz") as source:
            for entry in source:
                assert entry.isfile() and entry.name not in self.contents
                self.contents[entry.name] = source.extractfile(entry).read()
        manifest = json.loads(self.contents.pop("MANIFEST.json"))
        assert manifest["original_zip_sha256"] == digest
        assert dict(manifest["files"]) == {k: H(v) for k, v in self.contents.items()}

    def read(self, key):
        return self.contents[key]

def read(z,key):return json.loads(z.read(key))
def decoded(z,key):
    body=z.read(key)
    return body if isinstance(z,Portable) else gzip.decompress(body)
def linked(row):return {key for key,data in row['test_executables'].items() if data['physical_links']}
def idents(row):return {key:(v['sha256'],v['bytes']) for key,v in row['test_executables'].items()}
def unit_keys(z,root,row):
    return {(pkg,n,tuple(kind)) for f,v in row['binary_roster'].items() if v['links'] for pkg,n,kind in [v['unit']]}
def phase(z,where,crc):
    prefix=where+'/'
    src=read(z,prefix+'verified.json')
    row=command(z,prefix,src,decoded=isinstance(z,Portable))
    assert row['scope']=='workspace' and len(row['test_executables'])==83
    assert row['e2e']['tests']==(194 if row['state']=='old' else 195)
    keys=unit_keys(z,where,src)
    if crc:
        units=[r for r in map(json.loads,decoded(z,prefix+'stdout.gz').splitlines())
               if r['reason']=='compiler-artifact' and r['target']['name']=='zlib_rs' and r['target']['kind']==['lib']]
        assert len(units)==len(src['zlib'])==2
        assert len({tuple(u['features']) for u in units})<=2
        for i,(u,proof) in enumerate(zip(units,src['zlib'])):
            assert u['package_id'].split('#')[-1]=='zlib-rs@0.5.5'
            assert [f for f in u['filenames'] if f.endswith('.rlib')]==[proof['path']]
            assert u['features']==proof['features'] and u['fresh']==proof['fresh']
            data=decoded(z,prefix+f'zlib-{i}.dep.gz')
            assert H(data)==proof['dep'] and b'zlib-rs-0.5.5/src/' in data
            assert proof['hard']==(b'ohm-untracked-relink-inputs' in data)
            assert proof['recheck']==(b'/dev/null/ohm-recheck-dependent-links' in data)
        assert row['full'].count('zlib_rs')==sum(not u['fresh'] for u in units)
    return row,keys

def compare(z,prior):
    if isinstance(z,zipfile.ZipFile):
        assert len(z.namelist())==len(set(z.namelist())) and z.testzip() is None
    pair=read(z,'pair.json')
    release=read(z,'release.json')
    assert '2d44' in release['cargo_version'] and release['cargo']['sha256']=='505008003127f597cf2bdbd967d2bac9158d706b55a18f8bf17790e9ea3bbac9'
    assert len(pair['differ'])==1
    for role,rev in zip('PC',(P,C)):
        observed=read(z,'bootstrap-'+role+'-product.json')
        assert observed==pair['products'][role] and observed['source']==rev
        assert observed['runtime']['bin/cargo']==release['cargo']['sha256']
        d=read(z,'workspace-dyld/'+role+'/verified.json')
        assert d['role']==role and d['loaded'][pair['differ'][0]]['sha256']==observed['runtime'][pair['differ'][0]]
    test=read(z,'run-make.json')
    assert test['source']==C and H(z.read('run-make.log'))==test['log']
    enrollment=read(z,'enrolled-workspace.json')
    assert enrollment['compiler']==[P,C] and enrollment['ruff']==[OLD,NEW] and enrollment['prior_sha256']==PRIOR
    rows={}
    for role in 'PC':
        for key in ('visit/cold',*('visit/'+s for s in PHASES),'empty-new/clean'):
            rows[role,key]=phase(z,'ty-comparison/workspace/'+role+'/'+key,True)
        ref=rows[role,'empty-new/clean'][0]
        for p in PHASES:
            v=rows[role,'visit/'+p][0]
            assert idents(v)==idents(ref) and v['e2e']['sha256']==ref['e2e']['sha256']
            if p=='edit':assert v['e2e']['links']==1 and 'ty_server' in v['full']
    outcome={}
    for p in PHASES:
        baseline,baseline_logical=phase(prior,'C/visit/'+p,False)
        (prev,pkeys),(curr,ckeys)=[rows[role,'visit/'+p] for role in 'PC']
        assert set(prev['test_executables'])==set(curr['test_executables'])==set(baseline['test_executables'])
        assert prev['full']==baseline['full'] and prev['link_only']==baseline['link_only']
        assert prev['all_linkers']==baseline['all_linkers'] and linked(prev)==linked(baseline)
        assert pkeys==baseline_logical
        to_list=lambda keys:[list((pkg,n,list(k))) for pkg,n,k in sorted(keys)]
        synopsis={'tests_total':83,'rustcs':[len(v['full']) for v in (prev,curr)],
                  'zlib_rustcs':[v['full'].count('zlib_rs') for v in (prev,curr)],
                  'all_links':[v['all_linkers'] for v in (prev,curr)],'test_links':[len(linked(v)) for v in (prev,curr)],
                  'saved':to_list(pkeys-ckeys),'added':to_list(ckeys-pkeys)}
        assert synopsis==read(z,'crc-workspace-result.json')[p]
        synopsis['e2e_links']=[v['e2e']['links'] for v in (prev,curr)]
        synopsis['remaining']=sorted(linked(curr))
        synopsis['remaining_registry_compiles']=sorted(set(curr['full'])&{'libm','ron','objc2','zlib_rs','zmij'})
        outcome[p]=synopsis
    return outcome

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,help='optionally verify the complete original Actions ZIP')
    args=parser.parse_args()
    source='45012e8b81dae37c06c2469cdaf08746cae78f087289ee830da25ec29f8f32e9'
    prior=Portable(TOOLS/'paired-workspace.tar.xz',PRIOR)
    packed=compare(Portable(HERE/'workspace.tar.xz',source),prior)
    if args.source:
        assert file_hash(args.source)==source
        with zipfile.ZipFile(args.source) as original:
            assert compare(original,prior)==packed
    for k,row in packed.items():
        print(k, {x:y for x,y in row.items() if x not in ('remaining','saved','added')})
