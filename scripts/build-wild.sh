#!/bin/sh
set -eu

# Use the pinned image's compiler before the source tree can select its toolchain.
toolchain=$(rustup show active-toolchain)
export RUSTUP_TOOLCHAIN=${toolchain%% *}
mkdir source wild
tar -xzf source.tar.gz --strip-components=1 -C source
cd source
git apply ../source.patch
cargo build --locked --profile dist --package wild-linker --bin wild --target x86_64-unknown-linux-gnu
install -m 755 target/x86_64-unknown-linux-gnu/dist/wild ../wild/wild
install -m 644 LICENSE-APACHE LICENSE-MIT ../wild/
