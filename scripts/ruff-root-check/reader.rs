// This client consumes the five .rmeta files passed to the real ruff_dev compiler.
pub const EXPRESSION_BYTES: [(); EXPECTED] = [(); size_of::<ruff_python_ast::Expr>()];

pub fn parse_count(source: &str) -> Option<usize> {
    let parsed = ruff_python_parser::parse_module(source).ok()?;
    let module: &ruff_python_ast::ModModule = parsed.syntax();
    Some(module.body.len())
}

pub fn defaults(
    _: &ty_project::ProjectDatabase,
    rule: Option<ruff_linter::RuleSelector>,
) -> (ty_python_semantic::AnalysisSettings, bool) {
    (Default::default(), rule.is_some())
}
