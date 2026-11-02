"""Additional source, native epoch, exact hardware, fresh-host, and blocking-clock checks."""
from collections import Counter
from fractions import Fraction
from math import comb
from pathlib import Path
import inspect,json,os,runpy,shutil,subprocess,sys
import core as c
m=c.m;S=c.HERE;D=S/'domain';ev=runpy.run_path(str(S/'thread-meter/exec_events.py'))
def migration():
 w,tmp=c.host();pool=tmp/'ctfe22-root-sdks';o=w/'trait-results/intake/domain-native';o.mkdir()
 source=[pool/r for r in c.ROLES];e=runpy.run_path(str(D/'epoch.py'))['run'];e(*source,o/'epoch','actual',expected=[(c.PAIR['arms'][r]['source']['commit'],c.PAIR['arms'][r]['source']['epoch'])for r in c.ROLES])
 proof=m.read(o/'epoch/passed.json');c.guard(proof['signed_argv_refusal_both_directions']and proof['same_sdk_self_loaded_before_and_after']and proof['no_header_edit']and proof['no_compiler_version_override']and proof['reader_compilations']==10,'cross-epoch refusal')
 from origin.compatibility import metadata, common_sysroot
 from origin.enrollment import SOURCES,FORMATS
 EPOCHS={rev:epochs for rev,epochs in zip(SOURCES,zip(FORMATS['incremental'],FORMATS['metadata']),strict=True)}
 real={commit:sdk for commit,sdk in zip(EPOCHS,source,strict=True)}
 common=o/'common-version-incremental.json'
 subprocess.run([sys.executable,'-ISB',S/'origin/epoch-native.py',o,common,source[0]/'bin/rustc','43319','43323',source[1]/'bin/rustc'],check=True)
 forced=m.read(common);c.guard(set(forced)=={'same-sdk-change-header','parent-to-candidate','candidate-to-parent'} and all(v['other_epoch_rejected']['diagnostics'] for v in forced.values()),'same-version incremental mismatch was not observed in both compiler directions')
 md=metadata(real,o/'metadata',expected=EPOCHS);c.guard(md['two_immutable_originals'] and not md['file_edits'] and not md['compiler_version_overrides'] and len(md['actual_compatible_pairs'])+len(md['actual_version_rejections'])==4 and len([v for v in md['real_compilations'].values() if v['codes']==['E0308']])==len(md['actual_compatible_pairs']),'wrong natural cross-SDK rmeta result')
 common_sysroot(real,o/'shared-sysroot')
 f=runpy.run_path(str(D/'fixture/oracle.py'))['main'];outputs={}
 for role,root in zip(c.ROLES,source,strict=True):
  f(root,D/'fixture',o/role,'candidate',inherited_source=c.PAIR['arms'][role]['source']['commit']);res=m.read(o/role/'qualified.json')
  c.guard(res['role']=='candidate' and res['actual_empty_edit_typeck']==dict.fromkeys(('read_adt','read_reference','read_str'),0)and res['registered_foreign_transitions']==11,'either compiler lost the existing native domain treatment')
  outputs[role]={'oracle':m.filesha(o/role/'qualified.json'),'actual_empty_edit_typeck':res['actual_empty_edit_typeck']}
 m.save(o/'accepted.json',{'roles':outputs,'epochs':m.filesha(o/'epoch/passed.json'),'rmeta_epochs':m.filesha(o/'metadata/passed.json'),'modes':10,
                          'separate_controlled_common_version':m.filesha(common),'true_sysroots':m.filesha(o/'shared-sysroot/passed.json'),'canonical_inputs':m.filesha(S/'pair.json')})
def boot():
 w,tmp=c.host();p=w/'trait-results';ready=m.read(p/'calibration.json')['ready'];now=Path('/proc/sys/kernel/random/boot_id').read_text().strip();ids={f['boot']for f in c.PAIR['prior_boots'].values()}
 c.guard(now==ready['boot']and len(ids)==len(c.PAIR['prior_boots'])and now not in ids,'previously enrolled host or changed boot')
 m.save(p/'fresh-boot.json',{'boot':now,'excluded':sorted(ids),'calibration':m.filesha(p/'calibration.json'),'thread_calibration':m.filesha(p/'per-rustc-calibration/calibration.json'),'blocking_clock':m.filesha(p/'blocking-clock/passed.json'),'coordinator':os.environ['GITHUB_SHA'],'run':os.environ['GITHUB_RUN_ID'],'attempt':os.environ['GITHUB_RUN_ATTEMPT'],'plan':m.filesha(S/'study.json')})
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
    from origin.policy import assess
    return assess(metrics)

def post_clock(out,ready):
 import wall_clock
 probe=c.host()[1]/'validated-wall-probe'
 pre=m.read(out/'blocking-clock/passed.json')
 wall_clock.calibrate(out/'blocking-clock-post',probe)
 c.guard(pre['machine']==m.read(out/'blocking-clock-post/passed.json')['machine'],'changed timer host')
