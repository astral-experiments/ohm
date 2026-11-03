"""Read the whole signed release archive and authenticate the actual same-source Rust metadata."""
import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('zip_sha');p.add_argument('out',type=Path);p.add_argument('--prefix',default='normal-ruff');p.add_argument('--legacy',type=Path,default=Path(__file__).resolve().parent.parent/'ruff-clap-config-help/evidence-release-24')
a=p.parse_args();sys.path.insert(0,str(a.legacy));import scope_rdr as decoder
sha=lambda b:hashlib.sha256(b).hexdigest()
with a.archive.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==a.zip_sha
sd=a.legacy/'schema/compiler';sy=(sd/'rustc_span/src/symbol.rs').read_bytes();tab=(sd/'rustc_metadata/src/rmeta/mod.rs').read_bytes()
assert [sha(sy),sha(tab)]==['b432282257901159c6e2758caa570feb305f01c82b1fa67a19cf6616c6ed1b0d','939927ea4e04ceeae1cbd63a7be80a91d213f594dafdce596ac0e7815ce8ca2c']
sy=decoder.decode_symbols(sy.decode());tab=re.findall(r'^    (\w+): Table<',tab.decode().split('define_tables! {',1)[1].split('\n}',1)[0],re.M)
assert (len(sy),len(tab))==(2314,88);release=json.loads(Path(__file__).with_name('published.json').read_bytes());version=release['linux_sdk']['rustc'].splitlines()[0]+' (Ohm metadata 3)'
with zipfile.ZipFile(a.archive)as z:
 assert len(set(z.namelist()))==len(z.namelist());rd=lambda n:json.loads(z.read(n));prefix=a.prefix+'/';x={};states={};proof={}
 registration=rd('registration.json');assert registration['actual_driver']=='b13243dc392a808cce88cb68486614d04bc00e0a6dc9fdf7a7f13b8335476f01'and registration['source']==['03f787e51e94999977b9a5a32b0153d82d7e2142','fa4a7bca2db70229710892c97b26ea6fb046cfc4']
 for n in ['initial-consumer','producer-NEW','producer-REPAIR','producer-OLD','unchanged-consumer']:
  sel=rd(prefix+n+'/selected.json');raw=subprocess.check_output(['zstd','-qdc'],input=z.read('metadata/'+sel['meta_sha']+'.zst'));assert len(raw)==sel['bytes']and sha(raw)==sel['meta_sha'];x[n]=decoder.decode(raw,sy,tab,'ruff',version);states[n]=sel
  evidence={}
  for tag,owner in [('stable','CheckCommand'),('changed','FormatCommand')]:
   field=rd(prefix+n+'/'+tag+'.json');text=z.read(prefix+n+'/'+tag+'.stderr');assert field['selected_rmeta']==sel['meta_sha'];assert ('::'+owner+')')in field['source'];valid=tag=='stable'or n in ('producer-NEW','producer-REPAIR');assert (field['status']==0)==valid and(not field['status']or b'E0609'in text);evidence[tag]=[field['status'],sha(text)]
  proof[n]=evidence
 first,last=x['initial-consumer'],x['producer-OLD'];ds={k:[first[1].get(k,last[1].get(k)),first[2].get(k),last[2].get(k)]for k in first[2].keys()|last[2].keys()if first[2].get(k)!=last[2].get(k)}
 obs={n:[(r['crate'],r['kind'])for r in rd(prefix+n+'/real-compiler.json')]for n in ('settled-original','producer-NEW','invalid','invalid-again','producer-REPAIR','producer-OLD','unchanged-consumer','settled-after')};assert not obs['settled-original']and not obs['settled-after']
 for n in ('invalid','invalid-again'):assert b'error[E0308]' in z.read(prefix+n+'/stderr')
 native={n:rd(prefix+n+'/native.json')for n in ('initial-consumer','unchanged-consumer')}
 for n,r in native.items():
  for i,h in r['help'].items():assert sha(z.read(prefix+n+'/help-'+i+'.stdout'))==h
 out={'original':a.zip_sha,'lane':a.prefix,'producer_states':states,'consumer_programs':native,'rows':ds,'repaired_new_logical_metadata_equal':x['producer-NEW'][1:]==x['producer-REPAIR'][1:],'old':first[0],'reverse':last[0],'public_rows':[len(first[2]),len(last[2])],'identities':[len(first[1]),first[1]==last[1]],'expansions':[len(first[3]),first[3]==last[3]],'deps':[len(first[4]),first[4]==last[4]],'exact_unchanged_consumer_output':native['initial-consumer']==native['unchanged-consumer'],'rustcs':obs,'unit_graph':rd('unit-graph.json'),'field_probes':proof}
 a.out.write_text(json.dumps(out,indent=1,sort_keys=True)+'\n');print('different/total rows',len(ds),out['public_rows'],'identities/exp/required',out['identities'],out['expansions'],out['deps'],'private same',first[0]['private']==last[0]['private'],'public same',first[0]['public']==last[0]['public'],'identical client',out['exact_unchanged_consumer_output'],'client compilers',obs['unchanged-consumer'],'chosen',out['unit_graph']['chosen'])
