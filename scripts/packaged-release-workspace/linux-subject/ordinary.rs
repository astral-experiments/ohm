fn main() {
    let block = "       # foo\n       # bar\n        return 2";
    let observed = ruff_python_trivia::textwrap::dedent_to(block, "    ").unwrap();
    print!("{observed}");
}
