#[inline(never)]
pub fn anchor(x: u32) -> u32 { std::hint::black_box(x).wrapping_add(2) }
