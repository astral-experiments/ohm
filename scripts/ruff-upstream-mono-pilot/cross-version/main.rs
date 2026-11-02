use cross_api::{Envelope, Recorded};
use std::mem::ManuallyDrop;

const REVISION: u32 = 17;

#[inline(never)]
fn evaluate(x: u32) -> (u32, u32) {
    let call = std::hint::black_box(cross_api::measure::<u32> as fn(u32) -> u32);
    let destroy = std::hint::black_box(std::ptr::drop_in_place::<Envelope<Recorded>> as unsafe fn(*mut Envelope<Recorded>));
    let mut value = ManuallyDrop::new(Envelope(Recorded(x + 1)));
    // ManuallyDrop leaves the initialized value available for this single explicit drop.
    unsafe { destroy(&mut *value) };
    (call(x) + cross_provider::anchor() + REVISION, cross_api::dropped())
}

fn main() {
    let x: u32 = std::env::args().nth(1).unwrap().parse().unwrap();
    let (value, dropped) = evaluate(x);
    println!("{value} {dropped}");
}
