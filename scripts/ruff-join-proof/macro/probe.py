from pathlib import Path
import subprocess,os,json,hashlib,re,shutil
q=Path.cwd();classes=q.name=='source-class';flags=[];w=q/'fixture';w.mkdir();e={k:os.environ[k]for k in ('HOME','USER','LANG','PATH','RUSTUP_HOME','CARGO_HOME')if k in os.environ};e.update(CARGO_TARGET_DIR=str(q/'target'),CARGO_BUILD_BUILD_DIR=str(q/'shared'),RUSTC_BOOTSTRAP='shape_observer')
def sha(data):return hashlib.sha256(data).hexdigest()
def write(name,text):
 p=w/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(text);return p
write('Cargo.toml','[workspace]\nmembers=["provider","observer","client"]\nresolver="2"\n')
for package in ('provider','observer','client'):
 text='[package]\nname="shape_'+package+'"\nversion="0.1.0"\nedition="2021"\n'
 if package=='observer':text+='[lib]\nproc-macro=true\n'
 if package=='client':text+='[dependencies]\nshape_provider={path="../provider"}\nshape_observer={path="../observer"}\n'
 write(package+'/Cargo.toml',text)
write('provider/src/lib.rs','mod a; mod b;\n')
write('observer/src/lib.rs','''#![feature(proc_macro_span)]
use proc_macro::{TokenStream,TokenTree,Literal};
#[proc_macro]
pub fn inspect(s: TokenStream) -> TokenStream {
 let mut i=s.into_iter();let mode=i.next().unwrap().to_string();
 let a=i.next().unwrap().span();let b=i.next().unwrap().span();assert!(i.next().is_none());
 let joined=a.join(b);
 let mut result=match mode.as_str(){
  "plain"=>Literal::u64_unsuffixed(u64::from(joined.is_some())),
  "range"=>Literal::u64_unsuffixed(joined.map_or(0, |s|(s.byte_range().start as u64).wrapping_shl(32) | s.byte_range().end as u64)),
  "bad"=>Literal::string("expected real type error"),
  _=>panic!(),
 };
 if let Some(s)=joined{result.set_span(s);}
 TokenTree::Literal(result).into()
}
''')
for mode in ('plain','range','bad'):
 write('client/src/bin/'+mode+'.rs',f'const VALUE:u64=shape_provider::left!({mode});\nfn main(){{println!("{{VALUE}}");}}\n')
left='#[macro_export]\nmacro_rules! left { ($m:ident)=>{ $crate::tail!($m 17) } }\n'
tail='#[macro_export]\nmacro_rules! tail { ($m:ident $x:tt)=>{ ::shape_observer::inspect!($m $x 29) } }\n'
source_a=write('provider/src/a.rs','// pad\n'+left+tail);source_b=write('provider/src/b.rs','// pad\n');stamp=source_a.stat().st_mtime_ns
def produce(name,pa,pb,pl,rg):
 for p,text in ((source_a,pa),(source_b,pb)):
  p.write_text(text);os.utime(p,ns=(stamp,stamp))
 rs={}
 for mode in ('plain','range','bad'):
  out=q/'results'/name/mode;out.mkdir(parents=True);argv=['cargo','+ohm',*flags,'build','-p','shape_client','--bin',mode,'--locked','--offline','-j2','--message-format=json']
  with(out/'stdout').open('wb')as so,(out/'stderr').open('wb')as se:r=subprocess.run(argv,cwd=w,env=e,stdout=so,stderr=se,timeout=60)
  rows=[json.loads(x)for x in(out/'stdout').read_text().splitlines()if x.startswith('{')]
  errors=[x['message']for x in rows if x['reason']=='compiler-message'and x['message']['level']=='error'and x['message'].get('code')]
  assert (r.returncode==0)==(mode!='bad')and [x['code']['code']for x in errors]==(['E0308']if mode=='bad' else[]),(name,mode,r.returncode)
  tgt=Path(e['CARGO_TARGET_DIR']);f,=[p for p in tgt.rglob('libshape_provider*.rmeta')if p.is_file()and not p.is_symlink()];raw=f.read_bytes();(out/'provider.rmeta').write_bytes(raw);head=subprocess.check_output(['rustc','+ohm',f,'-Zls=public_hash'],env=e,text=True).strip();hdr=subprocess.check_output(['rustc','+ohm',f,'-Zls=root'],env=e,text=True);private=re.search(r'private hash ([a-f0-9]{32}) stable_crate_id',hdr)[1];diags=[x['spans']for x in errors]
  rec={'public':head,'private_hash':private,'full':sha(raw),'len':len(raw),'exit':r.returncode,'diagnostic_spans':diags,'codes':[x['code']['code']for x in errors],'nonfresh':[x['target']['name']for x in rows if x['reason']=='compiler-artifact'and not x['fresh']]}
  if mode!='bad':
   exe=tgt/'debug'/mode;v=int(subprocess.check_output([exe]));rec.update(verdict=v,elf=sha(exe.read_bytes()));ea=q/'bodies'/rec['elf'];ea.parent.mkdir(exist_ok=True);ea.write_bytes(exe.read_bytes());assert (v==pl if mode=='plain'else(v==0 if rg==0 else v>0)),(name,mode,v)
   ds=[p for p in tgt.rglob(mode+'*.d')if p.is_file()and not p.is_symlink()and p.parent.name=='out'];assert len(ds)==1,(name,mode,ds);body=ds[0].read_bytes();(out/'consumer.d').write_bytes(body);rec['foreign_marker']=b'ohm-foreign-span-bytes'in body;assert classes or rec['foreign_marker']==bool(pl),(name,mode,rec)
  rs[mode]=rec;(out/'proof.json').write_text(json.dumps(rec,indent=2,sort_keys=True)+'\n')
 print(name,rs['plain']['public'],rs['plain']['verdict'],rs['range']['verdict'],flush=True);return rs
