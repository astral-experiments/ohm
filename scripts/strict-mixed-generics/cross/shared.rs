#![feature(no_core)]
#![no_core]
extern crate minicore;

#[inline]
pub fn hinted<T>(p: *const T) -> *const T { p }
