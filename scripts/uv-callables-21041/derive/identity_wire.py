"""Selected native -22 metadata readers hash-pinned in wire-origins.json."""
from functools import cache
from pathlib import Path
import hashlib,json,re,struct,subprocess

def bind(parser):
    global SNAP,S,SIG,C,R,Reader,decl_fields,parents,record,case,TARGETS
    SNAP=parser.__globals__["SNAP"]
    SIG=S=SNAP["sig"]
    Reader=SIG.original.Reader
    C={"R":SNAP,"S":SIG,"root":root,"Reader":Reader,"deps":deps}
    R={"K":{"span":span}}
    parents={"T":{"decode":decode}}
    decl_fields=SNAP["crate"].__globals__["keys"]
    expected=json.loads(Path(__file__).with_name("witness-scope.json").read_bytes())
    record=expected["expected_members"];case=expected["source"]
    TARGETS={(kind,name) for kind,rows in record.items() for name in rows}
    assert len(TARGETS)==6

def sha(data):
    return hashlib.sha256(data).hexdigest()

def sh(path):
    return sha(path.read_bytes())


def external_identity_rows(data):
 # std's full metadata omits optional RDR output. The exact wire prefix and all
 # relocated definition tables are common to both; no fabricated RDR fields.
 klass=C['R']['Reader21'];v=klass(data,struct.unpack_from('<Q',data,8)[0]);orig=klass.read.__globals__['original'];assert v.byte()==0;v.string();v.fingerprint();v.fingerprint();v.symbol();assert v.raw(2)==bytes(2);ex=v.string();st=v.raw(8).hex();edition=v.raw(7);assert edition[:2]==bytes(2) and edition[2] in (0,1,2,3) and edition[3:]==bytes(4), ('unsupported native edition/flags',edition.hex())
 fields=orig.source[orig.source.index('    externally_implementable_items: LazyArray'):orig.source.index('    impls: EncodedTraitImpls')]
 for f in re.findall(r'^    (\w+): LazyArray<',fields,re.M):v.array(f)
 assert v.u()in(0,1)
 for f in ('impls','incoherent_impls','interpret_alloc_index'):v.array(f)
 assert v.byte()==0
 for f in ('debugger_visualizers','exportable_items','stable_order_of_exportable_impls','exported_non_generic_symbols','exported_generic_symbols'):v.array(f)
 for f in orig.table_names+['syntax_contexts','expn_data','expn_hashes']:v.table(f)
 v.value('def_path_hash_map');di=C['S'].di;ids=di.keyed(data,{'tables':v.tables});ptrs=di.rows(data,v.tables['def_keys']);assert len(ids)==len(ptrs)
 dk=C['R']['crate'].__globals__['keys'];ent={}
 for i,(kid,pp)in enumerate(zip(ids,ptrs)):
  pos=int.from_bytes(pp,'little')
  if not pos:continue
  q,_=dk.key_at(data,pos,ids);ent[kid.hex()]=(q['parent'],q['kind'],q['name'][1]if q['name']else None,q['disambiguator'])
 @cache
 def get(key):
  if key is None:return ()
  if key not in ent:return None
  parent,*elem=ent[key];up=get(parent);return up+(tuple(elem),)if up is not None else None
 return {'extra_filename':ex,'stable_crate_id':st}, {k:get(k)for k in ent if get(k)is not None}

