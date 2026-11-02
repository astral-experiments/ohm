
#[inline(never)]
pub fn offer_target() -> fn(u32) -> u32 { mono_api::fold_value::<u32> }

#[inline(never)]
pub fn offer_target_drop() -> unsafe fn(*mut mono_api::Envelope<mono_api::Record>) {
    std::ptr::drop_in_place::<mono_api::Envelope<mono_api::Record>>
}
