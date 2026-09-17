use std::rc::Rc;

struct Wrapped<T>(T);

fn selected(send: u8, non_send: Rc<u8>) -> impl Sized { send          }
fn requires_send<T: Send>(_: T) {}
fn first_caller() { requires_send(Wrapped(selected(1, Rc::new(1)))); }
fn second_caller() { requires_send(Wrapped(selected(2, Rc::new(2)))); }
fn other_opaque() -> impl Sized { 1_u8 }
fn other_caller() { requires_send(Wrapped(other_opaque())); }
fn untouched() -> u8 { 3 }
