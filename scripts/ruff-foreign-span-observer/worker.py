from pathlib import Path
import subprocess,os,time,sys,hashlib,json,shutil,signal,re,tarfile
src=Path(__file__).resolve().parent;root=Path(os.environ['RUNNER_TEMP'])/'ohm-foreign-join';root.mkdir(exist_ok=True);proof=root/'published';proof.mkdir(exist_ok=True);work=Path(os.environ['GITHUB_WORKSPACE'])/'ruff';sdk=root/'sdk';ru=root/'rustup';home=root/'cargo-home';target=root/'target';shared=root/'shared';hostpath=os.environ['PATH'];OLD='710c60f7135879b05f6c05a34085cd7af5c19e7f';NEW='b00f68a23cedbd3a38fc25bac63638f0f11fc3f0';OLDLOCK='47d65136d6cf3743b88970429f5e3bf39e788afe8c35ca5ce2f94939648086eb'
def hf(p):return hashlib.file_digest(Path(p).open('rb'),'sha256').hexdigest()
def put(p,o):p.write_text(json.dumps(o,indent=2,sort_keys=True)+'\n')
def avail():return int(re.search(r'^MemAvailable:\s+(\d+) kB$',Path('/proc/meminfo').read_text(),re.M)[1])*1024
def guard():
 assert avail()>8*2**30 and shutil.disk_usage(root).free>15*2**30
def git(*a):return subprocess.check_output(['git','-C',work,*a],text=True).strip()
def prereg():
 guard();assert git('rev-parse','HEAD')==NEW and git('rev-parse','HEAD^')==OLD and hf(work/'Cargo.lock')==OLDLOCK and not git('status','--porcelain')
 assert not(proof/'registration.json').exists();put(proof/'registration.json',{'old':OLD,'edited':NEW,'lock':OLDLOCK,'machine':os.uname().machine,'kernel':os.uname().release,'sdk_manifest_sha256':hf(src/'sdk.json'),'source_receiver':{p.name:hf(p)for p in src.iterdir()if p.is_file()},'admission':'One ordinary check of each real revision, then unchanged. Capture the actual last owner only. Replay exact live argv except two private output roots. Require whole rmeta and depfile, all six preimage-checked native stores, 2 foreign joins with 61-byte results, count every Debug entry and independently evaluate the original predicate.'});assert os.uname().machine=='x86_64'
def install():
 manifest=json.loads((src/'sdk.json').read_bytes());asset=manifest['asset'];assert asset['id']==704038224 and len(manifest['members'])==79;arc=root/asset['name'];url='https://github.com/astral-experiments/ohm/releases/download/ohm-1.99.0-23/'+asset['name']
 api='repos/astral-experiments/ohm/releases/assets/'+str(asset['id']);acc={k:os.environ[k]for k in ('PATH','HOME')};acc['GH_TOKEN']=os.environ.pop('OHM_SDK_READ_TOKEN');raw=json.loads(subprocess.check_output(['gh','api',api],env=acc));assert all(raw[k]==v for k,v in asset.items())
 with arc.open('xb')as out:subprocess.run(['gh','api',api,'-H','Accept: application/octet-stream'],stdout=out,env=acc,check=True)
 del acc
 assert arc.stat().st_size==asset['size']and hf(arc)==asset['digest'][7:];lookup={data[0]:(name,data)for name,data in manifest['members'].items()};seen=set()
 with tarfile.open(arc,'r:gz')as archive:
  for member in archive:
   if member.name not in lookup:continue
   dest,data=lookup[member.name];out=sdk/dest;assert out.is_relative_to(sdk)and '..'not in Path(dest).parts and dest not in seen and member.isfile() and member.size==data[2];out.parent.mkdir(parents=True,exist_ok=True)
   with archive.extractfile(member)as inp,out.open('xb')as fp:shutil.copyfileobj(inp,fp)
   assert hf(out)==data[3];out.chmod(data[1]);seen.add(dest)
 assert len(seen)==79
 e={k:os.environ[k]for k in ('HOME','PATH','USER','LANG')if k in os.environ}; e.update({'RUSTUP_HOME':str(ru),'CARGO_HOME':str(home),'CARGO_TARGET_DIR':str(target),'CARGO_BUILD_BUILD_DIR':str(shared),'CARGO_NET_GIT_FETCH_WITH_CLI':'true'});subprocess.run(['rustup','toolchain','link','ohm',sdk],env=e,check=True);r=subprocess.check_output(['rustc','+ohm','-vV'],env=e,text=True);c=subprocess.check_output(['cargo','+ohm','-vV'],env=e,text=True);assert 'd57fd1515986dccecdcece8da85e651bfb4b81f9'in r and '7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed'in c;put(proof/'sdk-proof.json',{'archive':hf(arc),'files':len(seen),'rustc':r,'cargo':c});return e
