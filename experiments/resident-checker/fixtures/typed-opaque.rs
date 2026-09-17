use std::rc::Rc;
fn selected(send: u8, non_send: Rc<u8>) -> impl Sized { send          }
fn requires_send<T: Send>(_: T) {}
fn caller() { requires_send(selected(1, Rc::new(1))); }
fn transitively_calls() { caller(); }
fn untouched() -> u8 { 3 }
