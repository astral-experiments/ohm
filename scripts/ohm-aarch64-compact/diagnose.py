"""Observe the precise frontend lowering of the retained failing native classifier."""
from pathlib import Path
import gzip
import shutil
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import kit
from study import MISSING, RECHECK, need, save, sha
rt=kit.rt
def main():
    native=rt.ROOT/'inputs/native'
    kit.bind()
    rt.SDK.parent.mkdir(parents=True,exist_ok=True)
    meta=kit.capsule.verify(rt.ROOT/'inputs/sdk.tar.zst','C',rt.SDK)
    driver,=[p for p in (rt.SDK/'lib').glob('librustc_driver*.so')]
    need(sha(driver)=='538e99410d068e9d59c259e16740fa9719f17a0eba216977424ea2e6b1aaee67','wrong failed driver')
    env=rt.environment(); results={}
    op='core::arch::asm!("/* {value} */", value = in(reg) x, options(nomem, nostack));'
    samples={
        'checked':((HERE/'gnu_aarch64.rs').read_text(),['--cfg','compact_input']),
        'source-unit':('#[inline(always)] pub unsafe fn barrier(x:usize){'+op+'}',[]),
        'source-return':('#[inline(always)] pub unsafe fn barrier(x:usize)->usize{'+op+'x}',[]),
        'source-pointer':('#[inline(always)] pub unsafe fn barrier(x:*const u8){'+op+'}',[]),
        'source-use':('pub unsafe fn barrier(x:usize)->usize{'+op+'core::hint::black_box(x)}',[]),
        'const':('pub unsafe fn barrier(){let x=7usize;'+op+'}',[]),
        'input-without-space':('pub unsafe fn barrier(x:usize){'+op.replace('/* {value} */','/*{value}*/')+'}',[]),
    }
    for tag,(source,cfg) in samples.items():
        root=rt.ROOT/'lower'/tag; root.mkdir(parents=True)
        dest=rt.LOG/tag; dest.mkdir(); f=root/'barrier.rs';f.write_text(source);shutil.copyfile(f,dest/f.name)
        cmd=['rustc','+ohm',f.name,'--crate-type=rlib','--target',rt.TARGET,'-Zohm-check-relink-inputs',*cfg]
        p=rt.record([*cmd,'--emit=link,dep-info=-'],dest/'native',root,env)
        q=rt.record([*cmd,'--emit=link,dep-info=-,mir,llvm-ir','-Zprint-mono-items=yes'],dest/'with-lowering',root,env)
        raw=(root/'barrier.mir').read_bytes(); lines=[l.decode().strip() for l in raw.splitlines() if b'asm!(' in l]
        ir=(root/'barrier.ll').read_bytes(); ins=[l.decode().strip() for l in ir.splitlines() if b' asm ' in l]
        for suf,data in [('mir',raw),('ll',ir)]: (dest/(suf+'.gz')).write_bytes(gzip.compress(data,mtime=0))
        rt.record([*cmd,'-Zunpretty=hir-tree'],dest/'hir',root,env)
        rt.record([*cmd,'-Zunpretty=thir-tree'],dest/'thir',root,env)
        before=[MISSING in p.stdout,RECHECK in p.stdout];after=[MISSING in q.stdout,RECHECK in q.stdout]
        need(before==after and any(before) and len(lines)>0 and ins,'instrumentation changed marker')
        results[tag]={'markers':before,'mir':lines,'llvm':ins,'actual_rlib':sha(root/'libbarrier.rlib')}
    need(results['checked']['markers']==[True,False],'original regression not reproduced')
    need(gzip.decompress((native/'direct-extended/compact_input/stdout.gz').read_bytes()).count(b'ohm-untracked-relink-inputs')==2,'wrong prior')
    save(rt.LOG/'complete.json',{'driver':sha(driver),'observed':results,'sdk':meta})
if __name__=='__main__': main()
