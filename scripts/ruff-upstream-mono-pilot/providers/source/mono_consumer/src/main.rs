fn main() {
    let x: u32 = std::env::args().nth(1).unwrap().parse().unwrap();
    let (value, dropped) = mono_consumer::evaluate(x);
    println!("{value} {dropped}");
}
