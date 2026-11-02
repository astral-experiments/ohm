"""Observe foreign inherent methods, invalidation, diagnostics and true compiler providers."""
from collections import Counter
from pathlib import Path
import hashlib,json,os,runpy,shutil,struct,subprocess,sys,tempfile
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def put(p,r):
 with p.open('x')as f:json.dump(r,f,sort_keys=True,indent=2);f.write('\n')
OWNERS=('read_str','read_reference','read_adt')
STATES=[
 ('empty',(), '0 0 0'),('noop',(), '0 0 0'),('empty-edit',('unrelated',),'0 0 0'),
 ('first',('string',),'11 0 0'),('same-domain',('string','unrelated'),'11 0 0'),
 ('switch',('token',),'0 0 31'),('two',('token','shared'),'0 23 31'),
 ('one-left',('shared',),'0 23 0'),('foreign-signature',('string_argument',),'E0061'),
 ('last-removed',(), '0 0 0'),('restored',('string',),'11 0 0')]
def main(sdk,src,out,role,*,inherited_source=None):
 original={'control':'f53496e2dd363b1455fc7e0a9d2dedea1bf7650e','candidate':'77ce0545653df71f43e601c28dde01a5e4f02b09'}
 expected=original[role]
 if inherited_source is not None:
  assert (role,inherited_source) in (('control','10d56274a98801b5ef8f80aab734e835749458e1'),('candidate','ac67101cb973e35ce8ff044cc8014c2c76bab69e')),'unregistered cumulative compiler source'
  expected=inherited_source
 sdk,src,out=[Path(p).resolve()for p in(sdk,src,out)];assert role in('control','candidate');out.mkdir()
 compiler=sdk/'bin/rustc';env={'PATH':str(sdk/'bin')+':/usr/bin:/bin','LC_ALL':'C','RUSTC_BOOTSTRAP':'1','LD_LIBRARY_PATH':str(sdk/'lib')}
 common=[str(compiler),'--sysroot',str(sdk),'--edition=2024','-Zthreads=1','-Zincremental-verify-ich=yes','--error-format=json'];profile=runpy.run_path(str(Path(__file__).resolve().with_name('profile_v9.py')))['Profile']
 def compile(w,folder,name,flags=(),error=None):
  folder.mkdir();args=common+['--crate-name',name,'--crate-type','bin'if name=='reader'else'rlib',name+'.rs']+list(flags)
  with (folder/'stdout').open('xb')as so,(folder/'stderr').open('xb')as se:
   p=subprocess.Popen(args,cwd=w,env=env,stdout=so,stderr=se);rc=p.wait(timeout=45)
  assert rc==(1 if error else 0),(name,rc,(folder/'stderr').read_text()[-1500:]);assert (folder/'stdout').stat().st_size==0
  ed=[json.loads(l)for l in (folder/'stderr').read_text().splitlines()]
  if error:
   actual=[(d['code']['code'],[(x['file_name'],x['line_start'],x['column_start'],x['line_end'],x['column_end'])for x in d['spans']if x['is_primary']])for d in ed if d.get('level')=='error'and d.get('code')];assert len(actual)==1 and actual[0][0]==error and actual[0][1] and all(a[0]=='reader.rs'for a in actual[0][1]),actual
  else:assert not ed,(folder,ed)
  return dict(pid=p.pid,args=args,stderr=sha(folder/'stderr'),outcome=error or 0)
 def readprofile(folder,pid):
  p,=folder.glob('*.mm_profdata');assert int(p.stem.split('-')[-1])==pid
  d=profile(p.read_bytes());seen=Counter();activity=0
  for typ,index,thread,lo,hi,flags in struct.iter_unpack('<QQIIII',memoryview(d.entries)[8:]):
   start=lo|((flags&0xffff0000)<<16);end=hi|((flags&65535)<<32)
   if start>=end or end>=0xfffffffffffe:continue
   ctx=d.label(typ);q=d.label(index)
   if ctx=='GenericActivity':activity+=1
   if ctx=='Query'and q.startswith('typeck_root\x1e'):seen[q.partition('\x1e')[2]]+=1
  assert activity and all(v==1 for v in seen.values()),seen
  return {'profile':sha(p),'owners':{n:seen['reader::'+n]for n in OWNERS},'all_typeck':dict(seen)}
 outdata={};banners=subprocess.check_output([compiler,'-vV'],text=True,env=env);assert 'commit-hash: '+expected in banners.splitlines()
 with tempfile.TemporaryDirectory(dir=out)as temp:
  w=Path(temp);[(shutil.copyfile(src/(n+'.rs'),w/(n+'.rs')))for n in ('owner','roster','reader')]
  compile(w,out/'owner','owner',['--emit=metadata,link'])
  for label,cfgs,expect in STATES:
   phase=out/label;phase.mkdir();up=compile(w,phase/'up','roster',['--emit=metadata,link','--extern','owner=libowner.rlib',*[v for x in cfgs for v in ('--cfg',x)]])
   shutil.copyfile(w/'libroster.rmeta',phase/'libroster.rmeta');res=[]
   for which in ('warm','cold'):
    cache=w/'reader-cache';hold=w/'saved-actual-history'
    if which=='cold'and cache.exists():cache.rename(hold)
    folder=phase/which;prof=phase/(which+'-profile');prof.mkdir()
    observed=compile(w,folder,'reader',['-L','dependency=.','--extern','owner=libowner.rlib','--extern','roster=libroster.rlib','-Cincremental=reader-cache','-Zself-profile='+str(prof),'-Zself-profile-events=default,query-keys'],'E0061'if expect=='E0061'else None)
    if expect!='E0061':
     output=subprocess.check_output([str(w/'reader')],cwd=w,env=env,text=True).strip();assert output==expect,(label,which,output,expect);observed.update(behavior=output,binary=sha(w/'reader'));observed.update(readprofile(prof,observed['pid']))
    res.append(observed)
    if which=='cold':
     if cache.exists():shutil.rmtree(cache)
     if hold.exists():hold.rename(cache)
   assert res[0]['stderr']==res[1]['stderr'] and (expect=='E0061'or res[0]['binary']==res[1]['binary']),(label,res[0],res[1])
   outdata[label]={'cfg':list(cfgs),'expected':expect,'upstream_rmeta':sha(phase/'libroster.rmeta'),'warm':res[0],'cold':res[1]}
   print(label,expect,res[0].get('owners'),flush=True)
 assert outdata['empty']['upstream_rmeta']==outdata['noop']['upstream_rmeta']!=outdata['empty-edit']['upstream_rmeta']
 assert outdata['noop']['warm']['owners']==dict.fromkeys(OWNERS,0)
 assert all(r['cold']['owners']==dict.fromkeys(OWNERS,1)for r in outdata.values()if r['expected']!='E0061')
 put(out/'observed.json',{'role':role,'rustc':banners,'states':outdata})
 gate=outdata['empty-edit']['warm']['owners']
 assert gate==dict.fromkeys(OWNERS,int(role=='control')),(role,'unchanged empty-directory unrelated edit',gate)
 put(out/'qualified.json',{'role':role,'registered_foreign_transitions':len(STATES),'actual_empty_edit_typeck':gate,'warm_cold_binary_and_errors':True,'observed':sha(out/'observed.json')})
if __name__=='__main__':main(*sys.argv[1:])
