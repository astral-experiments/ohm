"""Inspect all previously observed uv_metadata imports in actual uv-client-check products."""
import hashlib,struct
from paths import paths
def require(v,why):
 if not v:raise ValueError(why)
def selected(parse,provider,terminal,enrollment):
 require(enrollment['count']==len(enrollment['A']['wire'])==41 and set(enrollment['A']['wire'])==set(enrollment['B']['wire']),'unregistered imports')
 hdr,defs,*_=parse(provider,'uv_metadata');need=enrollment['A']['wire'];values={}
 _,by_path=paths(defs)
 observed_keys={}
 for original_key,source in need.items():
  path=tuple(tuple(part)for part in source['full_defkey_path']);require(path in by_path,('unresolved complete DefKey path',path))
  key=by_path[path];require(key not in observed_keys.values(),('ambiguous enrolled identity',path));observed_keys[original_key]=key
  if hdr['stable_crate_id']==enrollment['A']['stable_crate_id']:require(key==original_key,('same stable crate should reproduce raw DefPathHash',path,key,original_key))
  value=bytes.fromhex(defs[key][0]);require(value and value[0]==1 and len(value)<=17,('unreachable provider definition',key))
  values[original_key]=f"{int.from_bytes(value[1:],'little'):032x}"
 lib=parse.__globals__;reader=lib['SIG'].original.Reader;readroot=lib['SNAP']['Reader21']
 def root(v):return readroot(v,struct.unpack_from('<Q',v,8)[0]).read()
 r=root(terminal);s=root(provider);require(r['crate_name']=='uv_client' and s['crate_name']=='uv_metadata' and s['stable_crate_id']==hdr['stable_crate_id'],'wrong terminal or provider identity')
 tab=r['tables']['crate_deps'];buf=reader(terminal,tab['position']);found=[];all_inputs=[]
 for _ in range(tab['length']):
  tag=buf.u();require(tag in (0,1,2),'invalid symbol')
  name=buf.string()if tag==0 else reader(terminal,buf.u()).string()if tag==1 else ['preinterned',buf.u()]
  svh=buf.raw(16)[::-1].hex();host=buf.u();require(host in (0,1),'host flag')
  host_hash=buf.raw(16)[::-1].hex()if host else None
  kind,extra,private=buf.u(),buf.string(),buf.u();require(kind<=5 and private in (0,1),'dependency shape')
  all_inputs.append([name,svh,host_hash,kind,extra,private])
  if name=='uv_metadata':found.append((svh,extra))
 require(found==[(hdr['public_svh'],s['extra_filename'])],'terminal does not identify actual provider file and public root')
 return {'stable_crate_id':hdr['stable_crate_id'],'module_extra':s['extra_filename'],'public_svh':hdr['public_svh'],'terminal_dependency':list(found[0]),'all_terminal_crate_deps':all_inputs,'current_wire_ids_by_original':observed_keys,'def_fingerprints':values}
def effects(a,b,c,count=41):
 require(b==c,'incremental B differs from independent B in actual declarations or terminal dependency')
 require(a['stable_crate_id']==b['stable_crate_id'] and a['module_extra']==b['module_extra'] and a['current_wire_ids_by_original']==b['current_wire_ids_by_original'],'unstable crate identity')
 keys=set(a['def_fingerprints']);require(len(keys)==count and keys==set(b['def_fingerprints']),'different stable definitions')
 for s in(a,b):require(s['terminal_dependency']==[s['public_svh'],s['module_extra']],'terminal used a different B/A provider')
 moved=sorted(k for k in keys if a['def_fingerprints'][k]!=b['def_fingerprints'][k])
 return {'observed_original_inputs':count,'changed_projected_inputs':len(moved),'changed_keys':moved,'provider_public_hash_changed':a['public_svh']!=b['public_svh'],'terminal_dependency_and_cold_equivalence':True}
def planned(control,child):
 require(control['changed_projected_inputs']==41 and control['provider_public_hash_changed']is True,'matched ordinary control failed to reproduce the original change')
 require(child['changed_projected_inputs']==0 and child['provider_public_hash_changed']is False,'model failed to give the registered whole-provider cutoff')
