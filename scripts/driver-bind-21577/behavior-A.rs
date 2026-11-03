use uv_errors::Hints;
fn main() {
    let mut hints = Hints::none();
    hints.push(String::from("general-last"));
    hints.push(String::from("specific-first"));
    uv_warnings::write_warning_chain(&std::io::Error::other("original warning"), hints).unwrap();
}
