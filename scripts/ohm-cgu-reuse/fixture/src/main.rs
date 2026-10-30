mod opaque;
mod pure;
fn main() { println!("{} {}", opaque::payload(), pure::value()); }
