"""Independent symbol, native body and observed Cargo program readback."""
import argparse,collections,hashlib,json,os,struct,subprocess,sys,tempfile,zipfile
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from member_names import read_names
def sha(b):return hashlib.sha256(b).hexdigest()
def elf(raw):
 h=struct.unpack_from('<16sHHIQQQIHHHHHH',raw);assert h[0][:7]==b'\x7fELF\x02\x01\x01' and h[1:3]==(1,62)
 sec=[struct.unpack_from('<IIQQQQIIQQ',raw,h[6]+64*i) for i in range(h[-2])]
 def data(i):
  r=sec[i];return raw[r[4]:r[4]+r[5]] if r[1]!=8 else b''
 def name(b,j):return b[j:b.index(b'\0',j)].decode('utf-8',errors='surrogateescape')
 names=[name(data(h[-1]),s[0])for s in sec];ti,=[i for i,r in enumerate(sec)if r[1]==2];strtab=data(sec[ti][6]);syms=[(name(strtab,n),info,other,idx,off,ln) for n,info,other,idx,off,ln in struct.iter_unpack('<IBBHQQ',data(ti))]
 rel=defaultdict(list)
 for i,r in enumerate(sec):
  if r[1]!=4:continue
  for off,info,add in struct.iter_unpack('<QQq',data(i)):
   nm,ki,vis,ndx,v,ln=syms[info>>32];which=names[ndx]if 0<ndx<len(sec)else ndx
   rel[r[7]].append((off,info&0xffffffff,nm,ki,vis,which,v,ln,add))
 fun={}
 for n,kind,vis,idx,start,length in syms:
  if kind&15!=2 or not idx or not n or not length:continue
  assert n not in fun and start+length<=len(data(idx))
  reloc=[(off-start,*other)for off,*other in rel[idx]if start<=off<start+length]
  fun[n]=(kind,vis,length,sha(data(idx)[start:start+length]),sha(json.dumps(reloc,separators=(',',':')).encode()))
 return fun

OLD='scripts=1\nscripts=1\nvendored-paths=3\n'
NEW='scripts=0\nscripts=1\nvendored-paths=3\n'
FIXTURE=b'#!/usr/bin/env -S uv run --script\n# /// script\n# requires-python = ">=3.11"\n# dependencies = []\n# ///\nprint("fixture")\n'
ROOTS=['35bor4tpfcrfa1dr5j4pk8ivh','cdh33gg8otnl9aaatn38qqbs2']
def put_body(z,entry,file):
    with file.open('wb') as out:subprocess.run(['zstd','-qdc'],input=z.read('native/'+entry['sha256']+'.zst'),stdout=out,check=True)
    with file.open('rb')as inp:assert hashlib.file_digest(inp,'sha256').hexdigest()==entry['sha256']
    assert file.stat().st_size==entry['bytes']
