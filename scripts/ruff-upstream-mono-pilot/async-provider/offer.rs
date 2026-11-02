
/// The value must stay initialized and exclusively accessible until this future finishes.
/// The caller must prevent an additional destructor call.
#[inline(never)]
pub unsafe fn offer_async<'a>(
    value: &'a mut mono_api::Envelope<mono_api::AsyncRecord>,
) -> impl std::future::Future<Output = ()> + 'a {
    let ctor: unsafe fn(&'a mut mono_api::Envelope<mono_api::AsyncRecord>) -> _ =
        std::future::async_drop_in_place::<mono_api::Envelope<mono_api::AsyncRecord>>;
    unsafe { std::hint::black_box(ctor)(value) }
}
