"""Recompute high procedural-derive slots from each real macro ELF, source ADT and visit order."""
from collections import defaultdict
from functools import cache
import gzip, hashlib, json, os, subprocess
from pathlib import Path
import identity_wire as wire
from origin.native_sip import hash128

HERE=Path(__file__).resolve().parent
REVS={"A":"a2a02424dcba3c3f37cf6b8de5484497dd48651e","B":"9049e07fa6b8e4863807b3a6e6e1293cbf68d0c3"}
@cache
def approved():
    return json.loads(gzip.decompress((HERE/"source-subjects.json.gz").read_bytes()))
@cache
def symbols():
    return json.loads((HERE/"subject-symbols.json").read_bytes())
@cache
def source(repo,revision,filename):
    assert filename.startswith("crates/") and ".."not in Path(filename).parts
    return subprocess.check_output(["git","-C",repo,"show",revision+":"+filename],
        env=dict(os.environ,GIT_NO_LAZY_FETCH="1",GIT_OPTIONAL_LOCKS="0",GIT_ALLOW_PROTOCOL="file"))
def seed(krate,decl,spelling):
    buf=int(krate,16).to_bytes(8,"little")+bytes.fromhex(decl)+spelling.encode()+b"\xff"
    return hash128(buf)[0]&0xffff_ffff
def slot(raw_seed,ordinal):
    return (1<<31)|((raw_seed+ordinal)&0x7fff_ffff)
def prove(label,phase,blob,bank,repo):
    head=wire.root(blob);tables=head["tables"];expected=approved()[phase][label]
    def rows(name):return wire.S.di.rows(blob,tables[name])
    raw_ids=wire.S.di.keyed(blob,head);keys=rows("def_keys")
    assert len(keys)==len(raw_ids)==len(set(raw_ids))
    access={k:rows(k)for k in ("def_kind","def_ident_span","expn_that_defined","expn_data","source_map")}
    def ptr(k,i):
        table=access[k];return int.from_bytes(table[i],"little")if i<len(table)else 0
    @cache
    def file_map(i):
        p=ptr("source_map",i);assert p
        r=wire.S.Reader(blob,p);assert (r.u(),r.u())==(0,0)
        name,root,absolute=[r.string()for _ in range(3)]
        assert name.startswith("crates/")and absolute==root+"/"+name and (r.byte(),r.u(),r.u())==(59,0,32)
        return name,r.raw(32).hex()
    deps={n:(pkg,extra,public)for n,pkg,public,extra,_ in wire.deps(blob,head)}
    @cache
    def expansion(k):
        pos=ptr("expn_data",k);assert pos
        r=wire.S.Reader(blob,pos);assert (r.u(),r.u())==(1,2)
        written=r.symbol()[1];assert isinstance(written,str)
        parent_cn,parent=r.u(),r.u();assert parent_cn==0
        sp,seg=wire.span(blob,r.p);r.p=seg[0][1]
        kind,context,start,n,fi,foreign=sp;assert (kind,context,foreign)==(0,0,None)
        path,md=file_map(fi);assert n>0
        r.u();dsp,seg=wire.span(blob,r.p);r.p=seg[0][1]
        for _ in range(r.u()):r.symbol()
        assert r.u()<=4 and r.u()==1
        cn=r.u();local=r.raw(8).hex();pkg,extra,pub=deps[cn]
        assert isinstance(pkg,str) and dsp[0]==1 and dsp[-1]==cn
        ids=bank.declarations(pkg,extra,pub,True);macro=ids[local]
        assert len(macro)==2 and macro[0]==("CrateRoot",None,0) and macro[1][0]=="MacroNs" and macro[1][2]==0
        elves,stable,_=bank.used[pkg,extra,pub,True]
        assert len(elves)==1 and len(stable)==16
        return (path,start,n,pkg,macro[1][1],written),md,stable,local,elves[0],parent
    groups=defaultdict(list);adts=defaultdict(list);ordinary_high=0
    for i,(h,p)in enumerate(zip(raw_ids,keys,strict=True)):
        pos=int.from_bytes(p,"little");assert pos
        d,_=wire.decl_fields.key_at(blob,pos,raw_ids)
        if d["kind"]=="TypeNs"and ptr("def_kind",i)in(2,3,4)and ptr("def_ident_span",i):
            sp,_=wire.span(blob,ptr("def_ident_span",i))
            if sp[0]==0 and sp[1]==0 and sp[-1]is None:
                fi=sp[4];path,md=file_map(fi);raw=d["name"][1]
                sy=symbols().get(str(raw))if isinstance(raw,int)else raw
                adts[(path,sp[2],sp[3],sy)].append((i,h.hex(),ptr("def_kind",i),md))
        if d["kind"]!="Impl"or d["disambiguator"]<1<<31:continue
        pos=ptr("expn_that_defined",i)
        if not pos:ordinary_high+=1;continue
        rd=wire.S.Reader(blob,pos);cn,ex=rd.u(),rd.u();assert cn==0
        if not ex:ordinary_high+=1;continue
        assert d["parent"] is not None and len(d["parent"])==16
        groups[ex].append((i,h.hex(),d["parent"],d["disambiguator"]))
    gold={tuple(q[:6]):q[6:]for q in expected};assert len(gold)==len(expected)
    seen={};native=[]
    for ex,items in sorted(groups.items()):
        orig,md,stable,decl,elf,parent=expansion(ex)
        assert orig in gold and orig not in seen,(label,orig,"unregistered source origin")
        sha,encoded,token,kind,sym,pos,n,attr,derive,total=gold[orig]
        assert len(items)==total and md==encoded and sym
        p,start,width=orig[:3];src=source(repo,REVS[phase],p)
        assert hashlib.sha256(src).hexdigest()==sha and hashlib.md5(src).hexdigest()+"0"*32==md
        assert hashlib.sha256(src[start:start+width]).hexdigest()==token and src[pos:pos+n].decode().removeprefix("r#")==sym
        assert attr[0]<derive[0]<=start<start+width<=derive[1]<attr[1]<pos
        ids=adts[(p,pos,n,sym)];assert len(ids)==1 and ids[0][2]=={"struct":2,"union":3,"enum":4}[kind] and ids[0][3]==md,(label,orig,sym,kind,ids)
        start_slot=seed(stable,decl,sym)
        rows=[]
        for ordinal,(idx,key,owner,actual)in enumerate(items):
            want=slot(start_slot,ordinal)
            assert actual==want,(label,orig,idx,sym,ordinal,actual,want)
            rows.append([idx,key,owner,ordinal,actual])
        seen[orig]=ex
        native.append({"source":list(orig),"decl":[stable,decl],"native_macro_elf":elf,"subject":[kind,sym,pos,n,*ids[0][:2]],
                       "source_sha256":sha,"native_expansion":[ex,parent],"native_seed":start_slot,"owners":rows})
    assert seen.keys()==gold.keys(),(label,"missing actual derive origins",len(seen),len(gold))
    return {"unit":label,"raw_sha256":hashlib.sha256(blob).hexdigest(),"local_definitions":len(raw_ids),
            "nonexpanded_high_impls":ordinary_high,"high_derive_impls":sum(map(len,groups.values())),"groups":native}
