use ruff_source_file::{LineIndex, OneIndexed, SourceCode};

fn main() {
    for (name, text) in [("lf", "a\nb"), ("crlf", "a\r\nb"), ("cr", "a\rb"), ("unicode", "é\r\nβ")] {
        let index = LineIndex::from_source_text(text);
        let source = SourceCode::new(text, &index);
        let first = source.line_end_exclusive(OneIndexed::from_zero_indexed(0));
        let second = source.line_end_exclusive(OneIndexed::from_zero_indexed(1));
        println!("{name} {} {}", u32::from(first), u32::from(second));
    }
}
