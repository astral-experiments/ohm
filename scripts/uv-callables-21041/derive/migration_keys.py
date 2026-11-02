"""Read the exact macro, source, trait-index and descendant witnesses of a renamed native impl."""
from collections import Counter,defaultdict
from functools import cache
from hashlib import sha256
import json
import identity_wire as w
from trait_terms import Terms,remap_terms


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(",",":")).encode()


def token(data):
    return sha256(encode(data)).hexdigest()


def unit(data,bank):
    root,traits=w.decode(data)
    table=root["tables"]
    rows=lambda key:w.S.di.rows(data,table[key])
    ids=w.S.di.keyed(data,root)
    defs={}
    for i,(raw,ptr) in enumerate(zip(ids,rows("def_keys"),strict=True)):
        if not any(ptr):raise ValueError("missing emitted DefKey")
        k,_=w.decl_fields.key_at(data,int.from_bytes(ptr,"little"),ids)
        key=raw.hex()
        assert key not in defs
        defs[key]=(i,k["parent"],k["kind"],tuple(k["name"]) if k["name"] else (),k["disambiguator"])
    presence=rows("rdr_hashes.local")
    presence.extend([b""]*(len(defs)-len(presence)))
    assert len(defs)==len(presence)
    @cache
    def path(key):
        if key is None:return ()
        i,up,kind,name,slot=defs[key]
        return path(up)+((kind,name,slot),)
    names={path(key):key for key in defs}
    assert len(names)==len(defs)
    extern={0:(root["crate_name"],root["extra_filename"])}
    public={}
    for n,nm,ph,extra,_ in w.deps(data,root):
        extern[n]=(nm,extra)
        public[n]=ph
    @cache
    def resolved(cn,key,macro=False):
        if cn==0:
            return (extern[cn],tuple((kind, val[-1]if val else None,slot)for kind,val,slot in path(key)))
        return (extern[cn],bank.declarations(*extern[cn],public[cn],macro)[key])
    terms=Terms(data,resolved)
    impl_index={}
    for (cn,k),items in traits.items():
        for i,self_type in items.items():
            assert i not in impl_index
            decl=(cn,k)
            if self_type and len(self_type)==3:
                tag,cnum,item=self_type
                value=(tag,cnum,item)
            else:
                value=self_type
            impl_index[i]=(decl,value)
    tables={n:rows(n) for n in ("expn_that_defined","expn_data","expn_hashes","source_map","impl_trait_header")}
    def pointer(name,index):
        xs=tables[name]
        return int.from_bytes(xs[index],"little")if index<len(xs)else 0
    def source_file(index):
        at=pointer("source_map",index)
        assert at>0,("source map",index)
        r=w.S.Reader(data,at)
        tag,local=r.u(),r.u()
        assert (tag,local)==(0,0),("not a remapped real filename",tag,local)
        rel,remap,full=[r.string()for _ in range(3)]
        scope=r.u();hash_kind,sz=r.u(),r.u();assert sz==32
        src=r.raw(sz).hex()
        return rel,remap,full,scope,hash_kind,src
    def local_span(span):
        kind,ctxt,lo,ln,file,cn=span
        assert kind==0 and cn is None,("nonlocal derive callsite",span)
        return source_file(file),lo,ln,ctxt
    def span_source(span):
        kind,ctxt=span[:2]
        if kind==2:return ("partial",ctxt)
        if kind==0:return ("local",local_span(span))
        assert kind==1 and span[-1] in public
        return ("external",extern[span[-1]],span[2:5],ctxt)
    def expansion_lineage(exid):
        chain=[];seen=set()
        while exid:
            assert exid not in seen and len(chain)<64,"cyclic or unbounded native expansion"
            seen.add(exid);ptr=pointer("expn_data",exid);assert ptr and pointer("expn_hashes",exid)
            r=w.S.Reader(data,ptr);tag=r.u()
            if tag==1:kind=(tag,r.u(),r.symbol())
            elif tag in (2,3):kind=(tag,r.u())
            else:raise ValueError(("unsupported native expansion",tag))
            cn,previous=r.u(),r.u();assert cn==0,("external expansion ancestor",cn)
            call,loc=w.span(data,r.p);r.p=loc[0][1];dis=r.u()
            definition,loc=w.span(data,r.p);r.p=loc[0][1]
            allowed=[r.symbol() for _ in range(r.u())];edition=r.u();present=r.u();assert present in (0,1)
            declared=None
            if present:
                n,h=r.u(),r.raw(8).hex()
                crate,suffix=extern[n]
                proc=n!=0 and isinstance(crate,str) and bool(bank.files.get("lib"+crate+suffix+".so"))
                declared=resolved(n,h,proc)
            chain.append((exid,kind,previous,span_source(call),dis,span_source(definition),allowed,edition,declared))
            exid=previous
        return chain
    expansion_lineage=cache(expansion_lineage)
    @cache
    def actual(exp):
        i,up,kind,name,slot=defs[exp];assert kind=="Impl"
        ptr=pointer("expn_that_defined",i);assert ptr>0
        r=w.S.Reader(data,ptr);cnum,exid=r.u(),r.u();assert cnum==0 and exid
        rp=pointer("expn_data",exid);hp=pointer("expn_hashes",exid);assert rp and hp
        r=w.S.Reader(data,rp);assert (r.u(),r.u())==(1,2),"not a native derive expansion"
        name=r.symbol();parent=(r.u(),r.u())
        sp,seg=w.span(data,r.p);r.p=seg[0][1]
        dis=r.u();defsp,seg=w.span(data,r.p);r.p=seg[0][1]
        allowed=[r.symbol()for _ in range(r.u())]
        edition=r.u();present=r.u();assert present==1 and edition<=4
        macro_crate=r.u();macro_key=r.raw(8).hex()
        assert macro_crate in public and defsp[0]==1 and defsp[-1]==macro_crate
        assert i in impl_index and pointer("impl_trait_header",i)>0,"missing typed impl trait header/index"
        tr,receiver=impl_index[i]
        tr=resolved(*tr)
        if receiver and len(receiver)==3:
            receiver=(receiver[0],resolved(receiver[1],receiver[2]))
        macro=resolved(macro_crate,macro_key,True)
        header_pos=pointer("impl_trait_header",i)
        header,header_end=terms.header(header_pos)
        assert header["trait"]==tr and header_end>header_pos,"trait header disagrees with native fast-reject index"
        return {"parent":path(up),"macro":[macro,name[1]],"native_macro_public":public[macro_crate],"expansion_lineage":expansion_lineage(exid),
                "callsite":local_span(sp),"expansion_disambiguator":dis,"expansion_index":exid,"parent_expn_ref":parent,
                "expansion_hash":data[hp:hp+16].hex(),"edition":edition,"allowed_internal":allowed,"trait":tr,"simplified_self":receiver,
                "typed_header":header,"impl_trait_header_position":header_pos,"impl_trait_header_end":header_end,"owner_slot":slot}
    return {"root":root,"names":names,"definitions":defs,"presence":presence,"actual":actual,"path":path,
            "data":data,"impl_index":impl_index,"external":extern}


