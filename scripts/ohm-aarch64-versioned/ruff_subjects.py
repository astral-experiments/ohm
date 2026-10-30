"""Install public A, prerequisite N and final V with the same authenticated new Cargo in every arm."""
from pathlib import Path
import runpy
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from version_kit import bind,rt,SOURCES
from study import sha,save,load,need
from compare import installable

REG=load(HERE/'qualified-builds.json')
DEFAULT_SOURCE={'A':'444c0273a2e2bc0b161e988d43c882349bc2d7a6','N':'d3538b42a2dc56edb9bffbc9cc2373fb93c35054','M':SOURCES['rust']['source']}
DEFAULT_DRIVERS={'A':'a1f1eb603214c354827aa24c7176aaa4c349b2cc741526e6e2e87af46105929b','N':'a51424740c111a4cfdfc67b39bf498907eb396b4b1f0800c27c4fcafc9e6eb72','M':REG['drivers']['C']}

def setup(ancestor,inputs,alternate):
    bind()
    origin=inputs/'versioned'
    _,pair,_=installable(origin/'sdk.tar.zst',REG['capsule'],origin/'native',expected_tree=SOURCES['rust']['tree'])
    oldA,oldN=(load(ancestor/'receipts'/(k+'-sdk.json')) for k in 'PC')
    roles={'A':oldA,'N':oldN,'M':pair['C']}
    assert {r:v['source'] for r,v in roles.items()}==DEFAULT_SOURCE
    assert pair['P']['source']==SOURCES['rust']['parent'] and pair['P']['files'].keys()==pair['C']['files'].keys()
    n,=[p for p in oldA['files'] if p.startswith('lib/librustc_driver')]
    common=dict(oldA['files']);del common[n]
    assert len(common)==118 and all({p:v for p,v in d['files'].items() if p!=n}==common for d in [oldN,*pair.values()])
    old=common['bin/cargo'];assert old[0]==rt.TOOLS['bin/cargo']
    actual,meta=alternate;assert actual.samefile(origin/'cargo/cargo')
    assert sha(actual)==meta['cargo_sha256']==REG['cargo_elf']
    assert meta['git']==SOURCES['cargo']['source'] and meta['mode']==old[2]
    tar=[REG['cargo_elf'],meta['raw_bytes'],meta['mode']]
    for role,d in roles.items():
        assert d['files'][n][0]==DEFAULT_DRIVERS[role] and d['files']['bin/cargo']==old
        d['files']['bin/cargo']=tar;save(rt.LOG/('subject-'+role+'.json'),d)
    save(rt.LOG/'cargo-substitution.json',{'immutable_source':meta['git'],'from':old,'to':tar,'version':meta['version'],'product':sha(origin/'cargo/product.json')})
    owners={'A':ancestor/'donor-P','N':ancestor/'donor-C','M':rt.ROOT/'donor-C'}
    Parked=runpy.run_path(str(HERE.parent/'ohm-aarch64-confirm/parked.py'))['Parked']
    staged=Parked(rt.ROOT/'fixed-role-parking',rt.SDK,{k:d['files'] for k,d in roles.items()},owners,n,overrides={'bin/cargo':actual})
    save(rt.LOG/'all-named-start-identities.json',staged.initial);history=[]
    def select(role):
        v=staged.select(role);target=rt.LOG/'physical-selections'/(f'{len(history):02d}-'+role+'.json')
        key=save(target,v)
        history.append({k:w for k,w in v.items() if k!='files'}|{'snapshot':target.relative_to(rt.LOG).as_posix(),'sha256':key})
        return [n]
    return select,history

def enroll(h):
    update={'setup':setup,'SOURCE':DEFAULT_SOURCE,'DRIVER':DEFAULT_DRIVERS,'CURRENT':REG['capsule']}
    h.update(update);h['block'].__globals__.update(update)
    assert h['block'].__globals__['setup'] is setup

def marker_rules(base,role,phase):
    files={}
    hard={'A':{'zmij','compact_str','ruff_python_ast'},'N':{'compact_str','ruff_python_ast'},'M':set()}
    roots={'hard':'/dev/null/ohm-untracked-relink-inputs','legacy':'/dev/null/ohm-recheck-dependent-links','versioned':'/dev/null/ohm-recheck-dependent-links-v2'}
    for name in ('compact_str','ruff_python_ast','zmij'):
        p=base/phase/(name+'.d');raw=p.read_bytes()
        expect='hard' if name in hard[role] else 'versioned' if role=='M' else 'legacy'
        actual=[tag for tag,val in roots.items() if (val+':').encode() in raw.splitlines()]
        assert actual==[expect],(role,phase,name,actual)
        files[name]={'gate':expect,'actual_depfile_sha256':sha(p)}
    return files
