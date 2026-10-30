#![crate_type = "rlib"]

#[cfg(global)]
core::arch::global_asm!(".macro qa_unseen", ".incbin \"payload.bin\"", ".endm");

pub unsafe fn barrier(mut x: usize, mut v: core::arch::aarch64::int32x4_t) -> usize {
    #[cfg(not(vector_only))]
    core::arch::asm!("/*{0}*/", inout(reg) x);
    #[cfg(not(general_only))]
    core::arch::asm!("/*{:v}*/", inout(vreg) v);
    #[cfg(scalar_modifier)]
    core::arch::asm!("/*{0:x}*/", inout(reg) x);
    #[cfg(vector_modifier)]
    core::arch::asm!("/*{:q}*/", inout(vreg) v);
    #[cfg(spaced)]
    core::arch::asm!("/* {0} */", inout(reg) x);
    #[cfg(input_only)]
    core::arch::asm!("/*{0}*/", in(reg) x);
    #[cfg(instruction)]
    core::arch::asm!("nop");
    #[cfg(file)]
    core::arch::asm!("/*{:v}*/", ".incbin \"payload.bin\"", inout(vreg) v);
    #[cfg(escape)]
    core::arch::asm!("/*{0}*/ .incbin \"payload.bin\" /*trailer*/", inout(reg) x);
    #[cfg(raw)]
    core::arch::asm!("/*x0*/", options(raw));
    core::hint::black_box(v);
    x
}
