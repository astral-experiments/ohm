use uv_errors::{Hint, HintOrdering, Hints};
fn main() {
    let mut hints = Hints::none();
    hints.push(Hint::new("general-last").with_ordering(HintOrdering::Last));
    hints.push(Hint::new("specific-first").with_ordering(HintOrdering::First));
    uv_warnings::write_warning_chain(&std::io::Error::other("original warning"), &hints).unwrap();
}
