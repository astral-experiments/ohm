use ruff_options_metadata::{OptionEntry, OptionsMetadata};
use ruff_workspace::options::Options;

fn main() {
    let key = std::env::args().nth(1).expect("one option name");
    match Options::metadata().find(&key) {
        Some(entry @ OptionEntry::Field(_)) => print!("{entry}"),
        Some(OptionEntry::Set(_)) => std::process::exit(3),
        None => std::process::exit(2),
    }
}
