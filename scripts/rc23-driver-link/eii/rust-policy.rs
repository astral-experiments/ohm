#![feature(extern_item_impls)]

#[inline(never)]
pub extern "C" fn rust_work(x: u64) -> u64 { x + 1 }

#[eii(default_slot)]
pub extern "C" fn weak_hook(x: u64) -> u64 { x + 2 }

#[eii(strong_slot)]
pub extern "C" fn strong_hook(x: u64) -> u64;

#[strong_slot]
pub extern "C" fn explicit_body(x: u64) -> u64 { x + 3 }

#[unsafe(export_name="_RNvC6spoof_10hook_name")]
pub extern "C" fn named_hook(x: u64) -> u64 { x + 4 }

#[used]
#[unsafe(no_mangle)]
pub static function_slots: [extern "C" fn(u64) -> u64;4] =
    [rust_work, weak_hook, strong_hook, named_hook];

#[unsafe(no_mangle)]
pub extern "C" fn get_slot(index: usize, x: u64) -> u64 {
    (std::hint::black_box(&function_slots)[index])(x)
}
