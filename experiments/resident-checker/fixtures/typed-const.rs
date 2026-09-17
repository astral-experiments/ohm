const fn selected() -> usize { 2        }
const fn middle() -> usize { selected() }
fn caller(_: [u8; middle()]) {}
fn downstream() { caller([0; 2]); }
fn untouched() -> usize { 77 }
