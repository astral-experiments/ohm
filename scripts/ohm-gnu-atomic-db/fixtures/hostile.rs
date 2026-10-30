#![crate_type="rlib"]
#[cfg(global_shadow)]
core::arch::global_asm!(".macro dmb arg", ".incbin \"payload.bin\"", ".endm");
#[cfg(naked)]
#[unsafe(naked)]
pub unsafe extern "C" fn naked_case() { core::arch::naked_asm!("ret"); }

#[unsafe(no_mangle)]
pub extern "C" fn qa_anchor() {}

pub unsafe fn operation(mut x: usize) -> usize {
    #[cfg(ordinary)]
    core::arch::asm!("ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    #[cfg(macro_inside)]
    core::arch::asm!(".macro qa_inject", ".incbin \"payload.bin\"", ".endm", "qa_inject", "ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    #[cfg(global_shadow)]
    core::arch::asm!("ldar {v}, [{v}]", "dmb ish",v=inout(reg) x,options(nostack));
    #[cfg(same_line)]
    core::arch::asm!("ldar {v}, [{v}]; .incbin \"payload.bin\"",v=inout(reg) x,options(nostack));
    #[cfg(feature_tail)]
    core::arch::asm!(".arch_extension lse; .incbin \"payload.bin\"","ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    #[cfg(label_include)]
    core::arch::asm!("2: .include \"nested.s\"","ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    #[cfg(label_expression)]
    core::arch::asm!("b 4f+0","4:","ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    #[cfg(symbol)]
    core::arch::asm!("b {name}","ldar {v}, [{v}]",name=sym qa_anchor,v=inout(reg) x,options(nostack));
    #[cfg(relocation)]
    core::arch::asm!("add {v}, {v}, :lo12:qa_anchor","ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    #[cfg(const_label)]
    core::arch::asm!("b {label}f","4:","ldar {v}, [{v}]",label=const 4,v=inout(reg) x,options(nostack));
    #[cfg(explicit_width)]
    core::arch::asm!("ldar {v:x}, [{v:x}]",v=inout(reg) x,options(nostack));
    #[cfg(other_options)]
    core::arch::asm!("ldar {v}, [{v}]",v=inout(reg) x,options(readonly,nostack));
    #[cfg(naked)]
    core::arch::asm!("ldar {v}, [{v}]",v=inout(reg) x,options(nostack));
    x
}
