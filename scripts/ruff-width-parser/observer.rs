use std::io::{self, Write};
use ruff_formatter::{format, format_args, LineWidth, SimpleFormatContext, SimpleFormatOptions};
use ruff_formatter::prelude::*;
use unicode_width::UnicodeWidthChar;

fn breaks(s: &str, width: u16) -> bool {
    let context = SimpleFormatContext::new(SimpleFormatOptions {
        line_width: LineWidth::try_from(width).unwrap(),
        ..SimpleFormatOptions::default()
    });
    let doc = format!(context, [group(&format_args![token("x"), soft_line_break_or_space(), text(s)])]).unwrap();
    doc.print().unwrap().as_code().contains('\n')
}

fn main() {
    let mut output = io::BufWriter::new(io::stdout().lock());
    for raw in 0..=0x10ffff {
        let Some(ch) = char::from_u32(raw) else { continue };
        let width = UnicodeWidthChar::width(ch).map_or(255, |x| u8::try_from(x).unwrap());
        let mut encoded = [0u8; 4];
        let s = ch.encode_utf8(&mut encoded);
        let wraps = if ch.is_control() { [255, 255] } else {
            [u8::from(breaks(s, 2)), u8::from(breaks(s, 3))]
        };
        output.write_all(&[width, wraps[0], wraps[1]]).unwrap();
    }
}
