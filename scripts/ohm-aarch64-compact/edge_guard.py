"""Separate explicit native declarations from parked, unwatched input-only changes."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import kit
sys.path.insert(0,str(HERE.parent/"ohm-aarch64-registers"))
import edges
from study import load,need,save,sha
rt=kit.rt
BARRIER='''#[inline(always)] pub fn barrier(value:usize)->usize {
    unsafe {core::arch::asm!("/* {value} */",value=in(reg) value,options(nomem,nostack));} value
}
'''
def main():
    archive,key=sys.argv[1:]; archive=Path(archive);need(sha(archive)==key,"wrong SDK")
    kit.bind()
    edges.BARRIER=BARRIER
    original=edges.BUILD
    complete={}
    for role in 'PC':
        rt.SDK.parent.mkdir(parents=True,exist_ok=True);kit.capsule.verify(archive,role,rt.SDK)
        for control in ('files','directories','undeclared'):
            choose={'files':'println!("cargo:rerun-if-changed={n}/libqa_owned_external.a");',
                    'directories':'println!("cargo:rerun-if-changed={n}");','undeclared':''}[control]
            edges.BUILD=original.replace('for n in ["early","late"]{','for n in ["early","late"]{'+choose)
            for placement in ('direct','library'):
                for kind in ('change','missing'):
                    lab='-'.join((role,control,placement,kind));base=rt.LOG/lab;base.mkdir()
                    edges.run(base,role,placement,True,native_only=(kind=='missing'))
                    trace=load(base/'completed.json')
                    rows={r['name']:r for r in trace['cases']};observed={}
                    pairs=({'higher-no-Rust-edit':'empty-higher','higher-real-Rust-edit':'empty-edited-higher',
                      'malformed-real-Rust-edit':'empty-malformed','missing-real-Rust-edit':'empty-missing',
                      'restored-real-Rust-edit':'empty-restored','restored-unchanged':'empty-restored'} if kind=='change' else
                      {'malformed-no-Rust-edit':'empty-malformed','repaired-no-Rust-edit':'empty-repaired',
                       'missing-no-Rust-edit':'empty-missing','restored-real-Rust-edit':'empty-restored-edited'})
                    verdict=lambda r: (r['exit'],r['answer'],r['elf'])
                    for stage,empty in pairs.items():
                        r,ref=rows[stage],rows[empty];same=verdict(r)==verdict(ref)
                        observed[stage]={'same_complete_clean':same,'actual':[r['exit'],r['answer']],'clean':[ref['exit'],ref['answer']]}
                        if control != 'undeclared' or 'no-Rust-edit' not in stage:
                            need(same,lab+'/'+stage+' differs from independent empty')
                    need(rows['empty-malformed']['exit']==rows['empty-missing']['exit']==101 and rows['cold-lower']['answer']=='17 7',
                         'wrong genuine provider expectations')
                    complete[lab]={'case_receipt':sha(base/'completed.json'),'observed':observed}
        rt.SDK.rename(rt.ROOT/('completed-runtime-'+role))
    save(rt.LOG/'terminal.json',{'scenarios':complete,'source':[kit.BEFORE,kit.AFTER],'source_shape':BARRIER})
if __name__=='__main__':main()