def capture(label,e,want):
 guard();dest=proof/label;dest.mkdir();argv=['cargo','+ohm','check','-p','ruff','--bin','ruff','--locked','--offline','-j4','--message-format=json'];owner=None;low=avail();t=time.monotonic_ns()
 with (dest/'cargo.jsonl').open('wb')as so,(dest/'stderr').open('wb')as se:
  proc=subprocess.Popen(argv,env=e,cwd=work,stdout=so,stderr=se,start_new_session=True)
  while proc.poll()is None:
   if want and owner is None:
    for ps in Path('/proc').glob('[0-9]*'):
     try:
      pid=int(ps.name)
      if os.getpgid(pid)!=proc.pid or not(ps/'exe').samefile(sdk/'bin/rustc'):continue
      args=[os.fsdecode(x)for x in (ps/'cmdline').read_bytes().split(b'\0')[:-1]]
      if '--crate-name'not in args or args[args.index('--crate-name')+1]!='ty_python_semantic':continue
      v=dict(os.fsdecode(x).split('=',1)for x in (ps/'environ').read_bytes().split(b'\0')[:-1]);cwd=(ps/'cwd').resolve();assert cwd==work and all(not any(s in k for s in ('TOKEN','PASSWORD','SECRET','CREDENTIAL')) for k in v)
      owner=[args,v];break
     except (FileNotFoundError,ProcessLookupError,PermissionError):continue
   low=min(low,avail())
   if low<8*2**30:os.killpg(proc.pid,signal.SIGTERM);proc.wait();raise RuntimeError('Ruff ordinary memory guard')
   time.sleep(.08 if want else .4)
 assert proc.returncode==0,(label,proc.returncode,(dest/'stderr').read_text()[-800:])
 msgs=[json.loads(x)for x in (dest/'cargo.jsonl').read_text().splitlines()if x.startswith('{')];art=[q for q in msgs if q['reason']=='compiler-artifact'];assert len(art)>300 and any(x['target']['name']=='ruff'for x in art);assert not any(q['reason']=='compiler-message'and q['message']['level']=='error'for q in msgs);dirty=[q['target']['name']for q in art if not q['fresh']];put(dest/'roster.json',{'argv':argv,'source':git('rev-parse','HEAD'),'total':len(art),'dirty':dirty,'unit_proof':sorted([(x['package_id'],x['target']['name'],x['target']['kind'],x['features'],x['fresh'])for x in art],key=repr),'minimum_available':low,'elapsed_unscored_ns':time.monotonic_ns()-t,'compiler_diagnostic_sha256':hf(dest/'cargo.jsonl')})
 if want:
  assert owner is not None and 'ty_python_semantic'in dirty
  assert json.loads((dest/'roster.json').read_bytes())['unit_proof']==json.loads((proof/'unchanged-unobserved/roster.json').read_bytes())['unit_proof']
 return owner
