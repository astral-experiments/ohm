#[inline(never)]
pub fn payload() -> u32 {
    let value: u32;
    unsafe {
        core::arch::asm!(
            "jmp 3f",
            "2:",
            concat!(".incbin \"", env!("CARGO_MANIFEST_DIR"), "/payload.bin\""),
            "3:",
            "movzx {value:e}, byte ptr [rip + 2b]",
            value = out(reg) value,
            options(nostack, preserves_flags),
        );
    }
    value
}
