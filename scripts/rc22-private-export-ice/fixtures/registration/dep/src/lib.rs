use core::sync::atomic::{AtomicU8, Ordering};
static VALUE: AtomicU8 = AtomicU8::new(3);
pub fn value() -> u8 { VALUE.load(Ordering::SeqCst) }
mod hidden;
