#!/bin/sh
set -eu

# Use the compiler already in the pinned image without installing the source tree's optional targets.
toolchain=$(rustup show active-toolchain)
export RUSTUP_TOOLCHAIN=${toolchain%% *}
mkdir source wild
tar -xzf source.tar.gz --strip-components=1 -C source
cd source
if [ -f ../source.patch ]; then
  git apply ../source.patch
fi
CARGO_PROFILE_DIST_LTO=thin cargo build --locked --profile dist --package wild-linker --bin wild --target x86_64-unknown-linux-gnu
install -m 755 target/x86_64-unknown-linux-gnu/dist/wild ../wild/wild
install -m 644 LICENSE-APACHE LICENSE-MIT ../wild/
