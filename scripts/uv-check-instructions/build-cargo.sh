#!/usr/bin/env bash
set -euo pipefail
test "$(git rev-parse HEAD)" = 1ba8a0a1fa3404a92da16b1886fb70df8ce03970
patch=../coordinator/scripts/uv-check-instructions/salts-pilot.patch
git apply --check "$patch"
rustup toolchain install 1.100.0 --profile minimal --no-self-update
export CFG_RELEASE_CHANNEL=dev
export CARGO_HOME="$RUNNER_TEMP/registry"
out="$RUNNER_TEMP/cargo-kits"
mkdir -p "$out" "$RUNNER_TEMP/package"
cp "$patch" "$out/source.patch"
for role in control candidate; do
  if [[ "$role" == candidate ]]; then
    git apply "$patch"
  fi
  cargo +1.100.0 build --release --locked -p cargo --bin cargo --features ohm-defaults,all-static
  cp target/release/cargo "$out/$role"
  "$out/$role" -vV | tee "$out/version-$role.txt"
done
git rev-parse HEAD > "$out/revision"
(cd "$out" && sha256sum control candidate source.patch | tee manifest.sha256)
tar -C "$RUNNER_TEMP" -cf - cargo-kits | zstd -T4 -3 > "$RUNNER_TEMP/package/cargo.tar.zst"
