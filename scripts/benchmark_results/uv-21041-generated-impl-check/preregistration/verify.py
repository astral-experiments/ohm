"""Recompute the enrolled group and whole-compiler costs from original Callgrind and counter files."""
from pathlib import Path
from collections import Counter
import hashlib, json, lzma, re
h=Path(__file__).resolve().parent
def j(p):return json.loads(p.read_bytes())
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
reg=j(h/'owner-enrollment.json')['roles'];roster=Counter((k,r['local_index']) for k,vs in reg.items()for r in vs)
chosen={(k,r['local_index'])for k,vs in reg.items()for r in vs if r['enrolled']}
summary=j(h/'two-bank.json')['banks'];assert len(roster)==134 and len(chosen)==97
assert digest(h/'protocol.json')=='b2801bb8a8f30b4facd5cc4c1a7b0b9142a7841906f17fd241629504a9273ab2'
assert digest(h/'cross-mode-gate.json')=='9ee6c73cb2c8b5a440026b0c4b7b4da6b8db51713b29cc751c31ce6df45d6cf8'
for i in [1,2]:
 p=h/f'history-{i}';a=j(p/'accepted.json');q=j(p/'request.json');raw=lzma.open(p/'callgrind.xz','rb').read()
 assert hashlib.sha256(raw).hexdigest()==a['aggregate_cost'] and digest(p/'cost.json')==a['subintervals']
 assert digest(p/'request.json')==a['request']==summary[i-1]['original_request'] and digest(p/'kernel.json')==a['kernel']
 assert digest(h/'counter.py')==q['counter_program'] and digest(h/'capture.py')==q['inner'] and digest(h/'replay.py')==q['runner']
 assert digest(h/'owner-enrollment.json')==q['enrollment']and a['ordinary_graph']==q['expected_graph']
 ar=q['argv'];assert j(p/'kernel.json')['full_argv'][-len(ar):]==ar and j(p/'admitted-elf.json')['opcodes']==q['opcodes']
 cost=j(p/'cost.json');assert cost['fault']==[]and cost['exit']==0;rows=cost['rows']
 assert Counter((r['symbol'],r['index'])for r in rows)==roster
 hit=[r for r in rows if(r['symbol'],r['index'])in chosen];ints=sorted((sum(r['start'].values()),sum(r['end'].values()))for r in hit)
 assert all(x<y for x,y in ints)and all(b<=c for (_,b),(c,_)in zip(ints,ints[1:]))
 summed=sum(y-x for x,y in ints);scopes={k:sum(r['delta_all_threads']for r in hit if r['symbol']==k)for k in reg}
 full,=map(int,re.findall(rb'^summary: (\d+)$',raw,re.M));assert full==int(re.search(rb'^totals: (\d+)$',raw,re.M)[1])
 assert summed==sum(scopes.values())==a['enrolled_union_Ir']==summary[i-1]['enrolled_97']and full==a['whole_guest_Ir']==summary[i-1]['whole']
 print(i,full,scopes,summed,100*summed/full)
mode=j(h/'cross-mode-original.json');gate=j(h/'cross-mode-gate.json')
assert gate['original_two_mode_output']==digest(h/'cross-mode-original.json')and gate['prior_protocol']==digest(h/'protocol.json')
for source,method,eh1,eh2,impl,fn in gate['rows_A_or_B_method_ExpnHash_incremental_ordinary_impl_method']:
 a,b=[mode[source][key]['observed'][method]for key in ['incremental','ordinary']]
 assert (a['expansion'],b['expansion'])==(eh1,eh2)and eh1!=eh2 and a['impl']==b['impl']==impl and a['method']==b['method']==fn
