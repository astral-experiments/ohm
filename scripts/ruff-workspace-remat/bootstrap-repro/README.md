# Reproduce the optional CI-LLVM source and patch fallback

From the directory containing this file, run the following on Linux x86-64 with Python 3.11+, `cargo +ohm`, GNU `patch`, `cc`, `g++`, `as`, and `nm` installed.

```sh
python3 reproduce.py --rust "$OHM_RUST" --llvm "$CI_LLVM" --sdk "$SIGNED_OHM" --sources "$LLVM_CODEGEN"
```

- `OHM_RUST` is an Ohm Rust checkout at `1589b5884e0a690776147e3a72223843ab83dccb` or its immediate parent `74d8eeab285ee9e1b7b6ea00c94ae0d2dc21ecb6`. The kit reconstructs the complete original build script at `d1c2e85990d0d9fdb34052af19a1b3cf8ebba36b` using a small reverse patch, then checks its full SHA-256. Each of the four product inputs is checked against the detected commit.
- `CI_LLVM` is the matching GNU Rust-CI LLVM prefix with its headers and shared library. `SIGNED_OHM` is the signed matching Ohm GNU toolchain root with `bin/rustc`, `bin/cargo`, and the byte-identical LLVM shared library.
- `LLVM_CODEGEN` is the `llvm/lib/CodeGen` directory at Rust LLVM `1b9c0d5ff9bbe7634aead059efe6b11a7eeba145`. Both source files are checked by SHA-256. Omit `--sources` if that submodule is available in the Ohm Rust checkout.
- The default creates a fresh temporary directory, copies the needed public cache rows and verified Cargo archives, and builds offline with one Cargo job. Use `--online` to fetch missing public locked Cargo build dependencies into the private cache, and `--out PATH` to retain results at a chosen empty directory. The execution guard requires 8 GiB of available memory and 512 MiB of free disk throughout.

The runner builds the complete bootstrap library with a small local entry that parses a real bootstrap configuration. It exercises the actual downloader against a controlled `curl` executable, authentic source files, and the matching SDK revision header. The build-script probe compiles the old and new files with their verbatim product call sites and their pinned `cc` version. GNU patch only operates from a private directory. When the optional setup is refused, a real C++ compilation and the real signed LLVM library run the resulting stock wrapper against typed IR using both values of its `Allow` parameter.

The command prints the receipt directory. `bootstrap-cases.json` records nine download outcomes, subprocess arguments, and published source fingerprints. `patch-cases.json` records seven build-script cases, generated source digests, native return values, and the files present in each private patch directory. The successful patched C++ file should contain 174,061 bytes with SHA-256 `c1b3191f7869a684eebccbd821a013a15c0ff76940a9aab7187a2663bedc608a`. The rejected branches must leave no `.rej` or `.orig` file.

## Coverage and revisions

| Check | Executed source |
| --- | --- |
| Nine full-bootstrap download/caching cases | A private full build of Ohm Rust `74d8eeab285ee9e1b7b6ea00c94ae0d2dc21ecb6`’s `Config`, downloader, and mandatory-error machinery. These production functions have the same bytes at the preceding local `508387fdfb79ca34acb5a05e8b3bb67dffaf5b02` snapshot. |
| Seven patch and fallback cases | Complete original `rustc_llvm/build.rs` at `d1c2e85990d0d9fdb34052af19a1b3cf8ebba36b` (SHA-256 `f8d58249d1d98a5a9ede32608c1845978f0ed86fd927728fd9d7feb7394404ab`) and reviewed `74d8eeab` (SHA-256 `e43d13b9601cc4c4a2adb8000c31211fc6775b94ba5d260f393d84af6d2acf26`). Real GNU patch on the intermediate `508387fd` emitted a 13,941-byte reject. `74d8eeab` adds `--reject-file=-` and leaves no reject or backup. |
| Four separate bootstrap Cargo-child cases | Baseline `74d8eeab`, and an otherwise identical local build that removes the private source variable at `Builder::bare_cargo`. The committed fix `1589b5884e0a690776147e3a72223843ab83dccb` independently passed its positive and both rejection cases through the same physical child. The portable command also passed all 16 from an empty registry and target at this commit. This investigation used the real Cargo construction, rustc/rustdoc shims, `rustc_llvm_env`, signed Cargo, and a physical receipt from the child build script. The already-downloaded LLVM step was supplied from the registered SDK. The 16-case portable command exercises individual production entry points rather than this parent-to-child bootstrap path. |

The full-child comparison observed the following behavior. With a mismatching LLVM revision, unmodified bootstrap forwarded an already-exported `LLVM_RUSTC_OHM_COALESCER_SOURCE` and the product build script enabled that source. Removing it from the raw Cargo command selected stock. Under the same removal, an authenticated local source still replaced the inherited value on a matching revision. With the variable originally unset, the rejected source stayed unset end to end. A separate actual C++ preprocessing control reached the deliberately invalid header only when the inherited override was accepted. These results exercise source admission during bootstrap. An explicitly invoked standalone build script can still receive its own override.

The independent local source-failure audit also exercised a cache parent that was a regular file, a failed atomic publish, a malformed submodule paired with refused network or a fully authenticated cache, a missing patch payload, and an unusable output directory. These six controls selected the authenticated cache or the stock implementation as appropriate. They are separate from the 16 cases run by the portable command.
