"""Run the unchanged GNU provider histories with a literal syscall as the only raw assembly."""
import os
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent/'ohm-aarch64-versioned')]
from bootstrap import CHILD
import safety
from native_kits import Selection,identity
from version_kit import rt
from study import sha
DRIVER='d38721a8dd46c97d253686d920563654b035f25b6f0687c80871fb0a92401084'
RUST='''
#[inline(never)] pub fn barrier(x: usize) -> usize {
    let pid: usize;
    unsafe { core::arch::asm!("svc 0", in("x8") 172usize, lateout("x0") pid, options(nostack, preserves_flags)); }
    assert!(pid > 0);
    x
}
'''
class Candidate(Selection):
    def __init__(self,inputs,role):
        assert role=='C'
        super().__init__(inputs,role)
        old=self.original_driver
        record=rt.load(rt.LOG/'candidate.json')
        assert (record['source'],record['driver'][0])==(CHILD,DRIVER)
        source=rt.ROOT/'candidate-sdk'/record['driver_path']
        assert sha(source)==DRIVER and self.driver.relative_to(rt.SDK).as_posix()==record['driver_path'] and old['sha256']!=DRIVER
        staged=self.driver.with_suffix('.verified-syscall')
        os.link(source,staged);staged.replace(self.driver)
        self.original_driver=identity(self.driver)
        assert self.original_driver['sha256']==DRIVER
        self.sdk_checked={'original':self.sdk_checked,'source':CHILD,'driver_from':old,'driver_to':self.original_driver,'other_members_identical':118}
def main():
    mode=sys.argv[1]; assert mode in ('signed','classic','aware','migrate-signed','migrate-classic')
    safety.Selection=Candidate
    safety.GNU=RUST
    safety.CHILD=CHILD
    inputs=Path(os.environ['CENSUS_PARENT']).parent/'inputs'
    safety.main(mode,inputs)
    report=rt.load(rt.LOG/'versioned-native-terminal.json')
    assert report['compiler']==CHILD and report['mode']==mode
    print(mode,sum(len(v['rows']) for v in report['rosters'].values()),'absolute native outcomes',flush=True)
if __name__=='__main__':main()
