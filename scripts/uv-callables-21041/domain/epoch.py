"""Verify real old/new header refusal and same-SDK reuse, without changing their version strings."""
import hashlib,json,os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
H=Path(__file__).resolve().parent;D=H.parents[2];F=H/'fixture'
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,o):
 with p.open('x')as f:json.dump(o,f,sort_keys=True,indent=2);f.write('\n')
def bins(root):
 ret={}
 for p in sorted(root.rglob('*.bin')):
  with p.open('rb')as f:
   head=f.read(7);assert len(head)==7
   if head[:4]!=b'RSIC':continue
   ver=f.read(head[6]).decode()
  ret[str(p.relative_to(root))]={'epoch':int.from_bytes(head[4:6],'little'),'version':ver,'sha256':sha(p),'bytes':p.stat().st_size}
 return ret
def run(control,candidate,out,mode):
 roots=[Path(control).resolve(),Path(candidate).resolve()];out=Path(out).resolve();out.mkdir();assert mode in('actual','fixture')
 proj=json.loads((H/'source-role.json').read_bytes());shim=[('f22825348d834ad9a8ef3934647181fb69f778ae',43311),(proj['commit'],43317)if mode=='actual'else('4cc83ad906d8cd570c15b4508bc82ec3712cfb81',43309)];zz={}
 for sdk,(rev,epoch) in zip(roots,shim):
  env={'PATH':str(sdk/'bin')+':/usr/bin:/bin','LD_LIBRARY_PATH':str(sdk/'lib'),'RUSTC_BOOTSTRAP':'1','LC_ALL':'C'}
  banner=subprocess.check_output([sdk/'bin/rustc','-vV'],env=env,text=True);assert 'commit-hash: '+rev in banner
  zz[rev]={'sdk':str(sdk),'epoch':epoch,'banner':banner,'driver':sha(next((sdk/'lib').glob('librustc_driver*.so')))}
 def reader(w,folder,n,expect,changed,place='cache'):
  folder.mkdir();sdk=roots[n];epoch=shim[n][1];env={'PATH':str(sdk/'bin')+':/usr/bin:/bin','LD_LIBRARY_PATH':str(sdk/'lib'),'RUSTC_BOOTSTRAP':'1','LC_ALL':'C'}
  common=[str(sdk/'bin/rustc'),'--sysroot',str(sdk),'--edition=2024','-Zthreads=1']
  for name,plus in [('owner',[]),('roster',['--extern','owner=libowner.rlib',*(['--cfg','string']if changed else[])])]:
   cp=subprocess.run(common+['--crate-name',name,'--crate-type=rlib',name+'.rs',*plus],cwd=w,env=env,capture_output=True);assert cp.returncode==0 and not cp.stderr,cp.stderr
  cli=common+['--crate-name','reader','reader.rs','-Ldependency=.','--extern','owner=libowner.rlib','--extern','roster=libroster.rlib','-Cincremental='+place,'-Zassert-incr-state='+expect,'-Zincremental-info','-Zincremental-verify-ich=yes']
  with (folder/'stderr').open('xb')as err,(folder/'stdout').open('xb')as std:cp=subprocess.run(cli,cwd=w,env=env,stdout=std,stderr=err)
  report=(folder/'stderr').read_text();assert cp.returncode==0,(cli,report[-1500:]);assert not (folder/'stdout').stat().st_size
  value=subprocess.check_output([str(w/'reader')],cwd=w,env=env,text=True).strip();assert value==('11 0 0'if changed else'0 0 0')
  mismatches=re.findall(r'\[incremental\] ignoring cache artifact `([^`]+)`: Wrong HEADER_FORMAT_VERSION',report)
  return {'argv':cli,'expected_incremental':expect,'epoch':epoch,'binary':sha(w/'reader'),'output':value,'stderr':sha(folder/'stderr'),'actual_epoch_refusals':mismatches,'headers':bins(w/place)}
 with tempfile.TemporaryDirectory(dir=out)as tmp:
  w=Path(tmp);[(shutil.copyfile(F/(name+'.rs'),w/(name+'.rs')))for name in ('reader','owner','roster')];cache=w/'cache';saved=[];before=[];reports={}
  for i in range(2):
   first=reader(w,out/('seed-'+str(i)),i,'not-loaded',False);second=reader(w,out/('self-'+str(i)),i,'loaded',False);assert first['binary']==second['binary']and not first['actual_epoch_refusals']and not second['actual_epoch_refusals']
   assert set(v['epoch']for v in second['headers'].values())=={shim[i][1]};root,=[x for x in cache.iterdir()if x.is_dir()]
   assert {Path(k).name for k in second['headers']}>={'dep-graph.bin','query-cache.bin'}
   first.update(physical_root=root.name);second.update(physical_root=root.name);reports['seed-'+str(i)]=first;reports['self-'+str(i)]=second
   save_dir=w/('original-'+str(i));cache.rename(save_dir);saved.append((save_dir,root.name));before.append(bins(save_dir))
  for donor,recipient in ((0,1),(1,0)):
   name=str(donor)+'-to-'+str(recipient);cache.mkdir()
   # Present unchanged closed foreign sessions in the reader's ordinary crate cache.
   # The compiler sees its own true version and must reject the original epoch.
   shutil.copytree(saved[donor][0]/saved[donor][1],cache/saved[recipient][1])
   presented=bins(cache)
   assert sorted((Path(k).name,v['sha256'])for k,v in presented.items())==sorted((Path(k).name,v['sha256'])for k,v in before[donor].items())
   fresh=reader(w,out/(name+'-reject'),recipient,'not-loaded',True);assert any('dep-graph' in k or 'query-cache' in k for k in fresh['actual_epoch_refusals']),(name,fresh['actual_epoch_refusals']);assert {Path(k).name for k,v in fresh['headers'].items()if v['epoch']==shim[recipient][1]}>={'dep-graph.bin','query-cache.bin'}
   again=reader(w,out/(name+'-own-reuse'),recipient,'loaded',True);assert not again['actual_epoch_refusals'];cache.rename(w/('retired-'+name))
   cold=reader(w,out/(name+'-cold'),recipient,'not-loaded',True);assert not cold['actual_epoch_refusals']and fresh['binary']==again['binary']==cold['binary'];cache.rename(w/('independent-'+name))
   reports[name]={'source_root':saved[donor][1],'receiver_root':saved[recipient][1],'unaltered_foreign_files_presented':presented,'rejected_then_fresh':fresh,'reused_own':again,'independent_cold':cold}
  assert all(bins(s[0])==original for s,original in zip(saved,before))
  save(out/'passed.json',{'mode':mode,'native_sdk':zz,'genuine_session_headers':reports,'no_compiler_version_override':True,'no_header_edit':True,'signed_argv_refusal_both_directions':True,'same_sdk_self_loaded_before_and_after':True,'reader_compilations':10})
 print(mode,sha(out/'passed.json'))
if __name__=='__main__':run(*sys.argv[1:])
