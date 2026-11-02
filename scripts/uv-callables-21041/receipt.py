import core as c
import json,hashlib
def read(p):return json.loads(p.read_bytes())
def unpack_candidate(module,archive,dest,role):
 import inspect
 original=inspect.getsource(module.unpack)
 line="extras={'allocator.log'} if role==ROLES[1] else set()"
 assert original.count(line)==1 and role==c.ROLES[1]
 qualified=original.replace(line,"extras={'allocator.log','coroutine-oracle.zip','coroutine-oracle.log','coroutine-oracle.json','callables-oracle.json','callables-oracle.log','callables-oracle.zip'}")
 scope=dict(module.__dict__);exec(compile(qualified,'enrolled coroutine SDK outer archive','exec'),scope);scope['unpack'](archive,dest,role)
def oracle(capsule):
 from zipfile import ZipFile
 from pathlib import PurePosixPath
 proof=read(capsule/'coroutine-oracle.json')
 assert proof['role']=='candidate' and proof['unrelated_typeck_provider_count']==0 and proof['genuine_signature_diagnostic']=='E0061'
 assert (capsule/'coroutine-oracle.log').read_bytes()==b'qualified candidate 0\n'
 with ZipFile(capsule/'coroutine-oracle.zip') as z:
  info=z.infolist();names=[i.filename for i in info]
  assert names==sorted(names) and len(names)==len(set(names))<160 and sum(i.file_size for i in info)<24<<20
  assert all(not PurePosixPath(n).is_absolute() and '..'not in PurePosixPath(n).parts and '\\'not in n for n in names)
  assert z.testzip()is None and json.loads(z.read('qualified.json'))==proof and hashlib.sha256(z.read('observed.json')).hexdigest()==proof['receipt_sha256']
  assert json.loads(z.read('observed.json'))['role']=='candidate' and any(n.endswith('.mm_profdata')for n in names)
 expected_callable_log=b"qualified candidate {'only_named': 0, 'only_ctor': 0, 'only_assoc': 0, 'only_closure': 0}\n"
 import recount
 actual=recount.actual(capsule/'callables-oracle.zip','candidate')
 public=(capsule/'callables-oracle.json').read_bytes()
 with ZipFile(capsule/'callables-oracle.zip') as z: inner=z.read('qualified.json')
 x=json.loads(inner)
 assert (json.dumps(x,sort_keys=True,indent=2)+'\n').encode()==inner and (json.dumps(x,sort_keys=True,indent=1)+'\n').encode()==public
 assert actual['source_qualified_sha256']==hashlib.sha256(inner).hexdigest() and actual['profiles']['toggle']['selected']==dict.fromkeys(recount.OWNERS,0)
 assert (capsule/'callables-oracle.log').read_bytes()==expected_callable_log
 return proof
