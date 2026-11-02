use annotate_snippets::{AnnotationKind, Level, Patch, Renderer, Snippet};

use annotate_snippets::renderer::DecorStyle;

use std::io::Write;
fn emit(text: String) {
    let mut out = std::io::stdout().lock();
    out.write_all(&(text.len() as u64).to_le_bytes()).unwrap();
    out.write_all(text.as_bytes()).unwrap();
}
fn multiple_insertions() {
    let source = "line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\nline 9\nline 10\nline 11\nline 12\nline 13\n";
    let input = &[
        Level::ERROR
            .primary_title("main diagnostic message")
            .id("test-diagnostic")
            .element(
                Snippet::source(source)
                    .path("example.py")
                    .annotation(AnnotationKind::Primary.span(7..13)),
            ),
        Level::HELP.secondary_title("Replace three lines").element(
            Snippet::source(source)
                .patch(Patch::new(7..7, "fixed "))
                .patch(Patch::new(42..42, "fixed "))
                .patch(Patch::new(87..87, "fixed ")),
        ),
    ];

    let renderer = Renderer::plain();
    emit(renderer.render(input));
    emit(renderer.decor_style(DecorStyle::Unicode).render(input));
}
fn snippet_with_cell() {
    let source = "First line\r\nSecond oops line";
    let input = &[Level::ERROR.primary_title("oops").element(
        Snippet::source(source)
            .cell_index(Some(1))
            .annotation(AnnotationKind::Primary.span(19..23).label("oops")),
    )];

    let renderer = Renderer::plain();
    emit(renderer.render(input));
    emit(renderer.decor_style(DecorStyle::Unicode).render(input));
}

fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("multiple_insertions") => multiple_insertions(),
        Some("snippet_with_cell") => snippet_with_cell(),
        _ => panic!("unknown case"),
    }
}
