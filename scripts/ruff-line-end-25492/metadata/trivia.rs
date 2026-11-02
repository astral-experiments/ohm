use ruff_python_trivia::textwrap::indent;

fn main() {
    for (source, expected) in [
        ("é\r\n\nβ\r", "> é\r\n>\n> β\r"),
        ("A\nB", "> A\n> B"),
        ("", ""),
    ] {
        assert_eq!(indent(source, "> "), expected);
        println!("{:?}", expected);
    }
}
