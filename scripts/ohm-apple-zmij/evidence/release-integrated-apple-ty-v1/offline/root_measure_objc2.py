"""Independently reopen all ordinary native times, typed graphs, executable copies and disk rows."""
import argparse,collections,gzip,hashlib,itertools,json,math,re,statistics,sys,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import root_qualify_objc2 as native
from disk import disk
from application import visits, env, same
from native import Dataset
H=lambda b:hashlib.sha256(b).hexdigest()
P,C='9b4b11ce8cb84020be10dc54a6426807bfa87caa','01dccb633d12cc0124c06e02c858aff74af1dcea'
A,B='4710e1aa962b13720cf64aa84eb279c5333896d7','915bb2b4bf9ae7eee47cf55646bbfebae254a23b'
F='fd55a13d0220748794ba3c7c9556ef8ceed8591f'
STEPS=('cold','edit','repeat-1','repeat-2')
DESIGN='Release-integrated Cargo fd55 with held markers, prior versioned CRC parent versus published #281 rustc on the ordinary Apple ty CLI v1'
OLD=b'All checks passed!\n'
NEW=b'@list.py:1:14: error[invalid-assignment] Object of type `Literal["literal"]` is not assignable to `int`\n@package/main.py:1:14: error[invalid-assignment] Object of type `Literal["directory"]` is not assignable to `int`\nFound 2 diagnostics\n'
def signature(body):
 messages=list(map(json.loads,body.splitlines()));assert messages[-1]=={'reason':'build-finished','success':True}
 units=[x for x in messages if x['reason']=='compiler-artifact']
 def key(x):return json.dumps([x[k] for k in ('package_id','target','profile','features','filenames','executable')],sort_keys=True,separators=(',',':'))
 def mine(x):return '/ruff/crates/ty/' in x['target']['src_path'] or (x['package_id'].endswith('#objc2@0.6.3') and x['target']['kind']==['lib'])
 roster=sorted(map(key,units));assert len(set(roster))==len(roster)
 assert len([x for x in units if mine(x) and x['target']['name']=='ty' and x['target']['kind']==['bin'] and x['executable']])==1
 return {'roster_sha256':H(json.dumps(roster).encode()),'count':len(roster),'dirty':sorted(key(u) for u in units if not u['fresh']),
         'focus':sorted([key(x),x['fresh']] for x in units if mine(x))}
