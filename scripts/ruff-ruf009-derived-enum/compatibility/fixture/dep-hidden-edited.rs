pub(super) fn classify(value: u8) -> bool { value == 1 }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Hidden { Value(u8) }
