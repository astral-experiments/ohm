#[repr(C)] struct Wire { value: u32 }
#[unsafe(export_name="ohm_private_abi_hook")]
#[inline(never)]
extern "C" fn hook(x: Wire) -> u64 { x.value as u64 }
#[inline(never)] pub(super) fn exercise(x:u64)->u64 { hook(Wire { value: x as _ }) }
