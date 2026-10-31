use ruff_db::source::SourceText;
pub fn is_python(source: &SourceText) -> bool {
    let first = source.as_notebook().is_some_and(|n| n.is_python_notebook());
    let second = source.as_notebook().is_some_and(|n| n.is_python_notebook());
    assert_eq!(first, second);
    first
}
