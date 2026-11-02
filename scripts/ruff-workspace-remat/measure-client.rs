use ruff_options_metadata::{OptionEntry, OptionsMetadata};
use ruff_workspace::options::Options;
use std::hint::black_box;

fn main() {
    let mut args = std::env::args().skip(1);
    let n = args.next().unwrap().parse::<u32>().unwrap();
    let keys: Vec<_> = args.collect();
    assert_eq!(keys.len(), 3);
    let mut digest = 14695981039346656037_u64;
    for _ in 0..n {
        for key in &keys {
            let field = match Options::metadata().find(black_box(key.as_str())) {
                Some(entry @ OptionEntry::Field(_)) => format!("{entry}").into_bytes(),
                Some(OptionEntry::Set(_)) => panic!("expected a leaf field"),
                None => vec![0xff],
            };
            for byte in field {
                digest = (digest ^ u64::from(byte)).wrapping_mul(1099511628211);
            }
        }
    }
    println!("{digest:016x}");
}
