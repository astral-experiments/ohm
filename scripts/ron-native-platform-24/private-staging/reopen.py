"""Reopen the two refused private-staging controls, optionally from GitHub's original ZIPs."""
import argparse,hashlib,json,zipfile,gzip
from pathlib import Path
HERE=Path(__file__).resolve().parent
PIN={'PC':(13277485841,'f8536af267acd60dcc7e07a2bdb2cc9be862578f5f1179cfd04b41e28b008a9e'),'CP':(13277290271,'db504cf64873d7377b0c487bdfdcddbbfad3ecec0f10451a56e628ba21d6a253')}
def collect(path,side):
    with path.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==PIN[side][1]
    with zipfile.ZipFile(path)as z:
        assert z.testzip()is None;names=set(z.namelist());assert len(names)==len(z.infolist())and not any('/ron-visit/complete-hardware.json'in n for n in names)
        keep={n:z.read(n)for n in ['staging-copy.json','copy-generations-hardware.json','bind-supervisor-hardware.json','untouched-real-census/kernel-maps.json.gz','private-ordinary-census/tasks/epochs.tsv']}
        if side=='CP':keep['private-ordinary-census/kernel-maps.json.gz']=z.read('private-ordinary-census/kernel-maps.json.gz')
        else:assert 'private-ordinary-census/kernel-maps.json.gz' not in names
        for phase in ('untouched-real-census','private-ordinary-census'):
            for n in sorted(names):
                if n.startswith(phase+'/tasks/')and n.endswith('.nul'):
                    body=z.read(n);a=body.split(b'\0')
                    if len(a)>6 and a[3].endswith(b'/sdk/bin/rustc')and b'--crate-name\0ron\0'in body:keep[n]=body
        return {side+'/'+k:v for k,v in keep.items()}
def counter(d):assert d['status']==0 and d['instructions']>0 and d['enabled']==d['running']>0;return d['instructions']
def derive(data):
    result={}
    for side in PIN:
        def j(n):
            b=data[side+'/'+n]
            return json.loads(gzip.decompress(b)if n.endswith('.gz')else b)
        s=j('staging-copy.json');f=s['files']
        assert len(f)==len({r['name']for r in f})==len({(r['dev'],r['ino'])for r in f})==15
        assert sum(x['bytes']for x in f)==s['bytes']==388275472 and sum(x['allocated']for x in f)==s['allocated']==388296704
        assert all(len(x['sha256'])==len(x['blake3'])==64 for x in f)
        before=j('untouched-real-census/kernel-maps.json.gz');assert len(before['files'])==len(before['devices'])==13
        outside,=[n for n in before['devices']if 'libserde_derive-'in n];prior,=[x for x in before['files']if x[0]==outside];assert any(x['name']==outside and x['sha256']==prior[8]and x['original_ino']==prior[2]for x in f)
        epochs=data[side+'/private-ordinary-census/tasks/epochs.tsv'].splitlines()
        bad=[l.decode()for l in epochs if l.startswith(b'C ')and (min(map(int,l.split()[4:]))<0 or int(l.split()[5])<int(l.split()[6]))]
        actual={}
        for ph in ('untouched-real-census','private-ordinary-census'):
            rows=[]
            for n,v in data.items():
                if not(n.startswith(side+'/'+ph+'/tasks/')and n.endswith('.nul')):continue
                av=v.split(b'\0');assert av[-1]==b''and av[3].endswith(b'/sdk/bin/rustc')and av[av.index(b'--crate-name')+1]==b'ron'
                so,=[x.split(b'=',1)[1].decode()for x in av if x.startswith(b'serde_derive=')]
                rows.append([int(av[0]),so,hashlib.sha256(v).hexdigest()])
            assert rows;actual[ph]=rows
        assert {u[1]for u in actual['untouched-real-census']}=={outside}
        used={u[1]for u in actual['private-ordinary-census']};assert len(used)==1;inside,=used
        entry=dict(archive=list(PIN[side]),staged=s['bytes'],allocated=s['allocated'],stage_instructions=counter(j('copy-generations-hardware.json')),bind_supervisor_build_instructions=counter(j('bind-supervisor-hardware.json')),stage_cpu_ns=s['cpu_ns'],stage_wall_ns=s['wall_ns'],actual_compilers=actual,invalid_epoch=bad,measured_ron_visits=0)
        if side=='CP':
            after=j('private-ordinary-census/kernel-maps.json.gz')
            assert not bad and len(after['files'])==12 and len(after['devices'])==13 and after['errors']
            assert actual['private-ordinary-census'][0][1]==inside and inside!=outside and inside in after['devices']
            d=after['devices'][inside];assert d['named']!=d['mapped']
            assert all(x['named']==x['mapped']for n,x in after['devices'].items()if n!=inside)
            assert inside not in {x['name']for x in f};entry['unbound_selected_provider']={'path':inside,**d}
        else:assert bad==['C 4470 39821 39821 361682 747900 800500']
        result[side]=entry
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--originals',type=Path);p.add_argument('--create',action='store_true');args=p.parse_args()
    compact=HERE/'original-records.zip'
    if args.originals:
        real={k:v for side in PIN for k,v in collect(args.originals/(side+'.zip'),side).items()}
        if args.create and not compact.exists():
            with zipfile.ZipFile(compact,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
                for k in sorted(real):z.writestr(k,real[k])
    with zipfile.ZipFile(compact)as z:
        assert z.testzip()is None and len(z.namelist())==len(set(z.namelist()));data={n:z.read(n)for n in z.namelist()}
    if args.originals:assert real==data
    r=derive(data);res=HERE/'verified.json'
    if args.create:res.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    assert r==json.loads(res.read_text())
    for side,v in r.items():print(side,v['stage_instructions'],v['allocated'],'bytes, completed treatment visits',v['measured_ron_visits'])
if __name__=='__main__':main()
