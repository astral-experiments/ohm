"""Run the identical private same-inode provider histories using the authenticated ordinary Rust 1.99 toolchain."""
from pathlib import Path
import gzip,re,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import native,verify_native
from ruff import rt
from study import save,sha,load
import edges,stock_compact
def main():
 tools=stock_compact.install();stock=load(rt.LOG/'stock-sdk.json');assert stock['plain_Cargo'] and stock['version']==stock_compact.COMMIT
 assert stock['executables']==tools and tools['cargo']==sha(rt.SDK/'bin/cargo') and tools['rustc']==sha(rt.SDK/'bin/rustc')
 edges.BARRIER=native.GNU;default=edges.BUILD;table={}
 for watch in ('undeclared','directories','files'):
  decl={'files':'println!("cargo:rerun-if-changed={n}/libqa_owned_external.a");','directories':'println!("cargo:rerun-if-changed={n}");','undeclared':''}[watch]
  edges.BUILD=default.replace('for n in ["early","late"]{','for n in ["early","late"]{'+decl)
  for placement in ('direct','library'):
   label='S-'+watch+'-'+placement;root=rt.LOG/label;root.mkdir()
   edges.run(root,'S',placement,True,stock_source=stock_compact.COMMIT,history=native.mutations)
   j=load(root/'completed.json');cases={r['name']:r for r in j['cases']};assert len(cases)==18 and cases['cold-lower']['answer']=='17 7' and cases['cold-lower']['selected']
   mismatch=[]
   for name,ref in native.PAIRS:
    a,b=cases[name],cases[ref];want=verify_native.expect[name];assert b['exit']==(101 if want is None else 0) and b['answer']==want and b['actual_GNU_linkers']
    if (a['exit'],a['answer'],a['elf'])!=(b['exit'],b['answer'],b['elf']):mismatch.append(name)
   table[label]={'complete':sha(root/'completed.json'),'physical_mutations':sha(root/'physical-provider-bytes.json'),'relative_to_own_clean':mismatch}
   print(label,mismatch,flush=True)
 version=gzip.decompress((rt.LOG/'cargo-stock-version/stdout.gz').read_bytes()).decode()
 cargo_source,=re.findall(r'^commit-hash: ([0-9a-f]{40})$',version,re.M);assert cargo_source.startswith('5f94df478')
 save(rt.LOG/'native-group.json',{'cargo':'stock','cargo_sha':tools['cargo'],'cargo_commit':cargo_source,'source_commits':{'rustc':stock_compact.COMMIT,'cargo':cargo_source},
      'all':table,'order':list(table),'all_role_sources':{'S':stock_compact.COMMIT},'same_stamp':True,'actual_stock_sdk':sha(rt.LOG/'stock-sdk.json')})
if __name__=='__main__':main()
