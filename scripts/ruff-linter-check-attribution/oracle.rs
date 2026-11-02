// Read both public constants from the exact metadata returned by Cargo. The
// native client can be linked without building a new copy of ruff_linter.
use ruff_linter::registry::INCOMPATIBLE_CODES;

const FIRST: &str = INCOMPATIBLE_CODES[0].2;
const SECOND: &str = INCOMPATIBLE_CODES[1].2;

#[unsafe(no_mangle)]
pub extern "C" fn conflict_message(second: bool) -> *const u8 {
    if second { SECOND.as_ptr() } else { FIRST.as_ptr() }
}

#[unsafe(no_mangle)]
pub extern "C" fn conflict_message_len(second: bool) -> usize {
    if second { SECOND.len() } else { FIRST.len() }
}
