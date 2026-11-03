"""Run one frozen counterbalanced copy of the source pilot without altering its code or Cargo argv."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

here=Path(__file__).resolve().parent
plan_file=here/'confirmation-plan.json'
plan=json.loads(plan_file.read_bytes())
root=Path(os.environ['GITHUB_WORKSPACE']).resolve(strict=True)
frozen=root/'original-receiver'
head=subprocess.check_output(['git','-C',frozen,'rev-parse','HEAD'],text=True).strip()
assert head==plan['primary_receiver_commit']=='2672756eb5b9d4e890b678d439dc6c40a29a4008'
assert hashlib.sha256((frozen/'scripts/ruff-derived-impl-cgus/paired.py').read_bytes()).hexdigest()==plan['canonical_receiver_sha256']
assert os.environ['RUFF_CASE']=='28392' and os.environ['GITHUB_RUN_ATTEMPT']=='1'
slot=int(os.environ['BOOT_SLOT']);assert 0<=slot<6 and str(slot)==os.environ['BOOT_SLOT']
sys.path.insert(0,str(frozen/'scripts/ruff-derived-impl-cgus'))
import paired
paired.ORDER=plan['orders'][slot]
try:
    paired.main()
finally:
    if paired.OUTPUT.is_dir():
        paired.b.put(paired.OUTPUT/'confirmation.json',{'slot':slot,'order':paired.ORDER,'plan_sha256':hashlib.sha256(plan_file.read_bytes()).hexdigest(),'runner_head':head,'recorded_receipt':os.environ['REVIEWED_HEAD'],'real_driver_sources':plan['compilers']})
