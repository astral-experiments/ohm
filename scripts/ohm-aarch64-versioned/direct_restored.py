"""Run precisely the previously unexecuted marker cases, using two freshly opened matched toolchains."""
import runpy
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from native_kits import Selection
from version_kit import rt
from study import save,sha
def main():
    for role in 'PC':
        s=Selection(rt.ROOT/'inputs',role)
        checks=runpy.run_path(str(HERE/'direct.py'))
        checks['main'](role)
        close=rt.ROOT/('direct-complete-'+role);close.mkdir()
        rt.SDK.rename(close/'sdk');s.parking.rename(close/'cargo-parking')
    save(rt.LOG/'direct-terminal.json',{k:sha(rt.LOG/('direct-version-'+k)/'complete.json') for k in 'PC'})
if __name__=='__main__':main()
