import os,shutil,subprocess as sp,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));from common import *
need(os.environ['GITHUB_RUN_ATTEMPT']=='1'and os.environ['GITHUB_SHA']==os.environ['REVIEWED_HEAD']and os.environ['GITHUB_REF_NAME']=='charlie/qa-ruff-clap-config-help-20261103','unregistered receiver')
ROOT.mkdir();PUB.mkdir();DIAG.mkdir();SDKBASE.mkdir();guard()
for p in ('fetch.py','extract.py'):shutil.copyfile(HERE/p,SDKBASE/p)
need(git('rev-parse','HEAD')==NEW and git('rev-parse','HEAD^')==OLD and git('diff','--name-only',OLD,NEW).splitlines()==['crates/ruff/src/args.rs','docs/configuration.md'],'Ruff history')
for p in ('fetch.py','extract.py'):sp.run([sys.executable,'-IB',SDKBASE/p],check=True)
for name in ('intake.json','compiler.json'):shutil.copyfile(SDKBASE/name,PUB/name)
need(json.loads((HERE/'intake.json').read_bytes())==json.loads((SDKBASE/'intake.json').read_bytes()),'different full distribution')
actual=json.loads((SDKBASE/'compiler.json').read_bytes());expected=json.loads((HERE/'compiler.json').read_bytes())
need(actual['members']==expected['members'] and actual['wild']==expected['wild'] and actual['tar_sha256']==expected['tar_sha256'],'different physical SDK')
for exe in ('whole_count','exec_count','thread_meter'):
    sp.run(['cc','-O2','-pthread','-Wall','-Wextra','-Werror',HERE/(exe+'.c'),'-o',ROOT/exe],check=True)
put(PUB/'registration.json',{'source':[OLD,NEW],'source_files':SRCS,'lock':LOCK,'command':CMD,
    'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'preexisting_work':False,'SDK':hf(HERE/'compiler.json'),
    'scope':'One unscored Linux stock release-candidate baseline. Actual old/new help, independent clean, invalid and repaired inputs. Maintained CPU/storage controls. Separate actual per-exec attribution and instruction profile when output gates admit.'})
