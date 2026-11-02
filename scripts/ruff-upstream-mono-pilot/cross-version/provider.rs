#[inline(never)]
pub fn anchor() -> u32 { std::hint::black_box(11) }

#[inline(never)]
pub fn offer() -> fn(u32) -> u32 { cross_api::measure::<u32> }

#[inline(never)]
pub fn offer_drop() -> unsafe fn(*mut cross_api::Envelope<cross_api::Recorded>) {
    std::ptr::drop_in_place::<cross_api::Envelope<cross_api::Recorded>>
}
