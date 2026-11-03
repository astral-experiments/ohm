import json,time,traceback
def run(t):
 e,root,pub,flip,evict,client,producer,start,body,observe,old_cargo,fixed,upstream,sdk=(t[k]for k in ('e','root','pub','flip_link','evict','client','producer','placeholder','client_source','observe','sdk','candidate','official','sdk'));old_cargo=sdk.sdk/'bin/cargo';out={};failed={};old,new=t['cases']('private')
 for arm in ('stock','fixed','upgrade','stock-split','fixed-split','upstream-split'):
  d=pub/'no-checksums'/arm
  try:
   env={**e,'RUSTFLAGS':'--remap-path-prefix=/ohm-unreachable-mtime=/also-unreachable'};subject=old_cargo if arm.startswith('stock')or arm=='upgrade'else fixed if arm.startswith('fixed')else upstream;flip(subject);evict();producer.write_text(old);client.write_text(start);rs={};out[arm]=rs
   def phase(k,package='selected_client'):
    rs[k]=observe('check',k,d/k,[],env,package);return rs[k]
   o=phase('discover');client.write_text(body);env.update(OLD_VALUE=str(o['fnv']),CHECK_VALUE='1');o=phase('old');phase('old-unchanged');time.sleep(1.08);producer.write_text(new)
   if arm.endswith('-split'):phase('producer-only','selected_producer')
   v=phase('edit');h=phase('next-unchanged')
   if arm=='upgrade':
    assert o['rmeta']!=v['rmeta']==h['rmeta']and v['exit']==h['exit']==0 and o['metadata_mtime_ns']==h['metadata_mtime_ns']
    before={n:t['sdk'].hf(p)for n,p in [('producer',producer),('client',client)]};held=(t['alias'].readlink(),producer.stat().st_mtime_ns,client.stat().st_mtime_ns);flip(fixed);u=phase('fixed-first-unchanged')
    assert held==(t['alias'].readlink(),producer.stat().st_mtime_ns,client.stat().st_mtime_ns)and before=={'producer':sdk.hf(producer),'client':sdk.hf(client)}
   evict();c=phase('independent-clean');time.sleep(1.08);producer.write_text(old);p=phase('repair')
   assert o['exit']==0 and c['errors']==['E0308']and c['exit']==101 and p['exit']==0
   assert c['rmeta']==v['rmeta']and u['rmeta']==c['rmeta'] if arm=='upgrade'else c['rmeta']==v['rmeta']
   if arm=='upgrade':assert u['errors']==['E0308']and'selected_client'in u['rustc_execs']
   elif arm.startswith(('upstream','fixed')):assert v['errors']==h['errors']==['E0308']and'selected_client'in v['rustc_execs']
   elif arm=='stock':assert v['exit']==h['exit']==0 and v['metadata_mtime_ns']==o['metadata_mtime_ns']and 'selected_client'not in v['rustc_execs']
   selected=[p for p in(d/'old').glob('raw-*.d')if 'selected.rmeta'in p.read_text()]
   assert selected and any('# checksum:blake3='in p.read_text()for p in selected)==arm.startswith('fixed')
  except Exception:
   failed[arm]=traceback.format_exc();print(failed[arm],flush=True)
  sdk.put(pub/'no-checksum-results.json',out);sdk.put(pub/'no-checksum-failures.json',failed)
 return failed
