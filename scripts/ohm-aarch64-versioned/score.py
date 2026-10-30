"""Run the existing calibrated whole-Cargo collector with the versioned compiler and aware Cargo."""
import hashlib
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from ruff_subjects import REG,DEFAULT_SOURCE,DEFAULT_DRIVERS,enroll,marker_rules,rt
from kernel_env import install,verify as verify_kernel
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
import fixed_study
import score_readback as original
from study import load,save,sha

ART='gnu-versioned-'
JOB='Versioned Cargo '
PHASES=('old-empty','edit','unchanged-1','unchanged-2','empty-edited')
def configure():
    fixed_study.HERE=HERE
    original.HERE=HERE
    enroll(fixed_study.HOLD)
    registered=load(HERE/'admissible-native.json')
    assert registered['cargo_elf']==REG['cargo_elf']
    assert registered['sources']==DEFAULT_SOURCE and registered['drivers']==DEFAULT_DRIVERS
    for name in ('reopen','analyze'):
        original.reader[name].__globals__.update(source=DEFAULT_SOURCE,drivers=DEFAULT_DRIVERS)
    return registered
def live(number,stage,ancestor,inputs):
    install()
    registered=configure()
    fixed_study.main(number,stage,ancestor,inputs,inputs/'versioned'/'cargo',registered['cargo_elf'])
    receipt={}
    for role in 'ANM':
        folder=rt.LOG/('block-'+number+'-'+role)
        receipt[role]={phase:marker_rules(folder,role,phase) for phase in PHASES}
    save(rt.LOG/'versioned-slot-status.json',{'native_slots':receipt,'terminal':sha(rt.LOG/'terminal.json'),
                                            'rust':DEFAULT_SOURCE,'cargo':REG['source']['cargo']['source']})
def block_reader(base):
    def read(path,stage,num,git,raw_sha,order_file):
        import zipfile
        with zipfile.ZipFile(path) as z:
            receipt=json.loads(z.read('versioned-slot-status.json'))
            assert receipt['terminal']==hashlib.sha256(z.read('terminal.json')).hexdigest()
            assert receipt['rust']==DEFAULT_SOURCE and receipt['cargo']==REG['source']['cargo']['source']
            assert set(receipt['native_slots'])==set('ANM')
            for role,phases in receipt['native_slots'].items():
                verify_kernel(z,f'block-{num}-{role}/edit')
                assert set(phases)==set(PHASES)
                for phase,markers in phases.items():
                    assert set(markers)=={'compact_str','ruff_python_ast','zmij'}
                    for crate,row in markers.items():
                        b=z.read(f'block-{num}-{role}/{phase}/{crate}.d')
                        want='hard' if crate in original.reader['hard'][role] else 'versioned' if role=='M' else 'legacy'
                        spell={'hard':'ohm-untracked-relink-inputs','versioned':'ohm-recheck-dependent-links-v2','legacy':'ohm-recheck-dependent-links'}
                        assert row['gate']==want and hashlib.sha256(b).hexdigest()==row['actual_depfile_sha256']
                        assert [k for k,v in spell.items() if ('/dev/null/'+v+':').encode() in b.splitlines()]==[want]
        result=base(path,stage,num,git,raw_sha,order_file);result['versioned_markers']=receipt['native_slots']
        return result
    return read
def reader(stage):
    configure();original.block=block_reader(original.block);original.remote(stage,ART,JOB)
if __name__=='__main__':
    if sys.argv[1]=='reopen':reader(sys.argv[2])
    else:live(sys.argv[1],sys.argv[2],*map(Path,sys.argv[3:]))
