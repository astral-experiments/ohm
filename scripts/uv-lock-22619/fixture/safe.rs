use uv_distribution_types::RemoteSource;
use uv_redacted::{SafeUrl, policy::SerializationPolicy};

pub fn require_policy<P: SerializationPolicy>() {
    fn require<T: RemoteSource>() {}
    require::<SafeUrl<P>>();
}
