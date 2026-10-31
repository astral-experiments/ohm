#![feature(no_core)]
#![no_core]
extern crate minicore;
extern crate shared;
extern crate provider;

#[no_mangle]
pub fn hinted_pointer() -> fn(*const u16) -> *const u16 { shared::hinted::<u16> }
#[no_mangle]
pub fn provider_pointer() -> fn(*const u16) -> *const u16 { provider::anchor() }