def identity_rows(data):
 # std's full metadata omits optional RDR output. The exact wire prefix and all
 # relocated definition tables are common to both; no fabricated RDR fields.
 klass=C['R']['Reader21'];v=klass(data,struct.unpack_from('<Q',data,8)[0]);orig=klass.read.__globals__['original'];assert v.byte()==0;v.string();v.fingerprint();v.fingerprint();v.symbol();assert v.raw(2)==bytes(2);ex=v.string();st=v.raw(8).hex();edition=v.raw(7);assert edition in (bytes((0,0,3,0,0,0,0)),bytes((0,0,2,0,0,0,0)))
 fields=orig.source[orig.source.index('    externally_implementable_items: LazyArray'):orig.source.index('    impls: EncodedTraitImpls')]
 for f in re.findall(r'^    (\w+): LazyArray<',fields,re.M):v.array(f)
 assert v.u()in(0,1)
 for f in ('impls','incoherent_impls','interpret_alloc_index'):v.array(f)
 assert v.byte()==0
 for f in ('debugger_visualizers','exportable_items','stable_order_of_exportable_impls','exported_non_generic_symbols','exported_generic_symbols'):v.array(f)
 for f in orig.table_names+['syntax_contexts','expn_data','expn_hashes']:v.table(f)
 v.value('def_path_hash_map');di=C['S'].di;ids=di.keyed(data,{'tables':v.tables});ptrs=di.rows(data,v.tables['def_keys']);assert len(ids)==len(ptrs)
 dk=C['R']['crate'].__globals__['keys'];ent={}
 for i,(kid,pp)in enumerate(zip(ids,ptrs)):
  pos=int.from_bytes(pp,'little')
  if not pos:continue
  q,_=dk.key_at(data,pos,ids);ent[kid.hex()]=(q['parent'],q['kind'],q['name'][1]if q['name']else None,q['disambiguator'])
 @cache
 def get(key):
  if key is None:return ()
  if key not in ent:return None
  parent,*elem=ent[key];up=get(parent);return up+(tuple(elem),)if up is not None else None
 return {'extra_filename':ex,'stable_crate_id':st}, {k:get(k)for k in ent if get(k)is not None}

def decode(blob):
    head=C['root'](blob);tbl=head['tables']['impls'];r=C['Reader'](blob,tbl['position']);tr=[]
    for i in range(tbl['length']):
        crate=r.u();key=r.raw(8).hex();r.array(str(i));array=r.tables[str(i)];tr.append([crate,key,array['position'],array['length']])
    result={}
    for idx,(cn,key,at,count) in enumerate(tr):
        reader=C['Reader'](blob,at);rows={}
        for _ in range(count):
            local=reader.u();tag=reader.u();assert tag in(0,1);short=None
            if tag:
                k=reader.u();assert k<=22
                if k in (5,6,15,16,17,18):short=(k,reader.u(),reader.raw(8).hex())
                elif k in (2,3,4,10,11,13,19):short=(k,reader.u())
                else:short=(k,)
            assert local not in rows;rows[local]=short
        assert reader.p==(tr[idx+1][2]if idx+1<len(tr)else tbl['position'])
        result[cn,key]=rows
    return head,result

def need(value, msg):
    if not value:
        raise ValueError(msg)

def root(b): return SNAP['Reader21'](b, struct.unpack_from('<Q', b, 8)[0]).read()

def symbol(data, r):
    tag = r.u()
    if tag == 0: return r.string()
    if tag == 1: return Reader(data, r.u()).string()
    need(tag == 2, 'symbol tag')
    return ('preinterned', r.u())

def deps(data, head):
    tbl = head['tables']['crate_deps']
    r = Reader(data, tbl['position'])
    for i in range(1, tbl['length']+1):
        name = symbol(data, r)
        svh = r.raw(16)[::-1].hex()
        host = r.u()
        need(host in (0,1), 'host hash')
        if host: r.raw(16)
        kind, extra, private = r.u(), r.string(), r.u()
        need(kind <= 5 and private in (0,1), 'dependency shape')
        yield i, name, svh, extra, private

def span(d,p):
 r=Reader(d,p);tag=r.byte();kind=tag&3;sz=tag>>3
 if kind==3:
  assert 1<=sz<=8;offset=int.from_bytes(r.raw(sz),'little');q=p-offset if tag&4 else offset;value,ranges=span(d,q);return value,[(p,r.p)]+ranges
 ctxt=0 if tag&4 else r.u()
 if kind==2:return (kind,ctxt),[(p,r.p)]
 lo=r.u();length=sz if sz<31 else r.u();idx=r.u();cnum=r.u() if kind==1 else None;return (kind,ctxt,lo,length,idx,cnum),[(p,r.p)]

