
#[inline(never)]
pub fn offer_unrelated() -> fn(u32) -> u32 { mono_api::fold_value::<u64> }

#[inline(never)]
pub fn offer_unrelated_drop() -> unsafe fn(*mut mono_api::Envelope<(mono_api::Record, u16)>) {
    std::ptr::drop_in_place::<mono_api::Envelope<(mono_api::Record, u16)>>
}
