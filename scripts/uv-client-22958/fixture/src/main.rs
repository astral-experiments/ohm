#![allow(dead_code, unexpected_cfgs)]
mod output_format;
use output_format::{ListFormat, TreeFormat};
#[cfg(feature = "schema")]
use output_format::MetadataOutputVersion;
#[cfg(feature = "schema")]
fn twice<T: Copy>(value: T) -> (T, T) { (value, value) }
fn main() {
    assert!(matches!(ListFormat::default(), ListFormat::Columns));
    assert_eq!(TreeFormat::default(), TreeFormat::Text);
    #[cfg(feature = "schema")] {
        let result = std::env::args().nth(1).as_deref()
            .map(MetadataOutputVersion::from).unwrap_or_default();
        let (first, second) = twice(result);
        assert!(matches!((first, second), (MetadataOutputVersion::Preview, MetadataOutputVersion::Preview)));
        println!("{}", serde_json::to_string(&second).unwrap());
    }
    #[cfg(not(feature = "schema"))] println!("columns, text");
}
