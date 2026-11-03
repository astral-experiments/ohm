"""Re-encode a two-row RPITIT result without embedding toolchain-specific keys."""
from hashlib import sha256
from proof import check, read, var, local_key


def parsed(b, root_reader, di, defkeys):
    h=root_reader(b);table=h['tables']
    ids=di.keyed(b,h)
    local=set(ids)
    ks=[defkeys.key_at(b,int.from_bytes(x,'little'),ids)[0] for x in di.rows(b,table['def_keys'])]
    # Restrict the general wire decoding to the authenticated source method.
    matches=[]
    for idx,c in enumerate(di.rows(b,table['collect_return_position_impl_trait_in_trait_tys'])):
        if any(c) and ks[idx]['kind']=='ValueNs'and ks[idx]['name']==('str','setup_build'):
            matches.append((idx,int.from_bytes(c,'little')))
    check(len(matches)==1,'not the unique enrolled RPITIT provider')
    idx,where=matches[0];n,p=read(b,where)
    check(n==2,'not two map entries')
    parts=[]
    for _ in range(n):
        begin=p
        key,p=local_key(b,p)
        check(key[0]!=0,'RPITIT key must be foreign')
        typos=p
        if b[p]&128:
            shorthand,p=read(b,p)
            check(0<shorthand-128<where and not b[shorthand-128]&128,'RPITIT Ty shorthand')
            ty=('shared',shorthand-128)
        else:
            # TyKind::Alias(IsRigid::No, AliasTyKind::Opaque { def_id }, args).
            check(b[p:p+3]==bytes([23,1,2]),'non-opaque or rigid Ty')
            opaque,p=local_key(b,p+3)
            check(opaque[0]==0 and opaque[1]in local and ks[ids.index(opaque[1])]['kind']=='OpaqueTy','missing opaque declaration')
            count,p=read(b,p)
            check(0<count<64,'unbounded opaque arguments')
            regions=[]
            for _ in range(count):
                # GenericArgKind::Lifetime(RegionKind::ReEarlyParam).
                check(b[p:p+2]==bytes(2),'opaque generic argument is not an early lifetime')
                index,p=read(b,p+2);tag=b[p];name,p=read(b,p+1)
                check(tag in (1,2),'a moved type publishes a symbol')
                if tag==1:
                    check(0<name<where,'symbol points inside moved type')
                    length,start=read(b,name)
                    b[start:start+length].decode()
                    check(b[start+length]==193,'bad lifetime symbol')
                regions.append((index,tag,name))
            ty=('opaque',opaque,regions)
        parts.append((key,ty,begin,typos,p))
    check(parts[0][0][0]==parts[1][0][0] and parts[0][0]!=parts[1][0],'map keys alias or suppliers differ')
    check(sorted(entry[1][0]for entry in parts)==['opaque','shared'],'RPITIT value shape')
    long_at=next(i[3]for i in parts if i[1][0]=='opaque')
    links=[]
    for other,c in enumerate(di.rows(b,table['type_of'])):
        ptr=int.from_bytes(c,'little')
        if ptr and b[ptr]&128:
            sh,stop=read(b,ptr)
            if sh==long_at+128:links.append((other,ptr,stop))
    check(len(links)==1,'number of typed backreferences')
    other,ptr,stop=links[0]
    check(other!=idx and ks[other]['kind']=='AnonAssocTy','missing associated type consumer')
    # Generic region args contain no nested Ty, Span, predicate or newly
    # interned symbol. Only the complete opaque Ty can publish a moving key.
    needle=var(long_at+128)
    hits=[]
    location=b.find(needle,p)
    while location>=0:
        hits.append(location);location=b.find(needle,location+1)
    check(hits==[ptr],'unowned possible later Ty shorthand')
    return h,where,p,parts,ids[idx],ids[other],ptr,stop


def project(left,right,reader,di,defkeys):
    a,where,end,rows,owner,assoc,ptr,stop=parsed(left,reader,di,defkeys)
    b,q,en2,other,owner2,assoc2,ptr2,stop2=parsed(right,reader,di,defkeys)
    check((where,end,owner,assoc,ptr,stop)==(q,en2,owner2,assoc2,ptr2,stop2),'different native map or reference')
    check([(i[0],i[1]) for i in reversed(rows)]==[(i[0],i[1])for i in other],'map keys/terms/order differ')
    out=bytearray(left)
    cursor=where+1
    longpos=None
    for key,term,start,ty,endpos in reversed(rows):
        if term[0]=='opaque':longpos=cursor+ty-start
        out[cursor:cursor+endpos-start]=left[start:endpos]
        cursor+=endpos-start
    check(cursor==end and longpos is not None,'map extent')
    ref=var(longpos+128)
    check(len(ref)==stop-ptr,'Ty reference width')
    out[ptr:stop]=ref
    check(bytes(out)==right,'additional native RPITIT differences')
    return {'method_local_hash':owner.hex(),'associated_local_hash':assoc.hex(),'foreign_keys':[[k[0][0],k[0][1].hex()] for k in rows],'bytes':len(out),'reconstructed_sha256':sha256(out).hexdigest()}
