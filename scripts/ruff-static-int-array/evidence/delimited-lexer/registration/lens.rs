#![feature(proc_macro_span)]
extern crate proc_macro;
use proc_macro::{Span, TokenStream, TokenTree};
use std::fs::OpenOptions;
use std::io::Write;

fn span(s: Span) -> String {
    let a = s.start();
    let b = s.end();
    format!("{:?}@{:?}@{}:{}-{}:{}@{:?}", s.file(), s.byte_range(),
            a.line(), a.column(), b.line(), b.column(), s.source_text())
}

fn visit(input: TokenStream, depth: usize, stream: &mut String) {
    use std::fmt::Write;
    for t in input {
        let pos = span(t.span());
        match t {
            TokenTree::Group(g) => {
                writeln!(stream, "G {depth} {:?} {pos} {} {}", g.delimiter(),
                         span(g.span_open()), span(g.span_close())).unwrap();
                visit(g.stream(), depth + 1, stream);
                writeln!(stream, "E {depth}").unwrap();
            }
            TokenTree::Ident(i) => writeln!(stream, "I {depth} {pos} {:?}", i.to_string()).unwrap(),
            TokenTree::Punct(p) => writeln!(stream, "P {depth} {pos} {:?} {:?}", p.as_char(), p.spacing()).unwrap(),
            TokenTree::Literal(l) => writeln!(stream, "L {depth} {pos} {:?}", l.to_string()).unwrap(),
        }
    }
}

#[proc_macro]
pub fn capture(input: TokenStream) -> TokenStream {
    let mut text = String::new();
    visit(input, 0, &mut text);
    let name = std::env::var_os("OHM_TEST_LEXER_FILE").unwrap();
    let mut f = OpenOptions::new().create(true).append(true).open(name).unwrap();
    f.write_all(text.as_bytes()).unwrap();
    "()".parse().unwrap()
}
