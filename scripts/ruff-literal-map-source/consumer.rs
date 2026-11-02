use ruff_linter::linter::{ParseSource, lint_only};
use ruff_linter::registry::Rule;
use ruff_linter::settings::{LinterSettings, flags::Noqa};
use ruff_linter::source_kind::SourceKind;
use ruff_python_ast::PySourceType;
use ruff_python_ast::str::{Quote, TripleQuotes};
use ruff_python_literal::escape::UnicodeEscape;
use std::path::Path;

fn main() {
    let settings = LinterSettings::for_rule(Rule::from_code("F401").unwrap());
    let lint = |code: &str| {
        lint_only(
            Path::new("proof.py"),
            None,
            &settings,
            Noqa::Disabled,
            &SourceKind::Python {
                code: code.into(),
                is_stub: false,
            },
            PySourceType::Python,
            ParseSource::None,
        )
    };
    let unused = lint("import os\n");
    assert!(!unused.has_invalid_syntax());
    assert_eq!(unused.diagnostics.len(), 1);
    assert!(lint("import os\nprint(os)\n").diagnostics.is_empty());
    assert!(lint("def (:\n").has_invalid_syntax());
    let source = std::env::args().nth(1).unwrap();
    let escaped = UnicodeEscape::with_preferred_quote(&source, Quote::Double).escape_for_display();
    print!(
        "F401=1 used=0 invalid=1\n{}",
        escaped.str_repr(TripleQuotes::No)
    );
}
