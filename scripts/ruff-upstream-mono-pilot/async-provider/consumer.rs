#![feature(async_drop)]

use mono_api::{AsyncRecord, Envelope};
use std::future::Future;
use std::mem::ManuallyDrop;
use std::task::{Context, Waker};

#[inline(never)]
unsafe fn constructor<'a>(value: &'a mut Envelope<AsyncRecord>) -> impl Future<Output = ()> + 'a {
    let ctor: unsafe fn(&'a mut Envelope<AsyncRecord>) -> _ =
        std::future::async_drop_in_place::<Envelope<AsyncRecord>>;
    unsafe { std::hint::black_box(ctor)(value) }
}

#[inline(never)]
pub fn evaluate(x: u32) -> (u32, u32) {
    let mut value = ManuallyDrop::new(Envelope(AsyncRecord(x.wrapping_add(2))));
    // This future has sole access until completion; ManuallyDrop prevents a second destructor.
    let mut future = std::pin::pin!(unsafe { constructor(&mut *value) });
    let mut cx = Context::from_waker(Waker::noop());
    assert!(future.as_mut().poll(&mut cx).is_pending());
    assert_eq!(mono_api::dropped(), 0);
    assert!(future.as_mut().poll(&mut cx).is_ready());
    (mono_left::anchor(x) + mono_right::anchor(x), mono_api::dropped())
}