def macro_elf(path):
 t=subprocess.check_output(['readelf','-SW',str(path)]).decode();entry,=re.findall(r'\]\s*\.rustc\s+PROGBITS\s+\w+\s+(\w+)\s+(\w+)',t);off,size=map(lambda x:int(x,16),entry);b=path.read_bytes()[off:off+size];assert b[:8]==b'rust\0\0\0\n'and int.from_bytes(b[8:16],'little')==len(b)-16;b=b[16:];assert b[:8]==b'rust\0\0\0\n';reader=C['R']['Reader21'](b,struct.unpack_from('<Q',b,8)[0]);assert reader.byte()==0;target=reader.string();private,public=reader.fingerprint(),reader.fingerprint();form,name=reader.symbol();assert reader.raw(2)==b'\1\0';extra=reader.string();stable_id=reader.raw(8)[::-1].hex();assert reader.raw(2)==b'\0\0'and reader.byte()in(2,3)and reader.raw(4)==b'\0'*4
 m=reader.read.__globals__['original'];fields=m.source[m.source.index('    externally_implementable_items: LazyArray'):m.source.index('    impls: EncodedTraitImpls')]
 for field in re.findall(r'^    (\w+): LazyArray<',fields,re.M):reader.array(field)
 assert reader.u() in (0,1);reader.array('impls');reader.array('incoherent_impls');reader.array('interpret_alloc_index');assert reader.byte()==1;proc_macro_decls_static=reader.u();s=reader.byte();assert s==0,s;reader.array('proc_macros')
 for field in ['debugger_visualizers','exportable_items','stable_order_of_exportable_impls','exported_non_generic_symbols','exported_generic_symbols']:reader.array(field)
 for field in m.table_names+['syntax_contexts','expn_data','expn_hashes']:reader.table(field)
 reader.value('def_path_hash_map');head={'tables':reader.tables};ids=SIG.di.rows(b,head['tables']['def_path_hashes']);nonzero=[h for h in ids if any(h)];assert nonzero and len(nonzero)==len(set(nonzero));ks=SIG.di.rows(b,head['tables']['def_keys']);dk=C['R']['crate'].__globals__['keys'];names={}
 for i,v in enumerate(ks):
  if not any(v):continue
  key=dk.key_at(b,int.from_bytes(v,'little'),ids)[0]
  if key['kind']!='MacroNs':continue
  name_key=key['name']; names[ids[i].hex()]={'name':name_key,'index':i,'parent':key['parent'],'disambiguator':key['disambiguator']}
 return {'path':str(path),'sha256':sh(path),'embedded_rmeta_sha256':hashlib.sha256(b).hexdigest(),'root_local_hash':ids[0].hex(),'compiler_stamp':b[16:180].split(b'\xc1',1)[0][1:].decode(),'name':name,'stable_crate_id':stable_id,'public_hash':public,'declarations':names}

def native(blob,exp,src,el,rec,expected,decl):
 h=C['root'](blob);pos=int.from_bytes(S.di.rows(blob,h['tables']['expn_data'])[exp],'little');assert pos;r=S.Reader(blob,pos);assert (r.u(),r.u())==(1,2);_,spelling=r.symbol();assert spelling.split('::')[-1]==decl;parent=(r.u(),r.u());sp,x=R['K']['span'](blob,r.p);r.p=x[0][1];dis=r.u();dp,x=R['K']['span'](blob,r.p);r.p=x[0][1];assert r.u()==0 and r.u()in(2,3)and r.u()==1;cnum=r.u();local=r.raw(8).hex();assert dp[0]==1 and dp[-1]==cnum and cnum>0;assert el['declarations'][local]['name'][1]==decl;(kind,ctxt,lo,ln,file,foreign)=sp;assert (kind,ctxt,foreign)==(0,0,None);tokens=src[lo:lo+ln];assert tokens.decode()==spelling,(tokens,spelling,sp);a=re.search(rb'\b(?:struct|enum|union)\s+([A-Za-z_]\w*)',src[lo+ln:lo+1000]);assert a and a[1].decode()==expected,(expected,sp,a[1]if a else None);return {'source_subject':expected,'resolved_defining_crate':el['name'],'resolved_stable_crate_id':el['stable_crate_id'],'resolved_local_hash':local,'authenticated_exported_defindex':el['declarations'][local]['index'],'macro':decl,'macro_token':spelling,'callsite_byte_range':[lo,lo+ln],'native_impl':rec,'parent_expn':parent,'encoded_cnum':cnum}