def inspect(owner):
 argv,env=owner;assert Path(argv[0]).samefile(sdk/'bin/rustc');normal=Path(argv[argv.index('--out-dir')+1]);meta,=normal.glob('libty_python_semantic-*.rmeta');dep,=normal.glob('ty_python_semantic-*.d');assert b'ohm-foreign-span-bytes'in dep.read_bytes()
 deps=[Path(argv[i+1].split('=',1)[1])for i,x in enumerate(argv)if x=='--extern'];assert all(p.is_file()for p in deps)
 qa=root/'replay';qa.mkdir();(qa/'debug-origins').mkdir();b=qa/'deep-joins';b.mkdir();o=qa/'private-out';o.mkdir();argv[argv.index('--out-dir')+1]=str(o)
 idx,=[i for i,x in enumerate(argv)if x.startswith('incremental=')];older=Path(argv[idx].split('=',1)[1]);oldcrate,=older.glob('ty_python_semantic-*');newi=qa/'inc';shutil.copytree(oldcrate,newi/oldcrate.name);argv[idx]='incremental='+str(newi)
 lib,=(sdk/'lib').glob('librustc_driver*.so');assert hf(lib)=='53aecb7726b1863849a89c4260c169132f98d0d33ba62e0892a06739b6e32e52'==json.loads((src/'sdk.json').read_bytes())['members']['lib/'+lib.name][3];put(qa/'plan.json',{'argv':argv,'driver':{'path':str(lib.resolve()),'sha':hf(lib)}})
 salsa=[p for basedir in {target,shared}for p in basedir.rglob('libsalsa_macros-*.so')];real={p.resolve()for p in salsa};byhash={hf(p)for p in real};assert len(byhash)==1 and real; # same body may have several links; resolve exact mapped path at the first event in the receiver.
 salsa_path=sorted(real,key=str)[0];prefix='<rustc_expand::proc_macro_server::Rustc as rustc_proc_macro::bridge::server::Server>::'
 def nm(p):return subprocess.check_output(['nm','-anS','-C',p],text=True).splitlines()
 offs={x.split(' ',3)[-1][len(prefix):]:int(x.split()[0],16)for x in nm(lib)if ' T '+prefix+'span_'in x};assert len(offs)==16;put(b/'fn-offsets.json',offs)
 macros={x.split(' ',3)[3]:x.split()[0]for x in nm(salsa_path)if re.fullmatch(r'[0-9a-f]+ [0-9a-f]+ [Tt] salsa_macros::[a-z_]+',x)};assert 'salsa_macros::update'in macros;put(b/'macro-entries.json',{'dylib':str(salsa_path),'symbols':macros,'same_physical_sha':byhash.pop()})
 subprocess.run(['cc','-Wall','-Werror','-shared','-fPIC','-O2',src/'unwind.c','-o',b/'unwind.so','-lunwind-ptrace','-lunwind-x86_64','-lunwind','-llzma'],check=True)
 wrap=qa/'wrap.sh';wrap.write_text('#!/bin/bash\nset -eu\npin="$OHM_LICENSED_RUSTC"\n[[ "$1" -ef "$pin" ]]\nshift\nexec -a "$pin" "$pin" "$@"\n');wrap.chmod(0o700);env.update(OHM_LICENSED_RUSTC=argv[0],OHM_F_SPAN_LOG=str(qa/'debug-origins/hits.json'),OHM_F_SPAN_PY=str(src/'observe.py'))
 script=qa/'debug.gdb';script.write_text('set confirm off\nset python print-stack full\nset pagination off\nset disable-randomization off\nset startup-with-shell on\nset exec-wrapper '+str(wrap)+'\nset debuginfod enabled off\nset auto-load off\nset auto-solib-add off\nset print thread-events off\nstart\npython\nimport os,gdb\nexec(compile(open(os.environ["OHM_F_SPAN_PY"]).read(),os.environ["OHM_F_SPAN_PY"],"exec"))\nend\ncontinue\npython\nfinish()\nend\n')
 guard();put(proof/'owner-input.json',{'argv':argv,'externs':{str(p):hf(p)for p in deps},'normal_rmeta_sha256':hf(meta),'normal_d_sha256':hf(dep),'selected_salsa_sha256':hf(salsa_path),'source_o':str(normal),'dependent_search_dirs':len([x for x in argv if x.startswith('dependency=')]),'environment_names':sorted(env)})
 with (proof/'gdb.stdout').open('wb')as so,(proof/'gdb.stderr').open('wb')as se:
  ps=subprocess.Popen(['gdb','--quiet','-nx','-nh','-batch','-x',script,'--args',*argv],env=env,cwd=work,stdout=so,stderr=se,start_new_session=True);until=time.monotonic()+600
  while ps.poll()is None:
   if avail()<8*2**30 or time.monotonic()>until:os.killpg(ps.pid,signal.SIGTERM);ps.wait();raise RuntimeError('diagnostic resource guard')
   time.sleep(.15)
  assert ps.returncode==0
 hits=qa/'debug-origins/hits.json';assert hits.is_file();j=json.loads(hits.read_bytes());shutil.copyfile(hits,proof/'hits.json');assert (o/meta.name).read_bytes()==meta.read_bytes() and (o/dep.name).read_bytes().replace(bytes(o),bytes(normal))==dep.read_bytes();assert j['exit_codes']==[0]and j['events']=={'join':2}and len(j['debugs'])==j['entry_counts'].get('span_debug')==21 and j['entry_counts'].get('span_join')==299 and len(j['actual_returns'])==2
 groups=[q['macro_scope']for q in j['join_sources']];assert all(x and x[-1]=='salsa_macros::update'for x in groups);assert all((int(q['returned'],16)>>32&0xffff)==61 for q in j['actual_returns'])
 owners=[k for k in deps if k.name.startswith('libbitflags-')];assert len(owners)==1;co=owners[0];data=co.read_bytes();id16=bytes.fromhex(j['join_sources'][0]['first']['stable_id']);assert data.count(id16)==1;paths={s[2]for s in j['join_sources'][0]['first']['names']if s[2].endswith('/bitflags-2.9.1/src/public.rs')};assert len(paths)==1;sf=Path(paths.pop());s=sf.read_bytes();ch=hashlib.md5(s).digest();assert data.count(ch)==1;at=j['join_sources'][0]['first']['relative_lo'];assert s[at:at+61]==b'<$PublicBitFlags as $crate::__private::PublicFlags>::Internal';shutil.copyfile(sf,proof/'bitflags-public.rs');shutil.copyfile(co,proof/'bitflags.rmeta');shutil.copyfile(meta,proof/'ty.original.rmeta');shutil.copyfile(o/meta.name,proof/'ty.replayed.rmeta');shutil.copyfile(dep,proof/'ty.original.d');shutil.copyfile(o/dep.name,proof/'ty.replayed.d');put(proof/'verified.json',{'debug_counts':len(j['debugs']),'independently_observing_debug':sum(x['would_independently_observe']for x in j['debugs']),'actual_returns':j['actual_returns'],'producer_source_sha256':hf(sf),'selected_owner_sha256':hf(co),'owner_stable_id_offset':data.index(id16),'source_md5_offset':data.index(ch),'source_text':s[at:at+61].decode(),'normal_rmeta':hf(meta),'full_rmeta_identical':True,'depfile_identical_after_only_outpath':True,'macro_scopes':groups})
if __name__=='__main__':
 prereg();e=install();git('switch','--detach',OLD);assert hf(work/'Cargo.lock')==OLDLOCK; subprocess.run(['cargo','+ohm','fetch','--locked','--target','x86_64-unknown-linux-gnu'],env=e,cwd=work,check=True);capture('old',e,False);git('switch','--detach',NEW);capture('edited',e,False);capture('unchanged-unobserved',e,False);inspect(capture('unchanged-observed',e,True))
