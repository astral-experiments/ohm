#![allow(dead_code)]
mod hidden;
pub fn visible() -> impl std::fmt::Debug { 7u8 }
#[macro_export]
macro_rules! observed { () => { $crate::visible() }; }
