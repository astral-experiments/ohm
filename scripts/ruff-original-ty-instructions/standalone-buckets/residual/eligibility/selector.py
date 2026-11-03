"""Apply the general post-stock selector to the entire ordinary crate. Names use actual rustc SipHash1-3 128-bit output."""
import argparse,json,re,subprocess
from pathlib import Path
M=(1<<64)-1
def rol(n,a):return ((n<<a) & M)|(n>>(64-a))
def hashes(t):
    b=t.encode()+b'\xff';v=[0x736f6d6570736575,0x646f72616e646f6d^0xee,0x6c7967656e657261,0x7465646279746573]
    def rounds(n):
        for _ in range(n):
            v[0]=(v[0]+v[1])&M;v[1]=rol(v[1],13)^v[0];v[0]=rol(v[0],32)
            v[2]=(v[2]+v[3])&M;v[3]=rol(v[3],16)^v[2];v[0]=(v[0]+v[3])&M;v[3]=rol(v[3],21)^v[0]
            v[2]=(v[2]+v[1])&M;v[1]=rol(v[1],17)^v[2];v[2]=rol(v[2],32)
    tail=b[len(b)//8*8:];last=(len(b)&255)<<56|int.from_bytes(tail,'little')
    for word in [int.from_bytes(b[j:j+8],'little')for j in range(0,len(b)-len(tail),8)]+[last]:
        v[3]^=word;rounds(1);v[0]^=word
    v[2]^=0xee;rounds(3);lo=v[0]^v[1]^v[2]^v[3];v[1]^=0xdd;rounds(3);hi=v[0]^v[1]^v[2]^v[3]
    return lo,hi
def enc(n):
    out='';z='0123456789abcdefghijklmnopqrstuvwxyz'
    for _ in range(25):n,q=divmod(n,36);out=z[q]+out
    assert not n;return out
def mangle(s):
    l,h=hashes(s);return enc((h<<64)|l)
def select(table):
    by_name=table['rows'];all_syms=[r['encoded_symbol']for r in by_name.values()]
    identities=set()
    for name,symbol in zip(by_name,all_syms,strict=True):
        m=re.fullmatch(r'_RINSCs([0-9a-zA-Z]+)_(\d+)([a-z_][a-z_0-9]*?)3cguKRe([0-9a-f]+)_E',symbol)
        assert m and int(m[2])==len(m[3]) and bytes.fromhex(m[4]).decode()==name
        raw=0
        for digit in m[1]:raw=raw*62+'0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'.index(digit)
        identities.add((m[3],format(raw+2,'016x')))
    assert len(identities)==1
    crate,crate_id=identities.pop();prefix=f'{crate}.{crate_id}';keys=[mangle(prefix),mangle(prefix+'.volatile')]
    ranks=sorted(by_name,key=lambda k:(-by_name[k]['size'],k))
    assert len(set(keys)&set(by_name))==2
    remaining=256-len(by_name);k=2**((1+remaining//len(keys)).bit_length()-1)
    return {'crate':crate,'stable_crate_id':crate_id,'all_post_stock':len(by_name),'available':remaining,'selected':keys,'other_units_considered':len(set(by_name)-set(keys)),'maximum_observed_size':max(q['size']for q in by_name.values()),'by_size_ranks':[ranks.index(n)+1 for n in keys],'ordinary_top_five':ranks[:5],'per_root_lanes':k,'final_if_nonempty':len(by_name)+2*(k-1),'left':remaining-2*(k-1)}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('tables',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r={k:select(v)for k,v in json.loads(a.tables.read_bytes()).items()};a.output.write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(r)
