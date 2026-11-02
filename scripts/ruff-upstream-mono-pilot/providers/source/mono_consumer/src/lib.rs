use mono_api::{Envelope, Record};
use std::hint::black_box;
use std::mem::ManuallyDrop;

#[inline(never)]
pub fn evaluate(x: u32) -> (u32, u32) {
    let target = black_box(mono_api::fold_value::<u32> as fn(u32) -> u32);
    let dropper = black_box(std::ptr::drop_in_place::<Envelope<Record>> as unsafe fn(*mut Envelope<Record>));
    let mut value = ManuallyDrop::new(Envelope(Record(x.wrapping_add(1))));
    // ManuallyDrop leaves initialization intact and suppresses automatic destruction.
    unsafe { dropper(&mut *value) };
    let result = target(x).wrapping_add(mono_left::anchor(x)).wrapping_add(mono_right::anchor(x));
    (result, mono_api::dropped())
}
