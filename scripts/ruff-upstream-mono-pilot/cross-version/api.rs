use std::sync::atomic::{AtomicU32, Ordering};

static DROPPED: AtomicU32 = AtomicU32::new(0);
pub struct Envelope<T>(pub T);
pub struct Recorded(pub u32);

impl Drop for Recorded {
    #[inline(never)]
    fn drop(&mut self) { DROPPED.fetch_add(self.0, Ordering::SeqCst); }
}

#[inline(never)]
pub fn dropped() -> u32 { DROPPED.load(Ordering::SeqCst) }

#[inline(never)]
pub fn measure<T>(x: u32) -> u32 {
    x.wrapping_mul(3).wrapping_add(std::mem::size_of::<T>() as u32)
}