def diff(a,b,banks):
    left,right=[unit(blob,bank)for blob,bank in zip((a,b),banks,strict=True)]
    names=[v["names"] for v in (left,right)]
    common=names[0].keys()&names[1].keys()
    changed=[names[0].keys()-names[1].keys(),names[1].keys()-names[0].keys()]
    roots=[]
    for nameset in changed:
        top={p for p in nameset if not p[:-1] in nameset}
        assert all(p[-1][0]=="Impl" for p in top),("outside an impl",len(top))
        roots.append(top)
    def reachable(s,p):
        i=s["definitions"][s["names"][p]][0]
        return bool(any(s["presence"][i]))
    def gather(s,paths,rset):
        result=defaultdict(list);unresolved=[]
        sub={r:[] for r in rset}
        for p in paths:
            parents=[p[:i] for i in range(1,len(p)+1) if p[:i] in sub]
            assert len(parents)==1,("ambiguous changed root",p)
            r=parents[0];sub[r].append([p[len(r):],reachable(s,p)])
        by_parent=defaultdict(list)
        for path in paths:
            by_parent[path[:-1]].append(path)
        # Named nested helpers and their impls may themselves refer to a migrated parent.
        # Project only actual, separately authenticated impl owners, even for these references.
        logical=lambda p:tuple((kind, value[-1] if value else None, slot) for kind,value,slot in p)
        qualified={logical(p):p for p in paths if p[-1][0]=="Impl"}
        assert len(qualified)==sum(p[-1][0]=="Impl" for p in paths)
        current=s["external"][0]
        def normalize_ref(ref):
            crate,path=ref
            if crate!=current:return ref
            p=tuple(tuple(v)for v in path)
            return [crate,normalize_path(p)]
        def normalize_path(p):
            normal=[]
            for i,attr in enumerate(p):
                link=qualified.get(p[:i+1])
                normal.append([attr[0],attr[1],owner_tag(link)] if link else attr)
            return normal
        active=set()
        @cache
        def owner_tag(path):
            if path in active:raise ValueError(("cyclic generated ownership",path))
            active.add(path)
            try:
                typed,ev=identity(path)
                return token([normalize_path(logical(path[:-1])),typed])
            finally:
                active.remove(path)
        def identity(path):
            ev=s["actual"](s["names"][path])
            typed={k:ev[k] for k in ("macro","callsite","expansion_disambiguator","expansion_lineage","edition","allowed_internal","trait","simplified_self")}
            typed["trait"]=normalize_ref(typed["trait"])
            typed["full_impl_trait_header"]=remap_terms(ev["typed_header"],normalize_ref)
            receiver=typed["simplified_self"]
            if receiver and len(receiver)==2 and isinstance(receiver[1],tuple):
                typed["simplified_self"]=[receiver[0],normalize_ref(receiver[1])]
            return typed,ev
        for r in sorted(rset):
            owners=[]
            def typed_subtree(path):
                kind,name,slot=path[-1]
                leaf=[kind,name,slot,reachable(s,path)]
                if kind=="Impl":
                    mark,evidence=identity(path)
                    leaf[2]=mark
                    owners.append((path,evidence,owner_tag(path)))
                children=[typed_subtree(child) for child in by_parent[path]]
                return token([leaf,sorted(children)])
            try:
                subtree=typed_subtree(r)
            except (ValueError,AssertionError,KeyError,IndexError)as exc:
                import traceback
                stack=traceback.extract_tb(exc.__traceback__)
                unresolved.append([r,str(exc)or (stack[-1].name+":"+str(stack[-1].lineno)),type(exc).__name__]);continue
            contract={"outside_parent":r[:-1],"all_typed_nested_definitions":subtree}
            assert owners and owners[0][0]==r
            records={k:{"path":p,"def_key":s["names"][p],"slot":ev["owner_slot"],"expansion":ev["expansion_index"],
                     "raw_expn_hash":ev["expansion_hash"],"lineage":token(ev["expansion_lineage"]),
                     "trait_header_position":ev["impl_trait_header_position"],"macro":ev["macro"],"macro_public":ev["native_macro_public"]}for p,ev,k in owners}
            assert len(records)==len(owners),"non-unique typed owner"
            result[token(contract)].append([r,owners[0][1],len(sub[r]),records])
        return result,unresolved
    collections=[gather(s,p,root)for s,p,root in zip((left,right),changed,roots,strict=True)]
    maps=[j[0]for j in collections]
    agreements=[]
    everything=maps[0].keys()|maps[1].keys()
    for k in sorted(everything):
        x,y=[d.get(k,[])for d in maps]
        if len(x)!=1 or len(y)!=1:continue
        (xr,ex,n,no),(yr,ey,m,mo)=x[0],y[0]
        assert n==m and no.keys()==mo.keys() and all(no[k]["lineage"]==mo[k]["lineage"] and no[k]["slot"]<2**31<=mo[k]["slot"] for k in no)
        agreements.append({"baseline":xr,"treatment":yr,"identity":k,"descendants":n,"typed_owners":len(no),"unique_native_owner_keys":sorted(no),"trait":ex["trait"],"simplified_self":ex["simplified_self"],
                           "macro":ex["macro"],"actual_callsite":ex["callsite"],"owners":[no,mo],"expansion_refs":[[e["expansion_index"],e["parent_expn_ref"],e["expansion_hash"]] for e in (ex,ey)],
                           "macro_hashes":[ex["native_macro_public"],ey["native_macro_public"]],"header_positions":[ex["impl_trait_header_position"],ey["impl_trait_header_position"]]})
    return {"crate":left["root"]["crate_name"],"complete_local_definitions":[len(n) for n in names],"common":len(common),
            "changed_paths":[len(k) for k in changed],"changed_impl_roots":[len(x) for x in roots],
            "common_reachability_changes":sum(reachable(left,k)!=reachable(right,k) for k in common),
            "unresolved":[dict(Counter(str(e[1]) for e in j[1])) for j in collections],
            "examples": [s[1][:4] for s in collections],"ambiguous_examples":[[[x[1]["macro"],x[1]["trait"],x[1]["simplified_self"],x[1]["impl_trait_header_position"]]for val in d.values()if len(val)>1 for x in val[:1]][:3] for d in maps],"unmatched":[sum(len(v)for k,v in d.items()if len(v)!=1 or len(maps[1-i].get(k,[]))!=1)for i,d in enumerate(maps)],
            "paired":agreements,"unequal_keys":[[v[0][1] for k,v in d.items() if k not in maps[1-i]][:3]for i,d in enumerate(maps)]}

def accept(result):
    old,new=result["complete_local_definitions"]
    assert old==new==result["common"]+result["changed_paths"][0],"lost definition"
    assert result["common_reachability_changes"]==0,"unrelated reachability change"
    assert result["unmatched"]==[0,0] and result["unresolved"]==[{},{}],"unknown or ambiguous generated definition"
    paired=result["paired"];count=sum(r["descendants"] for r in paired)
    assert result["changed_paths"]==[count,count],"unaccounted rooted descendants"
    assert result["changed_impl_roots"]==[len(paired)]*2,"unaccounted generated subtree"
    owners=[key for item in paired for key in item["unique_native_owner_keys"]]
    assert len(owners)==len(set(owners)) and all(
        set(group["unique_native_owner_keys"])==old.keys()==new.keys() and
        all(old[k]["lineage"]==new[k]["lineage"] and old[k]["expansion"]==new[k]["expansion"] and old[k]["slot"]<2**31<=new[k]["slot"] for k in old)
        for group in paired for old,new in [group["owners"]]),"multiple or inconsistent native owners"
    return {"definitions":old,"common":result["common"],"migrated_paths":count,"maximal_roots":len(paired),"typed_impl_owners":len(owners)}
