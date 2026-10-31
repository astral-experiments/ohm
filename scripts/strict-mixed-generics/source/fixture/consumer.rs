extern crate provider;
extern crate shared;

#[no_mangle]
pub fn hinted_pointer() -> fn(u32) -> u32 {
    shared::hinted::<u16>
}

#[no_mangle]
pub fn never_pointer() -> fn(u32) -> u32 {
    shared::never::<u16>
}

#[no_mangle]
pub fn foreign_pointer() -> extern "C" fn(u32) -> u32 {
    shared::foreign::<u16>
}

#[no_mangle]
pub fn caller_line_matches() -> bool {
    shared::caller::<u16>() == line!()
}

fn main() {
    assert!(provider::caller_line_matches());
    assert!(caller_line_matches());
    let (hinted, never, foreign) = provider::pointers();
    let value = std::hint::black_box(7);
    assert_eq!([hinted(value), never(value), foreign(value)], [9, 5, 5]);
    assert_eq!(
        [hinted_pointer()(value), never_pointer()(value), foreign_pointer()(value)],
        [9, 5, 5]
    );
    #[cfg(panic = "unwind")]
    assert!(std::panic::catch_unwind(|| hinted_pointer()(std::hint::black_box(u32::MAX))).is_err());
}
