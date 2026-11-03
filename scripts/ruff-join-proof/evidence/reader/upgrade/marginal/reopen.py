"""Recover the four fixed-external ordinary Cargo prices and the refused independent-cold witness."""
import argparse,collections,gzip,hashlib,json,re,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;H='647092f0c7f37b26176cafdbe9cf204f2212a28c3d07d0fd79574e5f96b9a744'
def sha(b):return hashlib.sha256(b).hexdigest()
def original(p):
    assert p.stat().st_size==138906749
    with p.open('rb')as src:assert hashlib.file_digest(src,'sha256').hexdigest()==H
    with zipfile.ZipFile(p)as z:
        assert z.testzip()is None;ans={}
        for name in z.namelist():
            if not name.startswith('fixed-extern/'):continue
            key=name.removeprefix('fixed-extern/');part=key.split('/')
            if key in ('registration.json','calibration.json','cargo-source.json','conversion.json','selected.json'):pass
            elif part[0].startswith('bounded-seed-')or part[0]=='wholly-empty-new-P':
                if key.endswith('/external-products.json.gz'):ans[key]=gzip.decompress(z.read(name)).decode();continue
                if part[-1]not in ('metadata.json','separate-verdict.json','record.json'):continue
            elif part[0].startswith('pair-'):
                if re.match(r'^exec\.\d+$',part[-1])or part[-1]in ('hardware.json','metadata.json','record.json','accepted.json')or (part[-1]=='stdout'and part[1]in('old','independent-clean-new','edit-unchanged-json'))or (part[-1]=='stderr'and part[1]=='invalid'):pass
                else:continue
            else:continue
            ans[key]=z.read(name).decode()
        return ans
def typed(raw,q):
    prefix=q+'/exec.';out={}
    for k,b in raw.items():
        if not k.startswith(prefix):continue
        pid=k[len(prefix):];assert pid.isdigit()
        for line in b.splitlines():
            a=re.match(r'^execve\("[^"]*/rustc",.*?"--crate-name", "([^"]+)",',line)
            if a and line.endswith(' = 0'):assert pid not in out;out[pid]=a[1]
    return out
def api(r):return {n:k['public']for n,k in r.items()}
def verify(raw):
    j=lambda k:json.loads(raw[k]);conv=j('conversion.json');p=j('bounded-seed-P/external-products.json.gz');c=j('bounded-seed-C/external-products.json.gz')
    assert p==c and conv['p']==conv['c']==sha(raw['bounded-seed-P/external-products.json.gz'].encode()) and len(p)==1322 and conv['differences']==[]
    cal=j('calibration.json');assert all(c['matched']and c['receipt']['instructions']>0 for c in cal.values())and set(cal)=={'true','false'}
    scalar=[];roots=[];ROLES={'P':'c67a662901b9d15945579f0b607c234cf92e55488c687b68ba8a95f9e22326a2','C':'f97b6020c860e05eb3b4a20f0d2ae0d0e1b10953bc2a2d2205b77df9565cb13d'}
    for i,role in enumerate('PCCP'):
        base=f'pair-{i}-{role}/';acc=j(base+'accepted.json');scores={};phases={}
        for n in ['old','old-unchanged','edit','edit-unchanged','edit-unchanged-json','private-body','private-unchanged','restore-body','invalid','repair','independent-clean-new']:
            q=base+n;r=j(q+'/record.json');o=typed(raw,q);assert o==r['rustcs']and r['cargo']==ROLES[role]and r['minimum_available']>=8*2**30
            assert r['exit']==(101 if n=='invalid'else 0)and r['error_codes']==(['E0308']if n=='invalid'else[])
            names=sorted(o.values());phases[n]=names
            if 'hardware'in r:
                hw=j(q+'/hardware.json');assert hw==r['hardware']and hw['status']==0 and hw['instructions']>0 and hw['running']>0 and hw['enabled']<=hw['running']*1.01;scores[n]=hw['instructions']
            if n in ('old','independent-clean-new'):
                rows=[json.loads(a)for a in raw[q+'/stdout'].splitlines()];local=[a for a in rows if a['reason']=='compiler-artifact'and a['package_id'].startswith('path+')];external=[a for a in rows if a['reason']=='compiler-artifact'and a not in local]
                assert len(local)==32 and len(external)==328 and all(not a['fresh']for a in local)and all(a['fresh']for a in external)
        assert len(phases['edit'])==7 and phases['repair']==phases['edit']and phases['edit-unchanged']==phases['old-unchanged']==['ty_python_semantic']and phases['private-body']==['ruff_linter','ty_python_semantic']and 'error[E0308]'in raw[base+'invalid/stderr']
        m=[json.loads(l)for l in raw[base+'edit-unchanged-json/stdout'].splitlines()]
        assert sum(r['reason']=='compiler-artifact'and not r['fresh']for r in m)==6 and scores==acc['whole_irs']
        values=[api(j(base+n+'/metadata.json'))for n in ('edit','restore-body','repair','independent-clean-new')]
        assert all(v==acc['public']for v in values);roots.append(values[0]);scalar.append(scores)
    assert all(v==roots[0]for v in roots)
    f=j('wholly-empty-new-P/external-products.json.gz');ev=j('wholly-empty-new-P/separate-verdict.json');diff=sorted(k for k in p.keys()|f.keys()if p.get(k)!=f.get(k));assert diff==ev['differences']and len(diff)==13 and not ev['independent_public_same']
    changed={k for k in p.keys()&f.keys()if p[k]!=f[k]};assert sorted(Path(k).suffix for k in changed)==['.log','.rmeta','.so']and len(p.keys()-f.keys())==len(f.keys()-p.keys())==5 and all(Path(k).name.startswith('autocfg_')and Path(k).suffix=='.ll'for k in p.keys()^f.keys())
    fully=api(j('wholly-empty-new-P/metadata.json'));assert fully.keys()==roots[0].keys()and all(fully[k]!=roots[0][k]for k in fully)
    assert not any(k.startswith('wholly-empty-new-C/')for k in raw)
    relative={n:[100*(scalar[1][n]/scalar[0][n]-1),100*(scalar[2][n]/scalar[3][n]-1)]for n in scalar[0]}
    return {'descriptive_fixed_input_counts_PCCP':scalar,'relative_percent_PC_CP':relative,'all_ordinary_fixed_controls':True,'fully_independent_final_control':'Ruf compiled successfully; separate P wholly cold gate refused, C never executed','external-byte-identity':conv['p']}
ap=argparse.ArgumentParser();ap.add_argument('--original',type=Path);ap.add_argument('--make',action='store_true');o=ap.parse_args()
if o.make:
    x=original(o.original);(HERE/'observed.json.gz').write_bytes(gzip.compress(json.dumps(x,sort_keys=True,separators=(',',':')).encode(),mtime=0))
x=json.loads(gzip.decompress((HERE/'observed.json.gz').read_bytes()))
if o.original:assert original(o.original)==x
print(json.dumps(verify(x),indent=2,sort_keys=True))
