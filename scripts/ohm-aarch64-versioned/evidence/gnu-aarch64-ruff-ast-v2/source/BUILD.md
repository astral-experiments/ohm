# Rebuild the measured sources

The byte-bound replay uses the original 119-member kits listed in `sdk-members.json`. The hosted source and tool receipts are in `build-and-unit.json`. The binary-only SDK artifact was retained for three days. The following are the source-matched bootstrap settings for an independently built kit.

On an x86-64 Ubuntu Linux host, supply GNU `aarch64-linux-gnu-gcc`, `aarch64-linux-gnu-g++`, binutils, the AArch64 cross libc development package, Ninja and Python. Check out the Rust or Cargo revision reconstructed by `materialize.py`. The public Rust comparison uses Rust #276 at `444c0273`, the prerequisite uses `N`, and the finished compiler uses `V`. The native builds used the compiler source's own stage0 manifest and CI LLVM, with the following host and target operations.

```sh
host=x86_64-unknown-linux-gnu
target=aarch64-unknown-linux-gnu
export CC_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-gcc
export CXX_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-g++
export AR_aarch64_unknown_linux_gnu=/usr/bin/aarch64-linux-gnu-ar
flags=(--ci false --set build.submodules=false --set rust.omit-git-hash=true
       --set rust.debug-assertions=false --set rust.lto=off --set llvm.download-ci-llvm=true
       --set "target.$target.cc=$CC_aarch64_unknown_linux_gnu"
       --set "target.$target.cxx=$CXX_aarch64_unknown_linux_gnu"
       --set "target.$target.ar=$AR_aarch64_unknown_linux_gnu"
       --set "target.$target.linker=$CC_aarch64_unknown_linux_gnu")
python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$host" compiler/rustc library
python3 x.py "${flags[@]}" build --stage 1 -j8 --host "$host" --target "$target" library
python3 x.py "${flags[@]}" test --stage 1 -j8 --host "$host" --target "$host" \
    tests/run-make/ohm-checked-dep-info tests/run-make/ohm-relink-assembler-inputs
```

The Cargo reader was built on the GNU classification prerequisite kit, using the signed Ohm 1.99.0-20 Cargo as the build frontend, fresh target/shared/registry directories and its locked dependencies. Its release features were `ohm-defaults,all-static`. The signed stock host Wild was preserved.

```sh
cargo +ohm -Zohm-defaults=no fetch --locked --target x86_64-unknown-linux-gnu
cargo +ohm -Zohm-defaults=no build --release --locked --offline -p cargo --bin cargo \
    --features ohm-defaults,all-static -j8 --message-format=json
```

Use the original SDK and per-file manifest for an exact historical replay. Different host tool, path or bootstrap inputs can change output bytes. The registered instruction series reports only its independently authenticated binaries. A new build with other hashes requires its own source and native qualification.
