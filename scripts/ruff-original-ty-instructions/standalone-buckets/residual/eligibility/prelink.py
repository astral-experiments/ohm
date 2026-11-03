"""Resolve real codegen_fn_attrs on the selected DefIds, including chained query records."""
import argparse,collections,hashlib,json,re,struct,subprocess,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from partitions import check,leb
from mono_rows import Decoder,read
REV='5c5af1a053326e6ce5df048c4dcb30b53e01a069'
def depkinds(repo):
    b=subprocess.check_output(['git','--no-lazy-fetch','-C',repo,'show',REV+':compiler/rustc_middle/src/queries.rs'])
    names=[v.decode()for pattern in (rb'^    non_query (\w+)\s*$',rb'^    query (\w+)\(')for v in re.findall(pattern,b,re.MULTILINE)]
    check(len(names)==len(set(names))and names[0]=='Null' and names[5]=='CompileCodegenUnit','wrong query schema')
    return names
def graph(b,names,kind,keys):
    bits=(len(names)-1).bit_length();p=7+b[6]+8;end=len(b)-13;mx,count,edges=struct.unpack_from('<QQQ',b,end-24);out={}
    check(b[:6]==b'RSIC'+(24450).to_bytes(2,'little')and b[-13:]==b'rust-end-file','graph')
    for _ in range(count):
        h,i=struct.unpack_from('<HI',b,p);k=h&((1<<bits)-1);n=(h>>(bits+2))-1;width=((h>>bits)&3)+1;did=b[p+6:p+22];p+=38
        if n<0:n,p=leb(b,p)
        if k==kind and did in keys:
            check(did not in out,'ambiguous query key');out[did]=i
        p+=n*width
    return out
def footer(b,length,wanted):
    foot=struct.unpack_from('<Q',b,length-21)[0];p=foot;v=0
    while b[p]&128:v|=(b[p]&127)<<(7*(p-foot));p+=1
    v|=b[p]<<(7*(p-foot));p+=1;check(v==0xc0ffeec0ffeec0ffeec0ffeec0ffee,'footer tag')
    previous=b[p];p+=1;check(previous in(0,1),'previous flag')
    if previous:previous,p=leb(b,p)
    n,p=leb(b,p);forwarded={}
    for _ in range(n):
        i,p=leb(b,p);old,p=leb(b,p)
        if i in wanted:forwarded[i]=old
    n,p=leb(b,p)
    for _ in range(n*3):_,p=leb(b,p)
    n,p=leb(b,p)
    for _ in range(n):_,p=leb(b,p);p+=24
    n,p=leb(b,p);at={}
    for _ in range(n):
        i,p=leb(b,p);a,p=leb(b,p)
        if i in wanted:
            check(i not in at and leb(b,a)[0]==i,'real tagged query');at[i]=a
    # OnDiskCache::query_value_source checks the current value before following the prior index.
    forwarded={k:v for k,v in forwarded.items() if k not in at}
    if forwarded:
        check(0<previous<length,'missing previous');older=footer(b,previous,set(forwarded.values()))
        check(set(older)==set(forwarded.values()),'dangling forwarded record')
        for i,old in forwarded.items():at[i]=older[old]
    return at
def explicit(b,off):
    d=Decoder(b,off);tag=d.u();flags=d.u();inline=d.byte();check(inline<4,'forced inline span');opt=d.byte();check(opt<4,'optimize')
    if d.boolean():d.symbol()
    n=d.u();check(n<100,'foreign alias count')
    for _ in range(n):d.defid();d.byte();d.byte()
    if d.boolean():d.p+=2
    n=d.u();check(n<100,'features')
    for _ in range(n):d.symbol();d.byte()
    safe=d.boolean();link=(d.byte()if d.boolean()else None)
    check(link is None or link<9,'linkage')
    return {'query_offset':off,'encoded_tag':tag,'flags':flags,'inline':inline,'optimize':opt,'safe_target':safe,'linkage':link,'inspected_prefix':b[off:d.p].hex()}
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('rust',type=Path);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    tables=json.loads((a.root/'partition-ordinary-exact.json').read_bytes());z=zipfile.ZipFile(a.root/'original-41671764437.zip');out={};names=depkinds(a.rust)
    for st in ('old','edit'):
        rec=json.loads(z.read(f'ordinary/{st}/project-session.json'));f=rec['raw']['dep-graph.bin'];b=(a.root/f'partition-{st}-query-cache.bin').read_bytes()
        units={n:read(b,u)for n,u in tables[st]['rows'].items()if n.startswith(('35bor','cdh33'))}
        keyset={bytes.fromhex(x[3])for rs in units.values()for x in rs if not x[4]and x[5]!=3};g=subprocess.check_output(['zstd','-qdc'],input=z.read('native/'+f['sha256']+'.zst'));check(len(g)==f['bytes']and hashlib.sha256(g).hexdigest()==f['sha256'],'graph SHA')
        q=graph(g,names,names.index('codegen_fn_attrs'),keyset);check(set(q)==keyset,('missing codegen attrs',len(keyset),len(q)));del g
        qs=tables[st];ids=set(q.values())|{qs['tagged_query_index']};pos=footer(b,len(b),ids);check(pos[qs['tagged_query_index']]==qs['tagged_from'],'active partition query')
        rows={did.hex():explicit(b,pos[i])|{'active_index':i}for did,i in q.items()}
        out[st]={'graph_sha256':f['sha256'],'query_sha256':qs['sha256'],'genuine_internalized_roots':rows,'units':{n:{'global_asm':sum(v[0]==2 for v in rs),'roots':sum(not v[4]for v in rs),'inline':sum(v[4]for v in rs),'MIR_root':sum(v[7]for v in rs if not v[4]),'MIR_inline':sum(v[7]for v in rs if v[4]),'late_internal_roots':sum(not v[4]and v[5]==4 for v in rs)}for n,rs in units.items()}}
        print(st,len(rows),collections.Counter(r['linkage']for r in rows.values()),out[st]['units'],flush=True);a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
