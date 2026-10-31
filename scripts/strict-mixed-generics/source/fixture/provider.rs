#![crate_type = "rlib"]

extern crate shared;

pub fn pointers() -> (fn(u32) -> u32, fn(u32) -> u32, extern "C" fn(u32) -> u32) {
    (shared::hinted::<u16>, shared::never::<u16>, shared::foreign::<u16>)
}

pub fn caller_line_matches() -> bool {
    shared::caller::<u16>() == line!()
}
