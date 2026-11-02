"""Additional source, native epoch, exact hardware, fresh-host, and blocking-clock checks."""
from collections import Counter
from fractions import Fraction
from math import comb
from pathlib import Path
import inspect,json,os,runpy,shutil,subprocess,sys
import core as c
m=c.m;S=c.HERE;D=S/'domain';ev=runpy.run_path(str(S/'thread-meter/exec_events.py'))
def unpack(mod,arc,origin,role):
 orig=inspect.getsource(mod.unpack);old="extras={'allocator.log'} if role==ROLES[1] else set()"
 std={'allocator.log','coroutine-oracle.zip','coroutine-oracle.json','coroutine-oracle.log','callables-oracle.zip','callables-oracle.json','callables-oracle.log'}
 if role==c.ROLES[1]:std|={'domain-oracle.zip','domain-oracle.json','domain-oracle.log'}
 c.guard(orig.count(old)==1,'changed archive membership contract');g=dict(mod.__dict__);exec(compile(orig.replace(old,'extras='+repr(std)),str(S/'domain/pinned-enroll.py'),'exec'),g);g['unpack'](arc,origin,role)
 import receipt
 receipt.oracle(origin)
 if role==c.ROLES[1]:
  v=runpy.run_path(str(D/'verify_domain.py'))['validate'](origin/'domain-oracle.zip',origin/'domain-oracle.json','candidate')
  c.guard(v['actual_changed_signature']=='E0061'and v['verified_raw_provider_counts']['empty-edit']['warm']==dict.fromkeys(('read_adt','read_reference','read_str'),0),'incorrect domain oracle in compiler build')
def migration():
 w,tmp=c.host();pool=tmp/'ctfe22-root-sdks';o=w/'trait-results/intake/domain-native';o.mkdir()
 source=[pool/r for r in c.ROLES];e=runpy.run_path(str(D/'epoch.py'))['run'];e(*source,o/'epoch','actual')
 proof=m.read(o/'epoch/passed.json');c.guard(proof['signed_argv_refusal_both_directions']and proof['same_sdk_self_loaded_before_and_after']and proof['no_header_edit']and proof['no_compiler_version_override']and proof['reader_compilations']==10,'cross-epoch refusal')
 f=runpy.run_path(str(D/'fixture/oracle.py'))['main'];outputs={}
 for role,g,root,v in zip(c.ROLES,['control','candidate'],source,[1,0]):
  f(root,D/'fixture',o/g,g);res=m.read(o/g/'qualified.json')
  c.guard(res['role']==g and res['actual_empty_edit_typeck']==dict.fromkeys(('read_adt','read_reference','read_str'),v)and res['registered_foreign_transitions']==11,'true local foreign method transitions')
  outputs[role]={'oracle':m.filesha(o/g/'qualified.json'),'actual_empty_edit_typeck':res['actual_empty_edit_typeck']}
 m.save(o/'accepted.json',{'roles':outputs,'epochs':m.filesha(o/'epoch/passed.json'),'modes':10,'canonical_inputs':m.filesha(S/'pair.json')})
def boot():
 w,tmp=c.host();p=w/'trait-results';ready=m.read(p/'calibration.json')['ready'];now=Path('/proc/sys/kernel/random/boot_id').read_text().strip();ids={f['boot']for f in c.PAIR['prior_boots'].values()}
 c.guard(now==ready['boot']and len(ids)==len(c.PAIR['prior_boots'])and now not in ids,'previously enrolled host or changed boot')
 m.save(p/'fresh-boot.json',{'boot':now,'excluded':sorted(ids),'calibration':m.filesha(p/'calibration.json'),'coordinator':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'plan':m.filesha(S/'study.json')})
def zero(path,state):
 """Trace one genuine unchanged command without touching the separately measured command."""
 path.mkdir();argv=c.CHECK;command=m.SRC
 identity=ev['file_id'](m.RUSTC);m.save(path/'compiler-image.json',{'id':identity,'sha256':m.filesha(m.RUSTC),'path':str(m.RUSTC)});ev['capture'](path,argv,m.ENV,command,identity);return check_zero(path,state)
def check_zero(path,state):
 request=m.read(path/'kernel-events.json');z=ev['decode'](request);root=z['root'];images=z['images'];c.guard(images[0]['argv']==c.CHECK and images[0]['pid']==root and z['exits'][root]==0,'wrong unchanged parent')
 wanted=m.read(path/'compiler-image.json');c.guard(wanted['path']==str(m.RUSTC)and len(wanted['id'])==3 and len(wanted['sha256'])==64,'missing selected compiler identity')
 rust=[v for v in images if v['file']==wanted['id'] or Path(v['exe']).name.startswith('rustc') or (v.get('argv')and v['argv'][0]==str(m.RUSTC))]
 c.guard(not rust,('unchanged command executed compiler',rust));c.guard(not (path/'stdout').stat().st_size and b'Finished 'in(path/'stderr').read_bytes(),'unchanged native completion')
 out={'state':state,'rustc_images':0,'root':root,'images':len(images),'events_sha256':m.filesha(path/'kernel-events.json')}
 f=path/'zero.json'
 if f.exists():c.guard(m.read(f)==out,'changed unchanged-exec receipt')
 else:m.save(f,out)
 return out
def hypothesis(metrics):
 p=metrics['uv_metadata']['raw_control_candidate'];c.guard(len(p)==8 and all(a>0 and b>0 for a,b in p),'missing true primary retired instructions')
 ratios=[Fraction(b,a)for a,b in p];wins=sum(v<Fraction(4,5)for v in ratios);prob=Fraction(sum(comb(8,j)for j in range(wins,9)),256)
 from statistics import median
 holds=[median(ratios[:4]),median(ratios[4:])]
 return {'primary':'uv_metadata','strict_candidate_over_control_below':.80,'raw_candidate_over_control':[float(v)for v in ratios],'wins':wins,'one_sided_exact_sign_p_ties_counted_against':float(prob),'two_hold_median_ratios':[float(v)for v in holds],'qualified':all(v<Fraction(4,5)for v in holds)and prob<=Fraction(1,20),'secondary':'all eight processes, their sum, inherited whole-command hardware instructions, paired uninstrumented blocking-wait wall'}
