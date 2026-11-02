#![feature(rustc_attrs)]
#![allow(internal_features)]

#[cfg(shared)]
impl<T: ?Sized> &T {
    #[rustc_allow_incoherent_impl]
    pub fn from_reference() -> u8 {
        13
    }
}

#[cfg(mutable)]
impl<T: ?Sized> &mut T {
    #[rustc_allow_incoherent_impl]
    pub fn from_reference() -> u8 {
        29
    }
}

#[cfg(unrelated)]
pub struct Unrelated;
