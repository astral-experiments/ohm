// Keep the queried trait, receiver and call site at the same definitions across installations.
trait Score {
    fn score() -> u32;
}

struct Left;
struct Right;

impl Score for Left {
    fn score() -> u32 {
        11
    }
}

#[inline(never)]
fn observe<T: Score>() -> u32 {
    T::score()
}

fn main() {
    println!("{}", observe::<Left>());
    let _right = Right;
}
