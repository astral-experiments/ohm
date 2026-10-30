"""Classify already sealed first-real-edit AST profiles using ELF mappings and actual call edges."""
from collections import Counter
from pathlib import Path
import gzip,hashlib,json,re,sys,zipfile
SYMBOL=b'rustc_codegen_llvm::base::compile_codegen_unit'
def H(b):return hashlib.sha256(b).hexdigest()
def size(z,base):
    subject=json.loads(z.read(base+'/verified.json'))['processes']['ruff_python_ast']
    pid=subject['pid']; profile=gzip.decompress(z.read(base+f'/profiles/cg.{pid}.gz'))
    assert H(profile)==subject['profile']
    obs={};names={};costs=Counter();calls=Counter();fn=ob=callee=None;outgoing=False
    for l in profile.splitlines():
        pair=re.match(rb'^(c?)(ob|fn)=\((\d+)\)(?: (.*))?$',l)
        if pair:
            indirect,kind,n,name=pair.groups();m=obs if kind==b'ob' else names
            if name is not None:assert m.setdefault(n,name)==name
            if not indirect and kind==b'ob':ob=n
            if not indirect and kind==b'fn':fn=n
            if indirect and kind==b'fn':callee=n
            continue
        if l.startswith(b'calls='):
            assert not outgoing and callee is not None
            calls[callee]+=int(l.removeprefix(b'calls=').split()[0]);outgoing=True
        elif re.match(rb'^[*+\-\d]', l):
            if not outgoing:
                assert ob is not None and fn is not None
                costs[ob]+=int(l.split()[-1])
            outgoing=False
    assert not outgoing and sum(costs.values())==subject['Ir']
    ordinary=[k for k,n in names.items() if n==SYMBOL]
    assert len(ordinary)<=1
    mod=[k for k,n in names.items() if n==SYMBOL+b'::module_codegen']
    assert len(mod)<=1
    return {'AST_Ir':subject['Ir'],'compile_codegen_unit_calls':sum(calls[k] for k in ordinary),'module_codegen_calls':sum(calls[k] for k in mod),
            'own_Ir_by_mapped_ELF':{Path(obs[k].decode()).name:v for k,v in costs.items()},'raw_profile':subject['profile']}
def main(run):
    d=Path(run)
    with zipfile.ZipFile(d/'gnu-compact-input-ruff-complete.zip') as z:
        data={name:size(z,name+'-edit-cycle/first-real-edit') for name in ('mirror1-P','mirror1-C','mirror2-C','mirror2-P')}
    body=(json.dumps({'counts':data,'raw_sha256':'0669587e7bab0594e7e039bf0f21793b524acdc5664096a5777b5bf90f6ab3b2','symbols':[SYMBOL.decode(),SYMBOL.decode()+'::module_codegen']},indent=2,sort_keys=True)+'\n').encode()
    (d/'first-edit-codegen-analysis.json').open('xb').write(body);print(H(body))
    for f,rec in data.items():
        print(f,rec['compile_codegen_unit_calls'],rec['module_codegen_calls'],{k:v for k,v in rec['own_Ir_by_mapped_ELF'].items() if 'LLVM' in k})
if __name__=='__main__':main(sys.argv[1])
