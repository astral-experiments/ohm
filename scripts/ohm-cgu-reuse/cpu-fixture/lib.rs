#![no_std]
pub mod arithmetic {
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub extern "C" fn independent_llvm_mask(x: u64, y: u64) -> u64 {
        (x & x.wrapping_neg()).wrapping_add(y.leading_zeros() as u64)
    }

    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn scan_words(a: *const u32, b: *const u32, n: usize, seed: u32) -> u32 {
        let mut r = seed;
        let mut t = seed ^ n as u32;
        for i in 0..n {
            let x = unsafe { *a.add(i) };
            let y = unsafe { *b.add(i) };
            r = r.wrapping_add(x.wrapping_mul(31) ^ y.rotate_left(3));
            t = t.wrapping_add(x & !y);
        }
        r ^ t
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn map_words(a:*const f64, b:*const f64, out:*mut f64, n:usize) {
        for i in 0..n {
            unsafe { *out.add(i) = *a.add(i) * 1.375 + *b.add(i) / 3.25; }
        }
    }
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub unsafe extern "C" fn filled(p: *mut u8, n:usize, v:u8) {
        for i in 0..n {
            unsafe { *p.add(i) = v.wrapping_add(i as u8) }
        }
    }
}
pub mod file {
    #[unsafe(no_mangle)]
    #[inline(never)]
    pub extern "C" fn opaque_llvm_file() -> u64 {
        let pointer: *const u8;
        unsafe {
            core::arch::asm!("lea {p}, [rip + 2f]", ".pushsection .rodata", "2:", ".incbin \"payload.bin\"", ".popsection", p = out(reg) pointer);
            *pointer as u64
        }
    }
}
