#![feature(no_core)]
#![no_core]
extern crate minicore;
extern crate shared;

pub fn anchor() -> fn(*const u16) -> *const u16 { shared::hinted::<u16> }
