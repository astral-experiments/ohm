use uv_distribution_types::RemoteSource;

pub fn require_bare() {
    fn require<T: RemoteSource>() {}
    require::<url::Url>();
}
