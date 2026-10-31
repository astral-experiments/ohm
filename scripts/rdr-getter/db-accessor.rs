use ruff_db::source::SourceText;
pub fn title(source: &SourceText) -> Option<&str> {
    source.as_notebook()?.metadata().title.as_deref()
}