def hdr(data):
 r=C['R']['Reader21'](data,struct.unpack_from('<Q',data,8)[0]);assert r.byte()==0;target=r.string();p,q=r.fingerprint(),r.fingerprint();_,name=r.symbol();return name,p,q

def dump(file,src,registry,proc,version):
 blob=file.read_bytes();assert version.encode()in blob[:200];head,impls=parents['T']['decode'](blob);assert head['crate_name']=='uv_pypi_types';ids=S.di.keyed(blob,head);deps={n:(k,v,ex)for k,n,v,ex,_ in C['deps'](blob,head)if n in ('rkyv','rkyv_derive')};assert len(deps)==2 and deps['rkyv'][1:]==(registry['public'],registry['extra']);assert deps['rkyv_derive'][1]==proc['public_hash'];span_rows=S.di.rows(blob,head['tables']['source_map']);positions=sorted({int.from_bytes(e,'little')for e in span_rows if any(e)})+[head['root']];srcid,=[i for i,row in enumerate(span_rows)if any(row)and (pos:=int.from_bytes(row,'little'))in positions and case['file'].encode()in blob[pos:positions[positions.index(pos)+1]]];keys=S.di.rows(blob,head['tables']['def_keys']);exp=S.di.rows(blob,head['tables']['expn_that_defined']);ed=S.di.rows(blob,head['tables']['expn_data']);ass=S.di.rows(blob,head['tables']['associated_item_or_field_def_ids']);dx=lambda i:decl_fields.key_at(blob,int.from_bytes(keys[i],'little'),ids)[0];key_cache={i:dx(i)for i,row in enumerate(keys)if any(row)};module,=[i for i,k in key_cache.items()if k['parent']==ids[0].hex()and k['kind']=='TypeNs'and tuple(k['name'])==('str','simple_json')];result={}
 for tr,idh in registry['traits'].items():
  for idx,short in impls[(deps['rkyv'][0],idh)].items():
   k=key_cache[idx]
   if k['kind']!='Impl'or k['parent']!=ids[module].hex()or not any(exp[idx]):continue
   rt=S.Reader(blob,int.from_bytes(exp[idx],'little'));cnum,eid=rt.u(),rt.u()
   if cnum or not eid:continue
   rd=S.Reader(blob,int.from_bytes(ed[eid],'little'))
   if (rd.u(),rd.u())!=(1,2):continue
   _,spelling=rd.symbol()
   if spelling!='rkyv::'+tr:continue
   rd.u();rd.u();span,_v=R['K']['span'](blob,rd.p)
   if span[0:2]!=(0,0)or span[4]!=srcid:continue
   lo,ln=span[2:4];assert src[lo:lo+ln].decode()==spelling;mt=re.search(rb'\b(?:struct|enum|union)\s+([A-Za-z_]\w*)',src[lo+ln:lo+1000]);assert mt;ty=mt[1].decode()
   if (tr,ty)not in TARGETS:continue
   attrs=ass[idx];pos=int.from_bytes(attrs[::2],'little');count=int.from_bytes(attrs[1::2],'little');assert 0<count<30 and pos>0;ar=S.Reader(blob,pos);members=[]
   for _ in range(count):
    mk=key_cache[ar.u()];assert mk['parent']==ids[idx].hex();members.append([mk['kind'],list(mk['name']),mk['disambiguator']])
   assert members==record[tr][ty]['A']['native_members'],(tr,ty,members);key=tr+'/'+ty;assert key not in result;desc=native(blob,eid,src,proc,ids[idx].hex(),ty,tr);assert desc['encoded_cnum']==deps['rkyv_derive'][0];result[key]={'slot':k['disambiguator'],'full_impl_identity':head['stable_crate_id']+':'+ids[idx].hex(),'module':ids[module].hex(),'declaring_trait':idh,'shape':short,'members':members,'derive':desc}
 assert {tuple(k.split('/'))for k in result}==TARGETS;return {'rmeta_sha256':sha(blob),'rmeta_bytes':len(blob),'public':head['public_svh'],'stable_crate_id':head['stable_crate_id'],'rows':result}
