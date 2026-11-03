fn needs_send<T: Send>(_: T) {}
fn main() { needs_send(dep::observed!()); }