def run(archive):
    root=Path(tempfile.mkdtemp());r={'stages':{},'native_functions':{},'holdout_names':{}}
    def read(z,k):return json.loads(z.read(k))
    def dem(xs):return dict(zip(xs,subprocess.run(['c++filt','-s','rust'],input='\n'.join(xs)+'\n',text=True,capture_output=True,check=True).stdout.splitlines(),strict=True))
    with tempfile.TemporaryDirectory(dir=root)as t,zipfile.ZipFile(archive)as z:
        tmp=Path(t);fixture=tmp/'fixture';fixture.mkdir();(fixture/'script.py').write_bytes(FIXTURE);exe=tmp/'client';rlib=tmp/'lib.rlib';fun={}
        for phase in ('old','edit'):
            r['stages'][phase]={};cmp={}
            for mode in('ordinary','sampled'):
                dir=f'{mode}/{phase}';n=read(z,dir+'/native.json');ans={}
                for crate in('ty_ide','ty_project'):
                    product=n['outputs'][crate]['rlib'];put_body(z,product,rlib);tab=read_names(rlib,crate);obj=tab['members'];expect=n['members'][crate]['bijection'];assert tab==expect
                    ans[crate]={'rlib':product,'count':len(obj),'member_signature':sha(json.dumps([x[1:]for x in obj],separators=(',',':')).encode()),'symbols':tab['symbols'],'symbol_map':tab['symbol_map'],'link_wrapper':tab['link_wrapper'],'metadata':tab['metadata']}
                    if crate=='ty_project'and mode=='ordinary':
                        # Resolve actual existing ordinary symbols for the preregistered second edit.
                        symbols=subprocess.run(['nm','-A','-S','--defined-only',rlib],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=True).stdout.decode().splitlines()
                        keys=('replace_index_diagnostics','set_diagnostics');hits=collections.defaultdict(list)
                        for key in keys:
                            picked=[l for l in symbols if key in l];mangled=[l.split()[-1]for l in picked];names=dem(mangled)if picked else{}
                            for l in picked:
                                raw=l.split(':')[-2];found=[x[2]for x in obj if x[0]==raw];hits[key].append([found[0]if found else raw,names[l.split()[-1]],l.split()[-3]])
                        r['holdout_names'][phase]=hits
                        for name,_,cgu,digest,size in obj:
                            if cgu in ROOTS:
                                raw=subprocess.check_output(['ar','p',rlib,name]);assert len(raw)==size and sha(raw)==digest;fun[phase,cgu]=elf(raw)
                oracle=read(z,dir+'/result.json')['oracle'];put_body(z,oracle['elf'],exe);exe.chmod(0o700);result=subprocess.run([exe,fixture],cwd=tmp,env={'PATH':'/usr/bin:/bin','HOME':str(tmp),'UV_OFFLINE':'1'},capture_output=True,timeout=60)
                assert result.returncode==0 and result.stdout.decode()==(OLD if phase=='old'else NEW)and result.stdout==z.read(dir+'/oracle/stdout')
                r['stages'][phase][mode]={'rlibs':ans,'client_sha256':oracle['elf']['sha256'],'actual_stdout':result.stdout.decode()};cmp[mode]=ans
            for crate in('ty_ide','ty_project'):
                a,b=cmp['ordinary'][crate],cmp['sampled'][crate];assert a['member_signature']==b['member_signature']and a['symbol_map']==b['symbol_map']and a['symbols']==b['symbols']
        for cgu in ROOTS:
            a,b=fun['old',cgu],fun['edit',cgu];names=dem(sorted(a.keys()|b.keys()));common=set(a)&set(b)
            for k in common:assert a[k][:4]==b[k][:4]
            added=b.keys()-a.keys();deleted=a.keys()-b.keys();assert not deleted
            owner='::ScriptFiles>::iter::{closure#0}';same=lambda n:owner in names[n]
            group=[(names[n],a[n][2])for n in a if same(n)]
            r['native_functions'][cgu]={'old':len(a),'edited':len(b),'same_machine_bytes_and_symbol_attributes':len(common),'same_complete_elf_relocation_tuple':sum(a[n]==b[n]for n in common),'all_old_func_bytes':sum(x[2]for x in a.values()),'old_exact_local_script_closure_occurrences':group,'old_closure_native_bytes':sum(x[1]for x in group),'additions':[(names[n],b[n][2],same(n))for n in sorted(added)]}
    root.rmdir();return r
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('archive',type=Path);a.add_argument('--output',type=Path,required=True);a=a.parse_args()
    with a.archive.open('rb')as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='7c624a492e8f746701f650c2d1ead9c50e46865c77318f2b189c6cb8315df081'
    r=run(a.archive);a.output.write_text(json.dumps(r,sort_keys=True,indent=2)+'\n')
    for k,x in r['native_functions'].items():print(k,x['old'],x['edited'],len(x['old_exact_local_script_closure_occurrences']),x['old_closure_native_bytes'],x['all_old_func_bytes'])
    print('heldout',[(k,len(v))for k,v in r['holdout_names']['old'].items()])
