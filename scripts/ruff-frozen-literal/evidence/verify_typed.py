"""Reopen exactly the differing bytes of same-operand native Rust metadata in each ranked original."""
import argparse,gzip,hashlib,json,re,subprocess,sys,zipfile
from pathlib import Path

pp=argparse.ArgumentParser();pp.add_argument('qa',type=Path);pp.add_argument('sources',type=Path);pp.add_argument('receipts',type=Path);args=pp.parse_args()
g=args.qa/'scripts/ruff-module-16149';sys.path.insert(0,str(g));import scope_rdr as dec
schema=json.loads(gzip.decompress((g/'schema.json.gz').read_bytes()));binding=json.loads((args.qa/'scripts/ruff-frozen-literal/factory.json').read_bytes())['source']
source=[]
for role in ('P','C'):
    rev=binding[role]
    names=['compiler/rustc_span/src/symbol.rs','compiler/rustc_metadata/src/rmeta/mod.rs']
    raws=[subprocess.check_output(['git','-C',args.sources,'show',rev+':'+n])for n in names]
    text=raws[1].decode().split('define_tables! {',1)[1].split('\n}',1)[0]
    assert dec.decode_symbols(raws[0].decode())==schema['symbols'] and re.findall(r'^    (\w+): Table<',text,re.M)==schema['tables']
    source.append(dict(role=role,commit=rev,files={n:hashlib.sha256(r).hexdigest()for n,r in zip(names,raws)}))
summary=json.loads((args.receipts/'summary.json').read_bytes());rows=[]
for slot in summary['scopes']:
    rank=slot['transport']['rank'];f=args.receipts/f'rank-{rank}/original.zip'
    with f.open('rb')as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==slot['transport']['sha256']
    out={}
    with zipfile.ZipFile(f)as z:
        for key in ('fixed','nonincremental'):
            pairs=slot[key];assert pairs[0]['metadata']==pairs[2]['metadata']
            raws=[z.read('objects/'+p['metadata']) for p in pairs[:2]]
            a,b=raws
            assert all(hashlib.sha256(v).hexdigest()==p['metadata']for v,p in zip(raws,pairs))
            got=[dec.decode(v,schema['symbols'],schema['tables'],'ty_vendored','rustc 1.99.0-dev (Ohm metadata 3)')for v in raws]
            reader=dec.Reader(a,schema['symbols']);reader.pos=int.from_bytes(a[8:16],'little');assert reader.symbol()=='x86_64-unknown-linux-gnu';start=reader.pos
            assert a[start:start+16].hex()==got[0][0]['private']
            same=len(a)==len(b) and b[start:start+16].hex()==got[1][0]['private'] and a[:start]==b[:start] and a[start+16:]==b[start+16:] and got[0][1:]==got[1][1:]
            out[key]=dict(parent=pairs[0]['metadata'],candidate=pairs[1]['metadata'],bytes=[len(a),len(b)],offset=start,identical_outside_private_hash=same,changed_required=sum(got[0][4].get(k)!=got[1][4].get(k)for k in set(got[0][4])|set(got[1][4])),changed_data=sum(p!=c for p,c in zip(a,b))if len(a)==len(b)else None)
    rows.append(dict(rank=rank,**out))
print(json.dumps(dict(actual_source=source,normal=rows),indent=2,sort_keys=True))
