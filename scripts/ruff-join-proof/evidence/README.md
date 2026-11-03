# Direct inputs after a dependency rebuild

The client includes the actual emitted metadata of its producer using `include_bytes!`. Its constant expression checks every byte of that file. On Ohm 1.99.0-23, Cargo accepted the first edited check after the bytes changed. An independent empty target immediately reported E0308. With explicit path remapping the old Cargo restored the prior metadata mtime, accepted the edit and accepted the following unchanged check as well. Running the producer in a separate command before the client reproduced the latter failure.

The matched source fix is Cargo `9f2bf0359b8186e059bd853e2ce89ceef9fc5087`, built with `ohm-defaults` using signed Rust `d57fd1515986dccecdcece8da85e651bfb4b81f9`. The diagnostic binary's SHA-256 is `5c053ef9e38322558eac8e0f82056b4e2e958d42ccee477c30c18ad16aa6af7a`. The first edited check now reports E0308. The same applies when the literal names a symlink, the source edit preserves its mtime, the two commands are split, or the generated output is under a target inside `CARGO_HOME/registry`. On upgrading a twice-poisoned target, the first unchanged check reports E0308. The new Cargo uses a new fingerprint namespace for its declared dependency. The explicit input in the consumer source keeps its original path and unchanged bytes throughout the swap and the independent empty-child check.

| Original run | Actual Cargo commands | Successful kernel rustc execs with fixture crate name | Distinct native ELF bodies reexecuted | Histories |
|---|---:|---:|---:|---:|
| [Signed defaults, defaults off and upstream Cargo](https://github.com/astral-experiments/ohm/actions/runs/41593423160) | 112 | 130 | 12 | 14 |
| [Signed vs corrected Cargo, mtime, split, upgrade, configured directories](https://github.com/astral-experiments/ohm/actions/runs/41597635908) | 155 | 185 | 6 | 20 |

The controls include native builds, an edit that moves macro coordinates and keeps both recorded crate hashes stable, independent empty outputs and repaired inputs. The signed Cargo with automatic Ohm defaults disabled and upstream Cargo `5f94df4789f005f9a352888e8355ffc645b7ed0e` both diagnosed the increasing-mtime edit immediately on the same signed compiler. Seventeen Cargo repository tests passed on the corrected source, including the new generated-under-Cargo-home regression and existing successful early cutoffs. The test command and raw output are in the packet.

## Run the reduced case

Use Linux x86_64, a rustup installation and the extracted signed Rust SDK from `ohm-1.99.0-23`. Each command needs a new work directory. The script uses a private rustup home, checks the exact Cargo binary and signed rustc version, and records Cargo's original JSON and physical metadata digests. It does not fetch dependencies or modify installed toolchains.

```sh
python3 -IB reproduce.py --sdk "$SDK" --cargo "$SDK/bin/cargo" \
  --cargo-sha256 "$(sha256sum "$SDK/bin/cargo" | cut -d' ' -f1)" \
  --work "$PWD/fresh-signed" --expect shipped --mtime --split
python3 -IB reproduce.py --sdk "$SDK" --cargo "$FIXED_CARGO" \
  --cargo-sha256 5c053ef9e38322558eac8e0f82056b4e2e958d42ccee477c30c18ad16aa6af7a \
  --work "$PWD/fresh-fixed" --expect fixed --mtime --split --under-cargo-home
```

## Reopen the original evidence

`originals.tar.zst` contains the raw fixture compiler exec traces, Cargo output, Rust dep-info, binary metadata, recorded headers and complete native executables. Identical member bodies are stored once. Its SHA-256 is `58db965c92b6015f09897516c77e367ccf6fc2e1bcce7ca7de2dbad162296c41`. `package.py` recreates it from the two immutable original Actions ZIPs, hashes their complete contents against both GitHub's artifact receipt and the committed digests, and excludes the toolchain build itself. `reopen.py` checks the raw kernel events, diagnoses, content hashes, published upgrade input and native verdicts again.

```sh
python3 -IB reopen.py --packet originals.tar.zst \
  --llvm "$SDK/lib/libLLVM.so.23.1-rust-1.99.0-beta" --output /tmp/reopened-cargo.json
sha256sum /tmp/reopened-cargo.json reopened.json
```

Both outputs have SHA-256 `bb9f4f1c56fe46e268692b0575f10c9dd7290c7fb698aa108fc6a06e1dc556c1`. The timed compiler and release-performance studies use separate hardware registrations. Concurrent edits during rustc's first read of a source file require a separate compiler-side checksum guarantee.
