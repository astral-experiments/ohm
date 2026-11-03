const fn byte_hash(bytes: &[u8]) -> u64 {
    let mut hash = 14695981039346656037u64;
    let mut i = 0;
    while i < bytes.len() { hash = (hash ^ bytes[i] as u64).wrapping_mul(1099511628211); i += 1; }
    hash
}
const ACTUAL_INPUT: &[u8] = include_bytes!(r#"@RUST_METADATA@"#);
const _: [(); 1] = [(); (byte_hash(ACTUAL_INPUT) == @OLD_FNV@u64) as usize];
