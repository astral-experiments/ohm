"""Recover the actual Cargo builds, linker executions, binary identities and literal CLI behavior."""
import argparse,gzip,hashlib,json,re,struct,zipfile
from pathlib import Path
H=lambda b:hashlib.sha256(b).hexdigest()
def mch(b):
 assert b[:8]==bytes.fromhex('cffaedfe0c000001') and struct.unpack_from('<I',b,12)[0]==2
 n,clen=struct.unpack_from('<II',b,16);cur=32;end=32+clen;sections=[]
 for _ in range(n):
  tag,size=struct.unpack_from('<II',b,cur);assert size>=8 and cur+size<=end<=len(b)
  if tag==0x19:
   ns=struct.unpack_from('<I',b,cur+64)[0];assert 72+80*ns<=size
   for i in range(ns):
    p=cur+72+80*i
    if b[p:p+32].split(bytes(1),1)[0]==b'__text' and b[p+16:p+32].rstrip(bytes(1))==b'__TEXT':
     length,offset=struct.unpack_from('<QI',b,p+40);assert length>0 and offset+length<=len(b)
     sections.append([length,H(b[offset:offset+length])])
  cur+=size
 assert cur==end and len(sections)==1
 return sections[0]
def main():
 arg=argparse.ArgumentParser()
 arg.add_argument('archive',type=Path)
 arg.add_argument('sha256')
 arg.add_argument('output',type=Path)
 arg.add_argument('--fixed',action='store_true')
 opts=arg.parse_args()
 archive=opts.archive
 with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==opts.sha256
 with zipfile.ZipFile(archive) as z:
  names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
  rd=lambda n:json.loads(z.read(n)); raw=lambda n:gzip.decompress(z.read(n+'.gz'))
  pair=rd('pair.json');expected={'P':'82911b516fb35608fd70ada4deb6f8429277f410','C':'7924254acf6ee5a17473ac47dfb33b5842d72005'}
  assert {role:v['source'] for role,v in pair['products'].items()}==expected
  cargo=rd('fixed-cargo-293.json') if opts.fixed else rd('release.json')
  if opts.fixed:
   assert cargo['commit']=='735e1528ed741015c57676dccf05dbdc0ff7bed1'
   enroll=rd('293-runtime/pair.json')
   assert all(enroll[r]['sdk']['cargo']==cargo['binary'] for r in 'PC')
  arms=('PC','CP') if opts.fixed else ('signed',)
  programs={}
  for k in names:
   if k.startswith('objc2-cli-programs/'):
    im=gzip.decompress(z.read(k));s=H(im);assert Path(k).stem==s and struct.unpack_from('<4I',im)[:2]==(0xfeedfacf,0x100000c) and struct.unpack_from('<I',im,12)[0]==2
    programs[s]={'size':len(im),'text':mch(im)}
  assert 2<=len(programs)<=4*len(arms)
  rows={};hits=0
  for k in names:
   if not k.startswith('objc2-cli/') or not k.endswith('/verified.json') or '/dyld/' in k:continue
   parts=k.split('/')
   if len(parts)==5:_,role,group,step,_=parts;arm='signed'
   else:_,arm,role,group,step,_=parts
   assert arm in arms and role in 'PC'
   top='/'.join(parts[:-3])+'/'
   sdk=rd(top+'installation.json')
   assert sdk['cargo']==(cargo['binary'] if opts.fixed else cargo['cargo'])
   if opts.fixed: assert sdk==enroll[role]['sdk']
   base=k.removesuffix('verified.json')
   row=rd(k);out,err,es=[raw(base+n) for n in ('stdout','stderr','exec.json')]
   streams=row['streams'].get('streams',row['streams']);assert streams=={'stdout':H(out),'stderr':H(err),'native_events':H(es)}
   msgs=list(map(json.loads,out.splitlines()));ev=json.loads(es);good=step!='invalid'
   assert msgs[-1]=={'reason':'build-finished','success':good} and row['code']==(0 if good else 101)
   units=[m for m in msgs if m['reason']=='compiler-artifact'];objc,=[m for m in units if m['target']['name']=='objc2' and m['target']['kind']==['lib']]
   assert row['command']==['cargo','+ohm','build','-p','ty','--bin','ty','--locked','--offline','-j4','--message-format=json']
   assert len(units)==row['units'] and sorted(u['target']['name'] for u in units if not u['fresh'])==row['dirty']
   assert objc['package_id'].endswith('#objc2@0.6.3')
   dep=raw(base+'objc2-0.dep');proof,=row['objc2']
   assert proof['dep']==H(dep) and proof['fresh']==objc['fresh'] and proof['hard']==(b'ohm-untracked-relink-inputs' in dep)
   assert proof['hard']==(role=='P') and proof['recheck']==(role=='C')
   full=[];relay=[];links=[];drivers=[];ordinary=[]
   for e in ev:
    a=e['argv']
    if e['path'].endswith('/native/bin/cargo'):
     if Path(a[0]).name=='ohm-link-cc' and Path(a[0]).parent.name.endswith('.rlink-objects'):drivers.append(e['pid'])
     else:ordinary.append(e['pid'])
    if e['path'].endswith('/native/bin/rustc') and '--crate-name' in a:
     n=a[a.index('--crate-name')+1]
     if n!='___' or not any(s.startswith('--print') for s in a):(relay if any('link-only' in s for s in a) else full).append(n)
    if Path(e['path']).name in ('ld','lld','ld64','wild','rust-lld','ld64.lld','ld-prime','ld-classic'):
     assert e['path'].endswith('/XcodeDefault.xctoolchain/usr/bin/ld')
     name,=[p for flag,p in zip(a,a[1:]) if flag=='-o'];links.append(name)
   assert row['native']['full']==sorted(full) and row['native']['link_only']==sorted(relay) and len(links)==len(row['native']['linkers'])
   assert len(ordinary)==1 and row['native']['cargo']==1
   if opts.fixed:
    receipt=rd(base+'native-link-receipt.json')
    assert sorted(drivers)==sorted(d['pid'] for d in row['native']['cargo_link_driver'])==sorted(d['pid'] for d in receipt['driver_processes'])
    assert receipt['stock_links']==len(links)
   else:assert not drivers
   assert row['links']==[p for p in links if re.fullmatch(r'ty(?:-[0-9a-f]{16})?',Path(p).name)]
   binaries=[u for u in units if u['target']['name']=='ty' and u['target']['kind']==['bin'] and not u['profile']['test'] and u['executable']]
   if good:
    assert len(binaries)==1 and row['product']['raw'] in programs
    code=rd(base+'ty-exit.json');stdout=raw(base+'ty-stdout');stderr=raw(base+'ty-stderr')
    assert H(stdout)==row['product']['stdout'] and not stderr and H(stderr)==row['product']['stderr'] and code==row['product']['exit'] and programs[row['product']['raw']]['text']==row['product']['text']
    if step=='cold' or group=='clean-old':assert code==0 and stdout==b'All checks passed!\n'
    else:
     assert code==1 and stdout.splitlines()==[
     b'@list.py:1:14: error[invalid-assignment] Object of type `Literal["literal"]` is not assignable to `int`',
     b'@package/main.py:1:14: error[invalid-assignment] Object of type `Literal["directory"]` is not assignable to `int`',b'Found 2 diagnostics']
    hits+=1
   else:
    errors=[(m['message'].get('code') or {},m['message']['message']) for m in msgs if m['reason']=='compiler-message']
    assert not binaries and not row['links'] and row['product'] is None and any(c.get('code')=='E0425' and 'ohm_objc2_response_file_missing' in text for c,text in errors)
   rows[arm,role,group,step]={'drivers':len(drivers),'full':full,'relay':relay,'ld':len(links),'ty_links':len(row['links']),'raw':row['product']['raw'] if good else None,'units':len(units)}
  for arm in arms:
   for role in 'PC':
    assert rows[arm,role,'clean-old','clean']['raw']!=rows[arm,role,'clean-new','clean']['raw']
    for step in ('cold','edit','repeat-1','repeat-2','repair'):
     assert rows[arm,role,'visits',step]['raw']==rows[arm,role,'clean-old' if step=='cold' else 'clean-new','clean']['raw']
  assert len(rows)==16*len(arms) and hits==14*len(arms) and {x['raw'] for x in rows.values() if x['raw']}==set(programs)
  data={'archive':opts.sha256,'programs':programs,'commands':len(rows),'native_cli':hits,
        'counts':{arm:{r:{s:{k:v for k,v in x.items() if k!='raw'} for (a,g,seq,s),x in rows.items() if (a,g,seq)==(arm,r,'visits')} for r in 'PC'} for arm in arms}}
  with opts.output.open('x') as f:json.dump(data,f,indent=2);f.write(chr(10))
  for arm in arms:
   for r,d in data['counts'][arm].items():print(arm,r,{s:(len(x['full']),len(x['relay']),x['drivers'],x['ld'],x['ty_links']) for s,x in d.items()})

if __name__=='__main__':main()
