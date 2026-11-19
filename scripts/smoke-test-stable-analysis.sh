#!/usr/bin/env bash
set -euo pipefail

toolchain=$1
probe="$2/stable-analysis"
mkdir -p "$probe/src"
cat > "$probe/Cargo.toml" <<'EOF'
[package]
name = "stable-analysis"
version = "0.0.0"
edition = "2024"
EOF

check() {
  cat > "$probe/src/lib.rs"
  cargo +"$toolchain" check --offline --manifest-path "$probe/Cargo.toml" --message-format=short
}

reject() {
  if check 2>"$probe/log"; then
    echo "Expected $1 for $2" >&2
    return 1
  fi
  if ! grep -Fq "error[$1]" "$probe/log"; then
    cat "$probe/log" >&2
    return 1
  fi
}

# https://github.com/rust-lang/rust/issues/162331
check <<'EOF'
pub trait Trait {
    const N: usize;
}

impl Trait for u8 {
    const N: usize = 0;
}

pub fn f()
where
    u8: Trait,
{
    match 0 {
        <u8 as Trait>::N => {}
        _ => {}
    }
}
EOF

# https://github.com/rust-lang/rust/issues/165173
reject E0597 'a local borrowed through two supertraits' <<'EOF'
trait Super<T> {}
trait TwoSuper<A, B>: Super<A> + Super<B> {}

fn need<T: ?Sized + Super<U>, U>(_: &T, _: U) {}

fn f<'a>(x: &dyn TwoSuper<&'a u8, &'a u8>) {
    let local = 0u8;
    need(x, &local);
}
EOF

# https://github.com/rust-lang/rust/issues/164337
reject E0506 'an assignment while a closure result borrows the value' <<'EOF'
trait Id { type Out: ?Sized; }
impl<X: ?Sized> Id for X { type Out = X; }

fn f<T: std::fmt::Display>(t: <&T as Id>::Out) -> impl std::fmt::Display {
    t
}

fn main() {
    let mut x = 0;
    let a = (|| f(&x))();
    x = 1;
    println!("{a}");
}
EOF

# https://github.com/rust-lang/rust/issues/164420
reject E0597 'a reference to a local string' <<'EOF'
#![forbid(unsafe_code)]
use std::fmt::Display;

fn g(_: &u8) {}

fn foo<'a>(s: &'a String, flag: bool) -> impl Display + use<'a> {
    let _f: fn(&u8) = g;
    if flag {
        let local = String::from("dangling");
        return &local;
    }
    s
}
EOF
