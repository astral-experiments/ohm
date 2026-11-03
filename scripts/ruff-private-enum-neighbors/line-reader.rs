use ruff_source_file::{LineIndex, OneIndexed};

fn main() {
    for text in ["a\r\nb", "a\nb", "b"] {
        let index = LineIndex::from_source_text(text);
        let end = index.line_end_exclusive(OneIndexed::from_zero_indexed(0), text);
        println!("{}", u32::from(end));
    }
}
