extern crate roster;

trait Fallback {
    fn from_reference() -> u8 {
        0
    }
}

impl<T: ?Sized> Fallback for &T {}
impl<T: ?Sized> Fallback for &mut T {}

fn main() {
    println!("{} {}", <&u8>::from_reference(), <&mut u8>::from_reference());
}
