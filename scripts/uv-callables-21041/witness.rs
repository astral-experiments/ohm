use std::sync::Arc;
use uv_pypi_types::{PypiSimpleDetail, PyxSimpleDetail};

fn main() {
    let input = r#"{"files":[
        {"filename":"one.whl","url":"https://a/one","hashes":{},"requires-python":">=3.10","size":12},
        {"filename":"two.whl","url":"https://a/two","hashes":{},"requires-python":">=3.10"},
        {"filename":"bad.whl","url":"https://a/bad","hashes":{},"requires-python":"%%%"}
    ]}"#;
    let pypi: PypiSimpleDetail = serde_json::from_str(input).unwrap();
    let pyx: PyxSimpleDetail = serde_json::from_str(input).unwrap();
    assert_eq!(pypi.files.len(), 3);
    assert_eq!(pyx.files.len(), 3);
    assert_eq!(pypi.files[0].size, Some(12));
    assert_eq!(pypi.files[1].filename.to_string(), "two.whl");
    let first = pypi.files[0].requires_python.as_ref().unwrap().as_ref().unwrap();
    let second = pypi.files[1].requires_python.as_ref().unwrap().as_ref().unwrap();
    assert!(Arc::ptr_eq(first, second));
    let first = pyx.files[0].requires_python.as_ref().unwrap().as_ref().unwrap();
    let second = pyx.files[1].requires_python.as_ref().unwrap().as_ref().unwrap();
    assert!(Arc::ptr_eq(first, second));
    assert!(pypi.files[2].requires_python.as_ref().unwrap().is_err());
    assert!(pyx.files[2].requires_python.as_ref().unwrap().is_err());
    let incomplete = r#"{"files":[{"filename":"bad.whl","url":"https://a/bad"}]}"#;
    assert!(serde_json::from_str::<PypiSimpleDetail>(incomplete).is_err());
    assert!(serde_json::from_str::<PyxSimpleDetail>(incomplete).is_err());
    println!("PyPI and Pyx parsed three files and agreed on interning and invalid inputs");
}
