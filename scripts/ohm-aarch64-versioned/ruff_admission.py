"""Acquire the true historical Ruff native outcomes before running any statistical sample."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from ruff_subjects import DEFAULT_SOURCE,DEFAULT_DRIVERS,REG,enroll,marker_rules,rt
from study import save,sha,load
sys.path.insert(0,str(HERE.parent/'ohm-aarch64-fallback'))
import ruff_native as original

def main(ancestor,inputs):
    enroll(original.HOLD)
    original.HIN['PRODUCT']=REG['cargo_elf']
    original.main(ancestor,inputs,inputs/'versioned/cargo')
    report=load(rt.LOG/'ruff-native-eligibility.json')
    assert report['sources']==DEFAULT_SOURCE and report['drivers']==DEFAULT_DRIVERS and report['cargo']==REG['cargo_elf']
    actual={}
    for role in 'ANM':
        base=rt.LOG/('ruff-native-'+role)
        actual[role]={phase:marker_rules(base,role,phase) for phase in ('old-empty','edit','unchanged-1','unchanged-2','empty-edited')}
    save(rt.LOG/'exact-marker-roles.json',{'native':sha(rt.LOG/'ruff-native-eligibility.json'),'roles':actual,'source_alias_M':DEFAULT_SOURCE['M'],'new_cargo':REG['cargo_elf']})
if __name__=='__main__':main(*map(Path,sys.argv[1:]))
