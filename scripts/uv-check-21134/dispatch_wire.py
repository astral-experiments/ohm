"""Exact two-entry RPITIT wire permutation and its native type backreference; unknown representations are rejected."""
from hashlib import sha256
from pathlib import Path
import tempfile
RDR=None
rmeta=None
MAP='collect_return_position_impl_trait_in_trait_tys';OWNER='CrateRoot::Impl#3::setup_build'
# These two original serialized (DefId, EarlyBinder<Ty>) pairs are proven below from both
# I/O directions, the encoder row, the native type_of pointer and the complete opposite file.
E0=bytes.fromhex('92037bd45838af29254217010200d31a1e7309f89722030000000238000000023800000101bbbc01')
E1=bytes.fromhex('92037bff806fd8dba4b2ebed02')
def u(b,i):
    n=0
    for j in range(10):
        x=b[i+j];n|=(x&127)<<(7*j)
        if x<128:return n,j+1
    raise ValueError('overlong ULEB')
def leb(n):
    b=bytearray()
    while n>=128:b.append((n&127)|128);n>>=7
    return bytes([*b,n])
def spec(b):
    with tempfile.TemporaryDirectory()as t:
        p=Path(t)/'x.rmeta';p.write_bytes(b);_,r,ids,labels=rmeta(p)
    assert r['crate_name']=='uv_dispatch';get=lambda n:[int.from_bytes(s,'little')for s in RDR['sig'].di.rows(b,r['tables'][n])]
    (idx,offset),=[(i,v)for i,v in enumerate(get(MAP))if v and labels[ids[i]]==OWNER]
    assert b[offset]==2;begin=offset+1
    one=b[begin:begin+len(E0)+len(E1)];assert one in (E0+E1,E1+E0)
    order=0 if one==E0+E1 else 1
    # DefId in the measured DefPathHash mode is encoded crate-number ULEB and 8-byte local hash.
    cnum,w=u(E0,0);assert (cnum,w)==u(E1,0)==(402,2) and E0[w:w+8]!=E1[w:w+8]
    long_at=begin+order*len(E1)+w+8;assert b[long_at]==0x17
    short=E1[w+8:];far,n=u(short,0);assert n==len(short) and 0<far-128<begin
    pointers=[]
    for i,p in enumerate(get('type_of')):
        if p and b[p]&128 and u(b,p)[0]-128==long_at:pointers.append([ids[i],labels[ids[i]],p,u(b,p)[1]])
    (other,desc,pointer,width),=pointers;assert desc==OWNER and ids[idx]!=other
    return {'map_index':idx,'map_key':ids[idx],'later_type_key':other,'map':offset,'keys':[E0[:w+8].hex(),E1[:w+8].hex()],'key_bytes':w+8,'order':order,'value_position':long_at,'other_shorthand':far-128,'type_of_shorthand':pointer,'width':width}
def convert(left,right):
    a=spec(left);b=spec(right)
    assert a['order']!=b['order'] and len(left)==len(right) and all(a[k]==b[k]for k in ('map_key','later_type_key','map','keys','key_bytes','other_shorthand','type_of_shorthand','width'))
    buf=bytearray(left);p=a['map']+1;buf[p:p+len(E0)+len(E1)]=(E1+E0 if b['order']else E0+E1)
    p=a['type_of_shorthand'];enc=leb(b['value_position']+128);assert len(enc)==a['width'];buf[p:p+len(enc)]=enc
    assert bytes(buf)==right,'wire differences outside the native unordered map and its exact typed backreference'
    return {'from':a,'to':b,'native_full_bytes':len(buf),'reconstructed':sha256(buf).hexdigest(),'changed_bytes':sum(x!=y for x,y in zip(left,right))}
