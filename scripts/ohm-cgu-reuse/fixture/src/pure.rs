#[inline(never)]
pub fn value() -> u32 { std::hint::black_box(41) }
