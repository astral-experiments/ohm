# Cargo profile used in the Apple Ruff measurements

The published Apple experiments ran on GitHub Actions with `CI=true`. Ohm Cargo reused compiled crates between commands. It disabled rustc incremental compilation for local crates. The original description of the Apple AST build as ordinary single-session incremental compilation was incorrect. This correction covers the measurements for Rust #276 and #277 and the additional Apple CLI probe. [Signed Cargo profile selection](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/src/workspace/profiles.rs#L76-L81) · [CI environment detection](https://github.com/astral-experiments/ohm-cargo/blob/2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c/crates/cargo-util/src/lib.rs#L24-L25)

The packet contains the complete kernel execution stream for every traced real edit in the seven listed artifacts. Across 28 observations, all 172 local Ruff compilers emitting artifacts ran without `-C incremental`. Both compiler roles occur in every artifact. The index records the artifact ID, original ZIP digest, file path and digest of each complete process stream. Only the edit phases are counted here.

| Real edit | Traced Cargo commands | Local Ruff rustcs | With rustc incremental |
| --- | ---: | ---: | ---: |
| AST build | 8 | 8 | 0 |
| AST test build | 8 | 8 | 0 |
| Focused ty_server e2e | 2 | 4 | 0 |
| Typeshed test build | 4 | 6 | 0 |
| Workspace test build | 2 | 136 | 0 |
| ty CLI build | 2 | 6 | 0 |
| Native controls for the inclusive ty_server timing | 2 | 4 | 0 |

On the signed Cargo revision, a separate one-crate build with no CI variables passed an incremental directory to rustc and left a nonempty work-products index and dependency graph there. Repeating from an empty target with `CI=true`, `TF_BUILD=1` or an empty `CI` suppressed both. The table above comes from the actual macOS jobs. The local control ran on Linux.

Run the offline verifier from this directory. With the original ZIPs named by artifact ID in one directory, pass that directory as `--archives DIR` to compare every retained stream byte for byte with the original.

```sh
python3 -IB verify.py
python3 -IB probe.py --rustup-home /path/to/rustup-home-with-signed-ohm
```

The subsequent developer-mode experiments exclude CI settings and require actual local compiler arguments plus populated crate-specific incremental files. [ty_server on Cargo #293](https://github.com/astral-experiments/ohm/actions/runs/41078503973) · [Typeshed on Cargo #293](https://github.com/astral-experiments/ohm/actions/runs/41078032982)
