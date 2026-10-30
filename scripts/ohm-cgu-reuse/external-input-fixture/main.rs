mod opaque {
    #[inline(never)]
    pub fn native() -> u64 {
        let ptr: *const u8;
        unsafe {
            core::arch::asm!("lea {p}, [rip + 2f]", ".pushsection .rodata", "2:", ".incbin \"payload.bin\"", ".popsection", p = out(reg) ptr);
            *ptr as u64
        }
    }
}
mod pathopt {
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub fn choose_slot(i: u64) -> u64 {
        if i & 1 == 0 {
            scalar_a(i).rotate_left(13)
        } else {
            scalar_b(i).rotate_right(3)
        }
    }
    #[inline(never)]
    fn scalar_a(x: u64) -> u64 {
        std::hint::black_box(x).wrapping_mul(67891).wrapping_add(11)
    }
    #[inline(never)]
    fn scalar_b(x: u64) -> u64 {
        std::hint::black_box(x).wrapping_mul(123457).wrapping_add(97)
    }
}
fn main() {
    let odd: u64 = std::env::args().nth(1).unwrap().parse().unwrap();
    let sum = (0..100_000u64).fold(0u64, |v, i| v.wrapping_add(pathopt::choose_slot(i.wrapping_mul(2) + odd)));
    println!("{} {}", opaque::native(), sum);
}
