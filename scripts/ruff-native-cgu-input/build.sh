#!/bin/sh
set -eu
: "${LLVM_CONFIG:?absolute path to matching LLVM 23 llvm-config}"
: "${SIGNED_LLVM:?absolute path to signed -22 libLLVM.so.23.1-rust-1.99.0-beta}"
: "${OUT:?new writable directory for the reader}"
test "$("$LLVM_CONFIG" --version)" = 23.1.1-rust-1.99.0-beta
printf '%s  %s\n' 43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51 "$SIGNED_LLVM" | sha256sum -c -
mkdir -p "$OUT"
"${CXX:-clang++}" $("$LLVM_CONFIG" --cxxflags) -DNDEBUG -O1 -gline-tables-only -Wl,-z,defs \
  "-Wl,-rpath,$(dirname "$SIGNED_LLVM")" "$(dirname "$0")/reader.cpp" "$SIGNED_LLVM" -o "$OUT/reader"
