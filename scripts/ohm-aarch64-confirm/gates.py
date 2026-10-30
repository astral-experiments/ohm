from pathlib import Path
import json,os,subprocess
repo='astral-experiments/ohm'
gates={
 41064199666:('7e371b32dfaeeb507d10133ce422bc4324c6be08',{'gnu-compact-input-native':'14f0846d03777780d4b09c57998f91345601d77bd3ae3f248c6872202ec1761a','gnu-compact-input-compiler-pair':'d12061de9f2b05adf06d3415690748bd5553857a6230034cb57564dd38c1644c'}),
 41064927474:('8ad9758f15746600982183222d339779dbac4715',{'gnu-compact-input-ruff-complete':'0669587e7bab0594e7e039bf0f21793b524acdc5664096a5777b5bf90f6ab3b2','gnu-compact-input-provider-controls':'6543876ffde16627de47ead92f945c17409c71151efac041ce03c072bed5fdf3'}),
 41065481694:('fb9c70f49ad96e8c844cf61581cc0b5ee37da670',{'gnu-compact-input-stock-provider':'1e0e2ef6bc4b663cf7db8bb53a683c2ecf72063bac4c790ebc6c3138ef570446'})}
def query(path):
 return json.loads(subprocess.check_output(['gh','api','repos/'+repo+'/'+path]))
def main():
 result={}
 for n,(head,required) in gates.items():
  r=query('actions/runs/'+str(n))
  assert (r['head_sha'],r['status'],r['conclusion'])==(head,'completed','success')
  actual={a['name']:a for a in query('actions/runs/'+str(n)+'/artifacts')['artifacts']}
  for name,h in required.items():
   assert actual[name]['digest']=='sha256:'+h and not actual[name]['expired'] and actual[name]['workflow_run']['head_sha']==head
  result[n]=required
 out=Path(os.environ['QA_ROOT'])/'receipts'/'prior-closed-gates.json'
 out.open('x').write(json.dumps(result,indent=2,sort_keys=True)+'\n')
if __name__=='__main__':main()
