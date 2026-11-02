"""The nominal trait, full type arguments and flags of an actual GNU -22 impl_trait_header row."""
from functools import cache
import identity_wire as w

class Terms:
    def __init__(self,data,resolve):
        self.data=data
        self.resolve=resolve

    def did(self,r):
        return self.resolve(r.u(),r.raw(8).hex())

    def skip_defid(self,r):
        cn=r.u(); r.raw(8)
        assert cn<65536

    def enum(self,r,last):
        value=r.u()
        if not 0<=value<=last:raise ValueError(("enum outside source",value,last))
        return value

    def region(self,r):
        k=r.u()
        if k==0:return ("EarlyParamRegion",r.u(),r.symbol()[1])
        if k in (3,6):return ("Region",k)
        raise ValueError(("unimplemented region",k))

    def generic_args(self,r):
        n=r.u()
        if n>200:raise ValueError(("large arg list",n))
        out=[]
        for _ in range(n):
            tag=self.enum(r,2)
            if tag==0:out.append(("Lifetime",self.region(r)))
            elif tag==1:out.append(("Type",self.ty(r)))
            else:raise ValueError("unimplemented const generic")
        return tuple(out)

    def adt_shape(self,r):
        # Nominal ADT identity is its resolved DefId and generic arguments. Rust additionally
        # encodes the definition inline. Consume and validate each field before reading those args.
        n=r.u()
        if n>2048:raise ValueError(("implausible AdtDef variant count",n))
        for _ in range(n):
            self.skip_defid(r)
            if self.enum(r,1):
                self.enum(r,1);self.skip_defid(r)
            r.symbol()
            if self.enum(r,1)==0:self.skip_defid(r)
            else:r.u()
            fields=r.u()
            if fields>8192:raise ValueError(("implausible field count",fields))
            for _ in range(fields):
                self.skip_defid(r);r.symbol()
                if self.enum(r,1):self.skip_defid(r)
                if self.enum(r,1):
                    self.skip_defid(r);_,offsets=w.span(self.data,r.p);r.p=offsets[0][1]
                self.enum(r,1)
                if self.enum(r,1):self.skip_defid(r)
            assert self.enum(r,1)==0,"tainted ADT"
            r.byte()
        r.raw(2)
        if self.enum(r,1):
            if self.enum(r,1):self.enum(r,7)
            self.enum(r,1)
        for _ in range(2):
            if self.enum(r,1):r.u()
        r.byte()
        if self.enum(r,1):raise ValueError("unimplemented scalable repr")
        r.raw(8)

    def ty(self,r):
        at=r.p;tag=r.u()
        if tag>=128:
            to=tag-128
            assert 0<to<at,"invalid type shorthand"
            return self.at_type(to)
        if tag in (0,1,7,21):return (tag,)
        if tag in (2,3,4):return (tag,r.u())
        if tag==5:
            definition=self.did(r)
            self.adt_shape(r)
            return (tag,definition,self.generic_args(r))
        if tag==6:return (tag,self.did(r))
        if tag==10:return (tag,self.ty(r))
        if tag==11:return (tag,self.ty(r),self.enum(r,1))
        if tag==12:return (tag,self.region(r),self.ty(r),self.enum(r,1))
        if tag==22:
            n=r.u();assert n<1024
            return (tag,tuple(self.ty(r)for _ in range(n)))
        if tag==23:return (tag,self.enum(r,1),self.enum(r,3),self.did(r),self.generic_args(r))
        if tag==24:return (tag,r.u(),r.symbol()[1])
        raise ValueError(("unimplemented actual TyKind",tag))

    @cache
    def at_type(self,pos):
        return self.ty(w.S.Reader(self.data,pos))

    def header(self,pos):
        r=w.S.Reader(self.data,pos)
        trait=self.did(r)
        args=self.generic_args(r)
        assert args and args[0][0]=="Type"
        flags=(self.enum(r,2),self.enum(r,1),self.enum(r,1))
        return {"trait":trait,"args_including_self":args,"polarity_safety_constness":flags}, r.p


def remap_terms(value,normalize):
    # A resolved DefId is (crate-name/extra, full rooted DefKey chain). Each leaf of the
    # type AST travels through this exact same native DefKey join, including nested helpers.
    if (isinstance(value,tuple) and len(value)==2 and isinstance(value[0],tuple)
            and len(value[0])==2 and isinstance(value[1],tuple) and value[1] and isinstance(value[1][0],tuple)
            and value[1][0][0]=="CrateRoot"):
        return normalize(value)
    if isinstance(value,(tuple,list)):return [remap_terms(v,normalize)for v in value]
    if isinstance(value,dict):return {k:remap_terms(v,normalize)for k,v in value.items()}
    return value
