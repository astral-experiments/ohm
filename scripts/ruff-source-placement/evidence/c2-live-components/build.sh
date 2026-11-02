#!/bin/sh
set -eu
: "${LLVM_CONFIG:?matching LLVM 23 llvm-config}"
: "${SIGNED_LLVM:?signed Ohm -22 Linux LLVM shared library}"
: "${RUST_SOURCE:?checkout containing exact C2 source}"
: "${OUT:?separate output directory}"
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
product=$RUST_SOURCE/compiler/rustc_llvm/llvm-wrapper/OhmSourcePlacement.cpp
printf '%s  %s\n' ec8919787fde3c79f161bc93ac2daf766cf3573157dd00a171a05765d929eadd "$product" | sha256sum --check -
printf '%s  %s\n' 43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51 "$SIGNED_LLVM" | sha256sum --check -
test "$("$LLVM_CONFIG" --version)" = 23.1.1-rust-1.99.0-beta
mkdir -p "$OUT"
"${CXX:-clang++}" $("$LLVM_CONFIG" --cxxflags) -O2 -DNDEBUG -fPIC -shared -Wl,-z,defs "-Wl,-rpath,$(dirname -- "$SIGNED_LLVM")" "$product" "$SIGNED_LLVM" -o "$OUT/product.so"
for actor in live parse
do
  "${CC:-clang}" -O2 -I"$("$LLVM_CONFIG" --includedir)" "$here/$actor-actor.c" "$SIGNED_LLVM" "-Wl,-rpath,$(dirname -- "$SIGNED_LLVM")" -ldl -o "$OUT/$actor"
done
