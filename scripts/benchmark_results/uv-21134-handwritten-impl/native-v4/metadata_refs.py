"""Location-dependent children of the genuine post-item metadata sections."""
from proof import check,read,var,local_key,original_span,span_ref


def primitive(raw,p):
    """Res::PrimTy: native hir::PrimTy and its scalar rustc_ast_ir child."""
    from proof import check,read
    kind,p=read(raw,p)
    check(kind<6,'invalid native primitive type')
    sub=None
    if kind<3:
        sub,p=read(raw,p)
        check(sub<(6,6,4)[kind],'invalid native primitive subtype')
    return (kind,sub),p


def rewrite(data, h, cols, op, relocate, full_positions, known, docs_only=False):
    def one(pos,limit,msg):
        val,end=read(data,pos)
        check(val<limit,msg+' at '+str(pos))
        return val,end

    def symbol(pos):
        tag=data[pos];p=pos+1
        if tag==0:
            n,p=read(data,p)
            data[p:p+n].decode()
            check(data[p+n]==193,'inline symbol terminator')
            return p+n+1
        check(tag in (1,2),'invalid symbol tag')
        x,q=read(data,p)
        if tag==1:
            check(0<x<pos,'nonpreceding symbol')
            n,t=read(data,x)
            data[t:t+n].decode()
            check(data[t+n]==193,'invalid prior symbol')
            b=var(relocate(x))
            check(len(b)==q-p,'symbol offset width changed')
            op.write(p,q,b,'typed Symbol backreferences')
        return q

    def typed_span(pos):
        known.add(pos)
        target,q=original_span(data,pos)
        if target!=pos:
            to=full_positions[target]if target in full_positions else relocate(target)
            enc=span_ref(relocate(pos),to)
            check(len(enc)==q-pos,'expansion span changes encoded width')
            op.write(pos,q,enc,'typed expansion spans')
        return q

    for c in (cols['expn_data'] if not docs_only else ()):
        if not any(c):continue
        p=int.from_bytes(c,'little')
        kind,p=one(p,4,'ExpnKind')
        if kind==1:
            _,p=one(p,3,'MacroKind')
            p=symbol(p)
        elif kind==2:
            _,p=one(p,3,'AstPass')
        elif kind==3:
            desugaring,p=one(p,13,'DesugaringKind')
            if desugaring==11:
                _,p=one(p,2,'FormatLiteral.source')
        kr,p=read(data,p)
        if kr:
            zero,p=read(data,p)
            check(zero==0,'foreign expansion version marker')
            _,p=read(data,p)
            p+=16  # ExpnHash
        else:_,p=read(data,p)
        p=typed_span(p)
        _,p=read(data,p)  # disambiguator
        p=typed_span(p)
        tag,p=one(p,2,'optional unstable features')
        if tag:
            n,p=read(data,p)
            for _ in range(n):p=symbol(p)
        _,p=one(p,4,'edition')
        for label in ('macro def','parent module'):
            tag,p=one(p,2,label)
            if tag:_,p=local_key(data,p)
        check(all(v<2 for v in data[p:p+4]),'expansion flags')

    def res(p):
        kind,p=one(p,10,'Res')
        if kind==0:
            dk,p=one(p,30,'DefKind')
            flags={12:1,14:3,15:2,17:1,18:1,27:1}.get(dk,0)
            for _ in range(flags):_,p=read(data,p)
            _,p=local_key(data,p)
        elif kind==1:
            _,p=primitive(data,p)
        elif kind in (2,3,4):
            _,p=local_key(data,p)
            if kind==3:_,p=one(p,2,'is_trait_impl')
        elif kind==5:_,p=read(data,p)
        elif kind==7:p=symbol(p)
        elif kind==8:
            attr,p=one(p,4,'NonMacroAttrKind')
            if attr==0:p=symbol(p)
        else:check(kind in (6,9),'unrecognized Res at '+str(p))
        return p

    for c in cols['doc_link_resolutions']:
        if not any(c):continue
        p=int.from_bytes(c,'little')
        n,p=read(data,p)
        for _ in range(n):
            p=symbol(p)
            _,p=one(p,3,'doc link Namespace')
            has,p=one(p,2,'optional doc link')
            if has:p=res(p)

    if docs_only:return
    # The Rust encoder's allocation index contains absolute serialized-allocation
    # byte offsets. The underlying allocation stream is copied in full.
    t=h['tables']['interpret_alloc_index'];p=t['position']
    if p is not None:
        for _ in range(t['length']):
            old,q=read(data,p)
            check(0<old<t['position'],'invalid indexed allocation')
            enc=var(relocate(old));check(q-p==len(enc),'allocation index width')
            op.write(p,q,enc,'CTFE allocation offsets')
            p=q
