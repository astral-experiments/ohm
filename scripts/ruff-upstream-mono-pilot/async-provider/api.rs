#![feature(async_drop)]

use std::pin::Pin;
use std::sync::atomic::{AtomicU32, Ordering};
use std::task::Poll;

static DROPPED: AtomicU32 = AtomicU32::new(0);

pub struct Envelope<T>(pub T);
pub struct AsyncRecord(pub u32);

impl Drop for AsyncRecord {
    fn drop(&mut self) {}
}

impl std::future::AsyncDrop for AsyncRecord {
    async fn drop(self: Pin<&mut Self>) {
        let mut first = true;
        std::future::poll_fn(move |cx| {
            if first {
                first = false;
                cx.waker().wake_by_ref();
                Poll::Pending
            } else {
                Poll::Ready(())
            }
        })
        .await;
        DROPPED.fetch_add(self.0.wrapping_mul(3).wrapping_add(5), Ordering::SeqCst);
    }
}

#[inline(never)]
pub fn dropped() -> u32 {
    DROPPED.load(Ordering::SeqCst)
}
