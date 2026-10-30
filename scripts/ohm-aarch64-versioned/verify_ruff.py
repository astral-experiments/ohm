"""Reopen all observed native processes, cold references, outputs and the exact marker-specific rules."""
from hashlib import sha256
from pathlib import Path
import json,sys,zipfile
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from ruff_subjects import DEFAULT_SOURCE,DEFAULT_DRIVERS,REG
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
import verify_ruff_native
H=lambda b:sha256(b).hexdigest()
def verify(p):
    r=verify_ruff_native.verify(p,DEFAULT_SOURCE,DEFAULT_DRIVERS,REG['cargo_elf'])
    if hasattr(p,'seek'):p.seek(0)
    with zipfile.ZipFile(p) as z:
        blob=z.read('exact-marker-roles.json');extra=json.loads(blob)
        assert extra['native']==H(z.read('ruff-native-eligibility.json'))==r['terminal']
        assert extra['new_cargo']==r['cargo'] and extra['source_alias_M']==DEFAULT_SOURCE['M']
        for role in 'ANM':
            for phase in ('old-empty','edit','unchanged-1','unchanged-2','empty-edited'):
                for name,row in extra['roles'][role][phase].items():
                    raw=z.read('ruff-native-'+role+'/'+phase+'/'+name+'.d')
                    assert H(raw)==row['actual_depfile_sha256']
                    err=name in {'A':{'zmij','compact_str','ruff_python_ast'},'N':{'compact_str','ruff_python_ast'},'M':set()}[role]
                    want='hard' if err else ('versioned' if role=='M' else 'legacy')
                    token={'hard':'ohm-untracked-relink-inputs','versioned':'ohm-recheck-dependent-links-v2','legacy':'ohm-recheck-dependent-links'}[want]
                    assert row['gate']==want and (b'/dev/null/'+token.encode()+b':') in raw.splitlines()
        report=json.loads(z.read('ruff-native-eligibility.json'))
        args=report['raw_normalized_argv']
        r.update(actual_argc=len(args),normalized_argv_sha256=H(json.dumps(args,sort_keys=True,separators=(',',':')).encode()),
                 full_marker_readback=H(blob),versioned_compiler=DEFAULT_SOURCE['M'])
    return r
if __name__=='__main__':
    p,out=map(Path,sys.argv[1:]);result=verify(p)
    data=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode();out.open('xb').write(data);print(H(data))
