extern crate rustc_fixture;
extern crate support;

#[unsafe(no_mangle)]
pub static DRIVER_SLOT: extern "C" fn() -> u32 = rustc_fixture::driver_value;
#[unsafe(no_mangle)]
pub static HOOK_SLOT: extern "C" fn() -> u32 = rustc_fixture::hook_value;
#[unsafe(no_mangle)]
pub static SUPPORT_SLOT: extern "C" fn() -> u32 = support::support_value;
