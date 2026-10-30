use ruff_python_ast::Expr;
use ruff_python_parser::parse_module;

fn main() {
    let parsed = parse_module("answer = [x for x in range(8) if x < 4]\n").unwrap();
    assert!(parsed.has_valid_syntax());
    assert!(parse_module("answer = [\n").is_err());
    println!("Expr={} valid={} rejected", std::mem::size_of::<Expr>(), parsed.syntax().body.len());
}
