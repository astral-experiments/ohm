use std::io::{self, Write};
use unicode_normalization::UnicodeNormalization;
fn main() {
    let mut output = io::BufWriter::new(io::stdout().lock());
    for raw in 0..=0x10ffff {
        let Some(c) = char::from_u32(raw) else { continue };
        let mut bytes = [0; 4];
        let s: &str = c.encode_utf8(&mut bytes);
        let canon: String = s.nfd().collect();
        let compat: String = s.nfkc().collect();
        if canon != s || compat != s {
            writeln!(output, "{raw:06x} {:?} {:?}", canon.as_bytes(), compat.as_bytes()).unwrap();
        }
    }
    for s in ["hello + world", "Kelvin", "Ångström", "꟱", "🄰", "unterminated("] {
        writeln!(output, "{s} {}", ruff_python_parser::parse_expression(s).is_ok()).unwrap();
    }
}
