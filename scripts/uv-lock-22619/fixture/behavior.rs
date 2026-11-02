use uv_distribution_types::{Error, RemoteSource};
use uv_redacted::{SafeUrl, policy::{Raw, Stripped}};

pub fn verify_behavior() {
    let input = "https://example.org/demo%20name.whl?sig=sentinel";
    let url = SafeUrl::parse(input).unwrap().with_policy(Stripped);
    assert_eq!(url.filename().unwrap(), "demo name.whl");
    assert_eq!(url.as_str(), input);

    let input = "mailto:ferris@example.com?x-amz%2dsignature=sentinel&safe=value";
    let url = SafeUrl::parse(input).unwrap().with_policy(Raw);
    let Error::MissingPathSegments(display) = url.filename().unwrap_err() else {
        panic!("unexpected error variant")
    };
    assert_eq!(display, "mailto:ferris@example.com?x-amz-signature=****&safe=value");
    assert_eq!(url.as_str(), input);
}

fn main() {
    verify_behavior();
}
