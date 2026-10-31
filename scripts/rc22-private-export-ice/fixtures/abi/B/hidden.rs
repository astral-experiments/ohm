#[unsafe(export_name="ohm_private_abi_hook")]
#[inline(never)]
extern "C" fn hook(x: u64) -> u64 { x as u64 }
#[inline(never)] pub(super) fn exercise(x:u64)->u64 { hook(x as _) }
