"""Compare exact release-24 stored metadata rows under their own symbols and public-metadata schema."""
import hashlib,json,pathlib,re,subprocess,sys,zipfile
from collections import Counter
here=pathlib.Path(__file__).resolve().parent;sys.path.insert(0,str(here));import scope_rdr as rd
archive=pathlib.Path(sys.argv[1]);wanted=sys.argv[2];out=pathlib.Path(sys.argv[3])
def fh(p):return hashlib.sha256(p.read_bytes()).hexdigest()
s=here/'schema/compiler/rustc_span/src/symbol.rs';t=here/'schema/compiler/rustc_metadata/src/rmeta/mod.rs'
assert fh(s)=='b432282257901159c6e2758caa570feb305f01c82b1fa67a19cf6616c6ed1b0d'and fh(t)=='939927ea4e04ceeae1cbd63a7be80a91d213f594dafdce596ac0e7815ce8ca2c'
txt=t.read_text().split('define_tables! {',1)[1].split('\n}',1)[0];tables=re.findall(r'^    (\w+): Table<',txt,re.M)
symbols=rd.decode_symbols(s.read_text());assert len(tables)==len(set(tables))==88 and len(symbols)==2314
v='rustc 1.99.0-dev (f5a51d8cc 2026-11-03) (ohm-1.99.0-24) (Ohm metadata 3)'
with archive.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()==wanted
results={}
with zipfile.ZipFile(archive)as z:
 for phase in ('old','edit','repair','independent-clean-new'):
    rec=json.loads(z.read(phase+'/products.json'))['rmeta'];raw=subprocess.check_output(['zstd','-dcq'],input=z.read('bodies/'+rec['sha256']+'.zst'))
    assert len(raw)==rec['size']and hashlib.sha256(raw).hexdigest()==rec['sha256']
    results[phase]=rd.decode(raw,symbols,tables,'ruff',v)
def cmp(pair):
 (a,ds,local,exp,deps),(b,es,other,ex2,de2)=pair
 shared=set(ds)&set(es);common=set(local)&set(other);changed={k for k in common if local[k]!=other[k]}
 return {'old':a,'new':b,'definitions':[len(ds),len(es)],'missing_definitions':[len(ds.keys()-es.keys()),len(es.keys()-ds.keys())],
         'same_named_identity':sum(ds[x][0]==es[x][0]for x in shared),'public_rows':[len(local),len(other)],
         'changed_rows':len(changed),'added_removed_rows':[len(other.keys()-local.keys()),len(local.keys()-other.keys())],
         'expansions':[len(exp),len(ex2)],'expansion_tables_equal':exp==ex2,'changed_expansion_rows':len([k for k in exp.keys() | ex2.keys()if exp.get(k)!=ex2.get(k)]),
         'required_crates':[len(deps),len(de2)],'required_changes':sorted(k for k in deps.keys()|de2.keys()if deps.get(k)!=de2.get(k)),
         'largest_3_substitutions':Counter((local[k],other[k])for k in changed).most_common(3),
         'examples':sorted(ds[k][0]for k in changed)[:20]}
r={'old_to_edit':cmp([results['old'],results['edit']]),'edit_to_clean':cmp([results['edit'],results['independent-clean-new']]),'edit_to_repair':cmp([results['edit'],results['repair']])}
out.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n')
for k,a in r.items():print(k,a['changed_rows'],a['public_rows'],len(a['required_changes']),a['expansion_tables_equal'],a['old']['public']==a['new']['public'])
