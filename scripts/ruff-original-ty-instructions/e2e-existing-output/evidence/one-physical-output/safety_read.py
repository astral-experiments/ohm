"""Reopen corruption, native changes, and terminal correctness independently from the full hosted ZIP."""
from pathlib import Path
from zipfile import ZipFile
import json,gzip,hashlib,re,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import read_functional as main
def run(archive,head,run_id,digest):
 r=main.main(archive,head,run_id,digest);stages=r['stages'];reference=r['registration']['reference'];proof={}
 ze=ZipFile(archive);names=set(ze.namelist())
 def raw(n):return gzip.decompress(ze.read(n))if n.endswith('.gz')else ze.read(n)
 def row(n):return json.loads(raw(n))
 h=lambda b:hashlib.sha256(b).hexdigest()
 if 'corrupt-preset.json'in names:
  c=row('corrupt-preset.json');assert c['inverse_full_sha256']==reference['new']and c['sha256']!=reference['new']and len(c['sha256'])==64
  assert c['byte_before']^c['byte_after']==1 and 0<c['text_offset']<c['bytes'] and c['mode']&0o111
  assert ((c['method']=='in-place'and c['old']==c['new'])or(c['method']=='atomic-one-byte-copy-after-ETXTBSY'and c['busy_attempts']>0 and c['old']!=c['new']))
  proof['physical_one_byte_corruption']=c
 for k in ('mid-output','rename-output','exclusive-collision','corrupt','replace'):
  if k+'-complete.json'not in names:continue
  q=stages[k];assert q['input_eligible'] and not q['published']and any(a[0].startswith('output-')for a in q['refused'])
  assert q['source_elf']['sha256']==reference['new']and q['cargo_terminal']=={'reason':'build-finished','success':True}
  proof[k]={'refused':q['refused'],'source_groups':q['source_groups'],'full_elf':reference['new']}
 if 'exclusive-collision'in proof:
  v=row('exclusive-collision-complete.json')['mutation'];assert v['old_link_count_after_native_repair']==0 and v['sentinel_sha256']==h(b'untouched native race witness before the exclusive open\n')
  proof['exclusive-collision']['held_sentinel_after_full_link']=v
 for k in ('earlier','four','native-repair','save-repair','final'):
  if k+'-complete.json'not in names:continue
  s=stages[k];a=row(k+'-complete.json')
  assert not s['published'] and s['cargo_terminal']=={'reason':'build-finished','success':True}and s['verified']==[[]]
  image=s['source_elf']['sha256'];assert (image!=reference['new']if k=='four'else True)
  if k=='four':assert a['exit']==83
  if k in ('earlier','four','native-repair'):assert not s['input_eligible']
  proof[k]={'full_elf':image,'input_key':s['input_proof']['key'],'inputs':s['input_proof']['inputs'],'actual_mutation':a.get('mutation'),'native_exit':a.get('exit')}
 for k,diagnostic in (('save',b'generation changed'),('malformed',b'DELIBERATELY')):
  if k+'/resources.json'not in names:continue
  q=stages[k];assert q['cargo_terminal']=={'reason':'build-finished','success':False}and q['resources']['exit']==101 and not q.get('published')
  msg=raw(k+'/stderr')+raw(k+'/stdout.jsonl');assert diagnostic in msg
  proof[k]={'exit':101,'diagnostic':diagnostic.decode(),'combined_output_sha256':h(msg)}
 if 'withheld-old-fails/stdout'in names:
  bad=raw('withheld-old-fails/stdout');assert b'source_text'in bad and b'script_tag'in bad and b'FAILED'in bad;proof['held_out_old_failed']=h(bad)
 for k in ('signed-independent-new','signed-untouched-warm1','signed-untouched-warm2'):
  if k+'/inventory.json.gz'not in names:continue
  q=row(k+'/inventory.json.gz');assert q['state']=='bfa2407e98ee1343caeefd02b4b69043509baa8c'and len(q['executables'])==102
  physical=q['executables'][q['binary']];assert physical['elf']['sha256']==reference['new']and physical['elf']['bytes']==227979336 and physical['unit'][1:3]==['e2e',['test']]
  proof[k]={'bytes':physical['elf']['bytes'],'same_complete_sha256':physical['elf']['sha256'],'inventory':len(q['executables'])}
 if r['complete']:
  assert set(('mid-output','rename-output','exclusive-collision','corrupt','replace','earlier','four','native-repair','save-repair','final','save','malformed','signed-independent-new','signed-untouched-warm1','signed-untouched-warm2'))<=set(proof)
 return {'source':r['registration'],'complete':r['complete'],'zip_sha256':digest,'physical_safety':proof}
if __name__=='__main__':print(json.dumps(run(*sys.argv[1:]),indent=2,sort_keys=True))
