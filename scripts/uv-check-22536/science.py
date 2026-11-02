"""Run every science phase on the same first eight distinct physical CPUs."""
from pathlib import Path
import os,subprocess,sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from basis import Env,kernel,read,writez
from session import W,calibrate,main
from managed_sdk import Managed
import opening,fixed_products,producer_map,producer_evidence
from compatibility import qualify as bounds
def checked_opening(e):
    # Preserve the local frozen admission. On the physical worker, check all
    # 42 Cargo-owned files on both roles before opening any timed visit.
    targets={}
    def collect(env,folder,policy):
        warm=folder.name in ('warm-B','warm-C','warm-D')
        before=fixed_products.ordinary_stats(env.target) if warm else None
        rec=producer_evidence.cold(env,folder) if folder.name=='cold-A' else kernel(env,folder,policy)
        if folder.name=='cold-A':
            targets[folder.parent]=fixed_products.paths(rec['workspace_rmeta_from_argv'])
            # The next unchanged ordinary check must stay at zero after this
            # genuine two-directory round trip; the original target stays put.
            old=env.active;other='R'if old=='F'else'F'
            for role in (other,old):
                env.choose(role)
                assert subprocess.check_output([env.bin,'--print','sysroot'],env=env.env,text=True).strip()==str(env.sdk)

        if warm:
            expected=targets[folder.parent]
            fixed_products.changed(before,fixed_products.ordinary_stats(env.target),expected)
            writez(folder/'fixed-products.json.gz',fixed_products.recorded(env.target,expected))
        return rec
    with patch.object(opening,'kernel',collect):gate=opening.qualify(e)
    base=e.results/'qualification';left=base/('signed-1'if gate['control']=='R'else'corrected');right=base/'treatment';mat=read(e.results/'actual-inputs.json')
    assert producer_map.verify_observed_pids(left,mat[gate['control']])==producer_map.verify_observed_pids(right,mat['F'])==497
    writez(base/'producer-bijection.json.gz',producer_map.compare(left,right))
    return gate
if __name__=='__main__':
    action,config=sys.argv[1:];e=Managed(read(config));cores=W['physical_cores']()
    assert len(cores)==8;os.sched_setaffinity(0,cores)
    try:
        if action=='calibrate':calibrate(e)
        elif action=='open':checked_opening(e)
        elif action=='epochs':bounds(e)
        elif action=='measure':main(e.inp,e)
        else:raise ValueError(action)
    finally:e.home()
