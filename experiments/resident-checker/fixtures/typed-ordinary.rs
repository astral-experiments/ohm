fn selected(value: u32) -> u32 { value       }
fn caller() -> u32 { selected(7) }
fn transitively_calls() -> u32 { caller() }
fn untouched() -> u32 { 9 }