subprocess.run(['cargo','+ohm','generate-lockfile','--offline'],env=e,cwd=w,check=True);out={};short='// pad\n';long='// pad with 37 more visible source bytes........\n'
if classes:
 e['CARGO_INCREMENTAL']='0'
 literal='#[macro_export]\nmacro_rules! left { ($m:ident)=>{ ::shape_observer::inspect!($m %s17%s29) } }\n'
 prefix_long=long[:-1];prefix_short=short[:-1]
 stages={'literal':short+literal%(' ',' ') +long,'equal_size_displaced':long+literal%(' ',' ')+short,'column':short+literal%(' '*65540,' '*65540)+long,'column_65536':short+literal%(' '*131076,' '*4)+long,'two_macros_same':short+left+tail,'two_files':short+left}
 assert len(stages['literal'])==len(stages['equal_size_displaced'])and len(stages['column'])==len(stages['column_65536'])
 for name_arm,flags0 in [('normal',[]),('full-hash-diagnostic',['-Zohm-defaults=no'])]:
  flags[:]=flags0
  for name,body in stages.items():
   label=name_arm+'-'+name;split=name=='two_files'
   for folder in ('target','shared'):
    src=q/folder
    if src.exists():src.rename(q/(folder+'-before-'+label))
   out[label]=produce(label,body,short+(tail if split else ''),int(not split),int(not split))
  for n1,n2 in [('literal','equal_size_displaced'),('column','column_65536')]:
   assert out[name_arm+'-'+n1]['range']['verdict'] != out[name_arm+'-'+n2]['range']['verdict']
 (q/'completed.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n')
 raise SystemExit(0)
for name,split,prefix in [('same_source',False,short),('same_lines_prefix_padding',False,long),('other_file',True,long),('independent_other_file',True,long),('restored_same_source',False,short)]:
 if name=='independent_other_file':
  for folder in ('target','shared'):
   src=q/folder
   if src.exists():src.rename(q/(folder+'-frozen-warm'))
 out[name]=produce(name,prefix+left+(''if split else tail),short+(tail if split else''),int(not split),int(not split))
assert out['same_source']['range']['verdict']!=out['same_lines_prefix_padding']['range']['verdict']
for mode in('plain','range','bad'):
 for key in ('public','full','exit','diagnostic_spans','codes',*(()if mode=='bad'else('elf','verdict','foreign_marker'))):
  assert out['other_file'][mode][key]==out['independent_other_file'][mode][key],(mode,key)
(q/'completed.json').write_text(json.dumps(out,sort_keys=True,indent=2)+'\n')
