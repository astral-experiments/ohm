#[inline(never)]
pub extern "C" fn driver_value() -> u32 { 11 }

#[unsafe(no_mangle)]
pub extern "C" fn hook_value() -> u32 { 12 }
