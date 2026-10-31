#![crate_type = "rlib"]

#[inline]
pub fn hinted<T>(value: u32) -> u32 {
    value + size_of::<T>() as u32
}

#[inline(never)]
pub fn never<T>(value: u32) -> u32 {
    value - size_of::<T>() as u32
}

#[inline]
pub extern "C" fn foreign<T>(value: u32) -> u32 {
    value ^ size_of::<T>() as u32
}

#[inline]
#[track_caller]
pub fn caller<T>() -> u32 {
    std::panic::Location::caller().line()
}
