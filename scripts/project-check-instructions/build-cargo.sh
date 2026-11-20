#!/usr/bin/env bash
set -euo pipefail
base=4193b7226ed980a4947848e979cd72444cc3bc22
test "$(git rev-parse HEAD)" = "$base"
out="$RUNNER_TEMP/alt-cargo"
mkdir -p "$out"
printf %s "$EXPERIMENT_PATCH" | base64 -d | gzip -dc > "$out/source.patch"
unset EXPERIMENT_PATCH
git apply --index "$out/source.patch"
git write-tree > "$out/source.tree"
git rev-parse HEAD > "$out/revision"
rustup toolchain install 1.100.0 --profile minimal --no-self-update
export CFG_RELEASE_CHANNEL=dev
export CARGO_HOME="$RUNNER_TEMP/registry"
cargo +1.100.0 build --release --locked -p cargo --bin cargo --features ohm-defaults,all-static
cp target/release/cargo "$out/cargo"
(cd "$out" && ./cargo -vV | tee version.txt && sha256sum cargo source.patch > manifest.sha256)
tar -C "$out" -cf - . | zstd -T4 -3 > "$RUNNER_TEMP/cargo.tar.zst"
