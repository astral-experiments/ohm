"""Reject coverage, denominator, process, and shard mistakes without running a native compiler."""
import copy,json
from pathlib import Path
import runpy
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import reopen
assert len(reopen.schedule)==12
rows=[]
for n,order in sorted(reopen.schedule.items()):
    row={'block':n,'order':order,'git':'a','source':reopen.source,'drivers':reopen.drivers,'boot':n,'raw_archive':n,
         'ordered_objects_sha256':{},'same_source_complete_reader':{},
         'whole_guest_Ir_by_process':{k:{c:{'cargo':v,'rustc':v*2} for c in ('first-real-edit','immediate-repeat','settled')}
                                     for k,v in {'A':23,'N':21,'M':10}.items()}}
    rows.append(row)
r=reopen.analyze(rows)
assert r['all_six_in_all_blocks_above_two'] and r['six_endpoint_family_coverage_lower_bound']==0.9619140625
assert r['full_ruff_guest_instruction_ratios']['N/M:first-real-edit']['one_sided_sign_against_two']==1/4096
rows[0]['whole_guest_Ir_by_process']['N']['first-real-edit']={'cargo':60}
assert not reopen.analyze(rows)['all_six_in_all_blocks_above_two']
rows[0]['order']=rows[1]['order']
try: reopen.analyze(rows)
except AssertionError: pass
else: raise AssertionError('accepted an altered block order')
print('schedule, totals, simultaneous intervals, a 2x tie and corrupted order passed')
