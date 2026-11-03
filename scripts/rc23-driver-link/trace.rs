mod v0;
use std::cell::RefCell;
use std::collections::BTreeSet;
use std::io::{self, BufRead, BufWriter, Write};
thread_local! {
    static ANCHORS: RefCell<BTreeSet<usize>> = const { RefCell::new(BTreeSet::new()) };
    static EVENTS: RefCell<Vec<String>> = const { RefCell::new(Vec::new()) };
}
fn crate_domain(start: usize, end: usize, disambiguator: u64, name: String) {
    assert!(name.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_'));
    EVENTS.with(|events| events.borrow_mut().push(format!("c,{start},{end},{disambiguator},{name}")));
}
fn anchor(pos: usize) { ANCHORS.with(|nodes| { nodes.borrow_mut().insert(pos); }); }
fn back_reference(start: usize, end: usize, target: usize) {
    assert!(ANCHORS.with(|nodes| nodes.borrow().contains(&target)), "bad structured backref at {start} -> {target}");
    EVENTS.with(|events| events.borrow_mut().push(format!("b,{start},{end},{target}")));
}
fn main() {
    let mut out = BufWriter::new(io::stdout().lock());
    for row in io::stdin().lock().lines() {
        let name = row.unwrap();
        EVENTS.with(|events| events.borrow_mut().clear());
        ANCHORS.with(|nodes| nodes.borrow_mut().clear());
        let complete = matches!(v0::demangle(&name),Ok((_, "")));
        if complete {
            EVENTS.with(|events| writeln!(out, "{}", events.borrow().join(";")).unwrap());
        } else {
            writeln!(out, "!").unwrap();
        }
    }
}