def check(archive,checksum,stage,kind="rust"):
 assert kind in ("rust","cargo")
 with archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==checksum
 with zipfile.ZipFile(archive) as z:
  names=z.namelist();assert len(names)==len(set(names)) and z.testzip() is None
  rd=lambda n:json.loads(z.read(n));raw=lambda n:gzip.decompress(z.read(n))
  allsets=list(itertools.combinations(range(12),6))
  if kind=='rust':
   top='objc2-clock-'+stage+'/';reg=rd(top+'registration.json');end=rd(top+'result.json')
   subjects=reg['subjects'];assert subjects==end['subjects'] and subjects['compiler']==[P,C] and subjects['ruff']==[A,B] and subjects['cargo']==F
   assert subjects['Ruff']==H(z.read('objc2-cli/mechanism.json')) and subjects['providers']==H(z.read('provider-matrix/terminal.json'))
   assert reg['harness']==end['harness'] and reg['primary']=='repeat-1' and reg['design']==DESIGN
   allocation=int(H(' '.join((DESIGN,P,C,A,B,F)).encode()),16)%924
   assert allocation==reg['assignment']==257
   dispatch=end['order'];harness=end['harness'];counter=end['counter_calibration'];positive=end['twofold_first_repeat']
  else:
   top='release-clock-'+stage+'/';reg=rd(top+'registration.json');end=rd(top+'terminal.json')
   assert end['registration']==reg
   subjects=reg['subjects'];sCargo='2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c'
   assert subjects['rust']==subjects['qualified_rust']==C and [subjects['signed_cargo'],subjects['integrated_cargo']]==[sCargo,F] and subjects['ruff']==[A,B]
   assert subjects['integrated_bytes']=='9f09941432a849b13ee6177c2f4b0f35f5d9c350e518688d64325ce513ec532d' and subjects['signed_bytes']==rd('release.json')['cargo']['sha256']
   assert reg['native_gate']==H(z.read('release-cli/terminal.json')) and reg['first_unchanged_primary']
   design='Signed #294 vs release-integrated fd55, one exact published #281 ObjC Rust, independent Apple developer ty installations v1'
   allocation=int(H(' '.join((design,sCargo,F,C,A,B)).encode()),16)%924
   assert allocation==reg['allocation']==428 and reg['design']==design
   dispatch=end['registration']['order'];harness=reg['sources'];counter=end['counter'];positive=end['twofold_qualified']
  assert rd('provider-matrix/terminal.json')['passed'] and rd('provider-matrix/terminal.json')['commands']==392 and not rd('versioned/legacy/terminal.json')['signed_integrated_differences']
  order=(['PC','CP'] if stage=='screen' else ['PC' if i in allsets[allocation] else 'CP' for i in range(12)])
  assert order==reg['order']==dispatch
  v=Dataset(z);raws={}; anchors={};control_images={};structural={}
  for r in 'PC':
   base='objc2-cli/PC/'+r+'/' if kind=='rust' else 'release-cli/PC/'+r+'/C/'
   for step in STEPS:
    rev=A if step=='cold' else B
    prefix=base+'clean-'+('old' if step=='cold' else 'new')+'/clean/'
    prod=rd(prefix+'verified.json')['product']
    anchors[r,step]=prod
    if (r,rev) not in control_images:control_images[r,rev]=visits(v,prefix.rstrip('/'),rev,prod,raws,{},traced=True)
    structural[r,step]=signature(raw(base+'visits/'+step+'/stdout.gz'))
  assert anchors['P','cold']['raw']!=anchors['P','edit']['raw'] and anchors['C','cold']['raw']!=anchors['C','edit']['raw']
  selections=[]
  if kind=='cargo':
   for r,source in (('P',sCargo),('C',F)):
    q=rd('release-cli/PC/'+r+'/C/installation.json')
    assert q['driver']==rd('versioned/sdk-C.json')['driver'] and ('commit-hash: '+source) in q['cargo_version']
    assert q['cargo']['sha256']==subjects['signed_bytes' if r=='P' else 'integrated_bytes']
  inc=[];times=collections.defaultdict(list);disks={};prior=-1;raw_rows=[];cache=[];typed_rows=[]
  for i,roles in enumerate(order,1):
   block={}
   for r in roles:
    d=top+f'pair-{i:02}/'+r+'/'
    block[r]={}
    env(rd(d+'development-environment.json'))
    if kind=='cargo':
     pick=rd(d+'cargo-selection.json');observed=rd('release-cli/PC/'+r+'/C/installation.json')
     assert pick['name']==('signed' if r=='P' else 'aware') and pick['source']==(sCargo if r=='P' else F)
     assert pick['binary']==observed['cargo'] and pick['version']==observed['cargo_version']
     selections.append(dict(pair=i,role=r,source=pick['source'],binary=pick['binary']))
    sessions=rd(d+'development-products.json');assert sessions and all(x['crate']=='ty' for x in sessions)
    diskrows={p[0]:p[1:] for p in json.loads(raw(d+'steady-disk/disk-inodes.json.gz'))}
    for x in sessions:
     for a in x['sessions']:
      inc_path=a['path'].split('/objc2-work/')[1]+'/'
      assert not inc_path.endswith('-working/') and '/ty-' in inc_path and a['graph_bytes']==diskrows[inc_path+'dep-graph.bin'][2]>0 and diskrows[inc_path+'work-products.bin'][2]>0
      obj=sorted(Path(p).name for p,i in diskrows.items() if p.startswith(inc_path) and p.endswith('.o') and i[2])
      assert len(obj)==a['objects']>0 and int(a['work_products'],16)>0 and H(chr(10).join(obj).encode())==a['object_names_sha256']
      cache.append({'pair':i,'role':r,'objects':len(obj),'graph':a['graph_bytes'],'work_products':a['work_products']})
    for step in STEPS:
     base=d+step+'/';row=rd(base+'result.json');t=row['cargo']
     out=raw(base+'stdout.gz');assert t['streams']=={'stdout':H(out),'stderr':H(raw(base+'stderr.gz'))}
     actual=signature(out);ref=structural[r,step]
     assert actual==row['signature'] and ref==row['reference']
     assert all(actual[k]==ref[k] for k in ('roster_sha256','count','focus'))
     assert actual['count']==ref['count'] and actual['count']>=300
     if actual['dirty']!=ref['dirty']:
      inc.append([i,r,step,[list(json.loads(k)[1]['name'] for k in sorted(set(actual['dirty'])-set(ref['dirty']))),list(json.loads(k)[1]['name'] for k in sorted(set(ref['dirty'])-set(actual['dirty']))) ]])
     rev=A if step=='cold' else B;prod=row['product']
     assert row['expected']==anchors[r,step] and row['expected_image']==control_images[r,rev]['native']['norm']
     checked=visits(v,base.rstrip('/'),rev,prod,raws,None,traced=False)
     assert same(checked,control_images[r,rev])
     typed_rows.append({'pair':i,'role':r,'phase':step,'units':actual['count'],'request':actual['roster_sha256'],'dirty':[json.loads(k)[1]['name'] for k in actual['dirty']],'fresh':[[json.loads(u)[1]['name'],f] for u,f in actual['focus']],
                       'raw':prod['raw'],'norm':checked['native']['norm'],'modules':checked['native']['modules_sha'],'receipt':checked['native']['recipe'],'complete_bytes':raws[prod['raw']]['bytes']})
     assert raw(base+'ty-stdout.gz')==(OLD if step=='cold' else NEW) and H(raw(base+'ty-stdout.gz'))==prod['stdout']
     assert raw(base+'ty-stderr.gz')==b'' and rd(base+'ty-exit.json')==prod['exit']==(0 if step=='cold' else 1)
     dep=raw(base+'objc2.dep.gz');assert H(dep)==row['depinfo'] and b'objc2-0.6.3/src/' in dep
     assert (b'ohm-untracked-relink-inputs' in dep)==(r=='P' and kind=='rust') and (b'/dev/null/ohm-recheck-dependent-links-v2:' in dep.splitlines())==(r=='C' or kind=='cargo') and b'/dev/null/ohm-recheck-dependent-links:' not in dep.splitlines()
     if step=='cold':assert 'ns' not in t;continue
     real,user,sy=map(float,re.fullmatch(r'\s*([0-9.]+) real\s+([0-9.]+) user\s+([0-9.]+) sys',z.read(base+'time.txt').splitlines()[0].decode()).groups())
     assert t['stop_ns']>t['start_ns']>prior and t['stop_ns']-t['start_ns']==t['ns'] and (user,sy)==(t['user'],t['system'])
     assert abs(real-t['ns']/1e9)<0.1
     time_raw=z.read(base+'time.txt')
     counts=[int(m[1]) for l in time_raw.splitlines() if (m:=re.fullmatch(rb'\s*(\d+)\s+instructions retired\s*',l))]
     assert counts==([t['instructions']] if 'instructions' in t else [])
     prior=t['stop_ns'];block[r][step]=t['ns']
     raw_rows.append({'pair':i,'role':r,'phase':step,'start':t['start_ns'],'end':t['stop_ns'],'ns':t['ns'],'user':user,'system':sy,'time_l':H(time_raw),'retired_reading':counts[0] if counts else None,**t['streams']})
    block[r]['edit+repeat-1']=block[r]['edit']+block[r]['repeat-1']
    disks[i,r]=disk(z,d+'steady-disk/')
   for step in block['P']:times[step].append([block[r][step] for r in 'PC'])
  scores={}
  for step,pairs in times.items():
   vals=[a/b for a,b in pairs];published=end['metrics']['monotonic_ns'][step]
   pv=statistics.median(vals)
   assert published['raw_PC']==pairs and published['ratios_P_over_C']==vals and published['median_ratio']==pv
   score={'median_P':statistics.median(p[0] for p in pairs)/1e9,'median_C':statistics.median(p[1] for p in pairs)/1e9,'paired':pv,'pairs':pairs}
   if stage=='confirmation':
    ranked=sorted(vals);ci=[ranked[2],ranked[9]]
    log=[math.log(u/2)*(1 if o=='PC' else -1) for u,o in zip(vals,order)]
    observed=statistics.mean(math.log(u/2) for u in vals)
    p=sum(sum(v if k in s else -v for k,v in enumerate(log))/12>=observed-1e-12 for s in allsets)/len(allsets)
    assert ci==published['median_CI_96.14pct'] and p==published['one_sided_balanced_sharp_2x_p']
    score.update(ci=ci,p=p)
   scores[step]=score
  if stage=='confirmation':
   for r in 'CP':
    base=top+'terminal-clean/'+r+'/';row=rd(base+'verified.json')
    assert row['code']==0 and raw(base+'ty-stdout.gz')==NEW and rd(base+'ty-exit.json')==1
    assert same(visits(v,base.rstrip('/'),B,row['product'],raws,{},traced=True),control_images[r,B])
    assert signature(raw(base+'stdout.gz'))['roster_sha256']==structural[r,'edit']['roster_sha256']
   assert positive==(scores['repeat-1']['ci'][0]>2 and scores['repeat-1']['p']<=.05)
  measured_counters='retired_instructions' in end['metrics'];cal=rd('calibration/result.json');assert measured_counters==(cal['retired_instruction_scope']=='whole-tree-calibrated')
  if stage=='screen':assert end['admit_confirmation']==all(t[0]/t[1]>2 for t in times['repeat-1'])
  mCPU='tree_cpu_seconds' if kind=='rust' else 'tree_CPU'
  elapsed_tree=mCPU in end['metrics'];assert elapsed_tree==cal['tree_CPU_calibrated']
  if elapsed_tree:
   for k in ('edit','repeat-1','repeat-2','edit+repeat-1'):
    endpoints=['edit','repeat-1'] if k=='edit+repeat-1' else [k]
    cpu=[[sum(q['user']+q['system'] for q in raw_rows if q['pair']==i and q['role']==r and q['phase'] in endpoints) for r in 'PC'] for i in range(1,len(order)+1)]
    assert all(abs(x-y)<1e-9 for v0,v1 in zip(cpu,end['metrics'][mCPU][k]['raw_PC']) for x,y in zip(v0,v1))
    scores[k]['tree_cpu_seconds']=cpu
  return {'stage':stage,'scores':scores,'raw_clocks':raw_rows,'typed_products':typed_rows,'cache':cache,'counter_scope':cal['retired_instruction_scope'],'order':order,'images':raws,'ordinary_cli_executions':8*len(order),'disk_allocated_MiB_medians':{r:statistics.median(v['allocated'] for (i,k),v in disks.items() if k==r)/2**20 for r in 'PC'},
          'physical_cargo_selections':selections,'harness':harness,'archive':checksum,'counter_calibration':counter,'incidental':inc,'twofold_primary':positive}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('sha');p.add_argument('stage',choices=['screen','confirmation']);p.add_argument('result',type=Path)
 p.add_argument('--comparison',choices=['rust','cargo'],default='rust');a=p.parse_args();summary=check(a.archive,a.sha,a.stage,a.comparison)
 with a.result.open('x') as f:json.dump(summary,f,indent=2);f.write(chr(10))
 print(summary['stage'],{step:[v['median_P'],v['median_C'],v['paired']] for step,v in summary['scores'].items()},summary['counter_calibration'])
