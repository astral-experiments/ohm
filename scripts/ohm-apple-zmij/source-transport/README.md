# Compiler source for the native Darwin qualification

From the private Ohm QA checkout, run the following commands with a fresh destination directory.

```sh
python3 -IB path/to/packet/prepare.py "$RUNNER_TEMP/ohm-compiler-source"
git -C "$RUNNER_TEMP/ohm-compiler-source" rev-parse HEAD HEAD^
```

The first command fetches eight levels of public Rust history at release 1.99.0 and imports the local Git bundle. Both original Ohm commits are then available for native builds. It checks the two full Git trees, 12 recursive gitlink IDs in each tree, the merge-bot history used to find the prebuilt LLVM, and the checked-out backtrace commit and tree. Use `x.py --ci false --set build.submodules=false` for the compiler-only build. The benchmark uses the separately authenticated, signed Ohm Cargo executable. The private Cargo source and ten other unused submodules stay uninitialized. Running a full distribution bootstrap would require additional source checkouts.

| Source | Commit | Tree |
| --- | --- | --- |
| [Public Rust 1.99.0](https://github.com/rust-lang/rust/releases/tag/1.99.0) | `b940084d7eb6a299eb4bfeb8e34901bc051e7ac4` | `6913117a864d5d61315111b926f9768f91c505a5` |
| Parent | `2035696c5316079f5b2e4373aee834839aac97e9` | `df84b98ba4deb07dd6f25446632704a1302c23a3` |
| Candidate | `444c0273a2e2bc0b161e988d43c882349bc2d7a6` | `f08c7d8e65d8d06ae7da0d81dafb25cc68124567` |
| [Public backtrace](https://github.com/rust-lang/backtrace-rs/commit/d902726a1dcdc1e1c66f73d1162181b5423c645b) | `d902726a1dcdc1e1c66f73d1162181b5423c645b` | `7f55c64f163ee354275bc92f21496620737401eb` |

The bundle is 1,158,652 bytes. It contains fork-only Git history for 262 commits beyond upstream and uses ordinary public Rust objects as delta bases. Its SHA-256 is `358196953e67cb9d9d9a57e82a5d5e499effaf7c277a704f1a7ea9d9ee78c654`. The pristine depth-eight public object database used about 49.0 MiB including Git indices on the validation host. A complete unpacked source checkout plus history used about 487 MiB. These sizes describe qualification infrastructure. The patch being tested adds no source bundle or second build-cache session to the Ohm toolchain.

Both revisions resolve the upstream LLVM artifact to `fba1b05a7bd8bdc73080edd02f672cef44648267`. The parent and candidate agree with that upstream commit on the LLVM submodule, bootstrap download stamp and Rust version. The compiler subtree changes from `294dda2b65f1801a085427c13923da2aa0938a40` to `1276de33b6b3042ee60ca5866621a63a12de8894`. The pinned all-source gitlinks are in `source.json`.

The assembly script disables Git credentials and account configuration on every child process. It fetches only rust-lang/rust and the public backtrace repository. Follow-up native jobs can use a local clone of the prepared directory for each compiler. The publisher can reproduce the pinned bundle bytes from the independent checkout by running the command below. Exact byte reproduction was tested using Git 2.55.0 and the same pack compression implementation. The checked commits and trees are portable Git identities.

```sh
python3 -IB path/to/packet/repack.py "$RUNNER_TEMP/ohm-compiler-source" "$RUNNER_TEMP/ohm-rust-verification.bundle"
```
