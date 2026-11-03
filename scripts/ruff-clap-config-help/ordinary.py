import json,shutil,subprocess as sp,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent));from common import *
whole=ROOT/'whole_count'
def run(tag,state):
    guard();td=PUB/tag;command(td,[whole,td/'hardware.json',shutil.which('cargo',path=env()['PATH']),*CMD])
    hw=json.loads((td/'hardware.json').read_bytes());need(hw['status']==0 and hw['instructions']>0 and hw['enabled']==hw['running']>0,(tag,'whole counter'))
    out=observe_products(td,state)
    put(td/'products.json',out)
    return out
select(OLD);prepare();ref=run('old',OLD)
if MODE=='build':shutil.copyfile(TARGET/'debug/ruff',ROOT/'retained-old');(ROOT/'retained-old').chmod(0o755)
old_warm=run('old-unchanged',OLD);need(old_warm==ref,'old unchanged differed')
select(NEW)
if MODE=='build':
    stale=PUB/'old-exe-on-new-source';stale.mkdir()
    need(verdict(ROOT/'retained-old',stale,OLD)==ref['verdict'],'saved older native program changed under edited source')
edit=run('edit',NEW);warm=run('edited-unchanged',NEW)
if MODE=='build':
    need(ref['elf']!=edit['elf'] and ref['verdict']['show_example']==edit['verdict']['show_example'],'required genuine help change')
    for label in ('help','check-help','format-help'):
        norm=lambda b:b' '.join(b.split())
        before=(PUB/'old'/(label+'.stdout')).read_bytes();after=(PUB/'edit'/(label+'.stdout')).read_bytes()
        need(norm(before).replace(b'lint.line-length = 100',b'line-length = 100')==norm(after),('unexpected other user-visible help',label))
need(edit==warm,'edited unchanged differed')
base=SRC.read_bytes()
try:
    SRC.write_bytes(base+b'\nconst _: u8 = "ohm_cli_invalid";\n')
    for label in ('invalid','invalid-unchanged'):
        p=PUB/label;command(p,CMD,101);raw=(p/'stderr').read_bytes()
        need(b'error[E0308]'in raw and b'ohm_cli_invalid'in raw,(label,'incorrect stale diagnostic',raw[-300:]))
finally:SRC.write_bytes(base)
repair=run('repair',NEW);need(repair==edit,'repaired output differed')
# The independently cold compiler gets no target, shared graph, proc macro, or Cargo-home registry product.
for p in (TARGET,BUILD,HOME):
    if p.exists():
        need(p.is_dir()and not p.is_symlink(),'unexpected output root')
        p.rename(ROOT/('original-'+p.name))
prepare();clean=run('independent-clean-new',NEW)
same=clean==edit
if MODE=='build':need(clean['verdict']==edit['verdict'],'independently empty runtime verdict changed')
put(PUB/'admission.json',{'strict_product_match':same,'same_check_or_runtime_verdict':True,'clean':clean,'edit':edit,
                          'old':ref,'command':CMD,'source':[OLD,NEW]})
# Restoring the ordinary history allows the separately observed re-edit to use its real earlier donors.
for p in (TARGET,BUILD,HOME):
    if p.exists():p.rename(ROOT/('clean-'+p.name))
    parked=ROOT/('original-'+p.name)
    if parked.exists():parked.rename(p)
need(not git('status','--porcelain'),'dirty working source')
