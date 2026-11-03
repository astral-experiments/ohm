# Linux code generation after the macOS warning fix

The two hosted performance measurements used Rust commit `9b63803c`. The follow-up `a325fe30` renamed one binding and its sole Linux-only use from `path` to `_path`. The final head passed the actual Linux and macOS compiler/regression jobs and the formatting/tidy job. [Compiler change](https://github.com/astral-experiments/ohm-rust/pull/351) · [Follow-up CI](https://github.com/astral-experiments/ohm-rust/actions/runs/41652048325)

The pinned bootstrap compiler compiled the entire `rustc_codegen_ssa` crate twice on x86-64 Linux at optimization level 3, using one codegen unit, identical paths, the same build identity and the same 38 dependency artifacts. Both complete 4,411,216-byte native objects were identical across all 9,114 ELF sections, including 1,371,710 executable bytes and 3,375 relocation sections.

A third private compilation swapped the device and inode arguments in the exact edited lookup. That changed one executable section, the 26,887-byte `CrateInfo::new` body into which the compiler inlined this path. The packet includes all three objects.

A second compilation emitted Rust metadata, LLVM bitcode and a native object together with ThinLTO enabled. The two 4,543,624-byte native objects matched. Across 559,800 decoded LLVM IR lines, two inline-assembly source-location metadata entries changed, attached at eight assembly sites in `TimingGuard` drop glue. The serialized bitcode differed at 38 bytes and Rust metadata at 365 bytes. Rust reported a different crate hash and an identical fixed StableCrateId. An outside Rust crate using each metadata file generated identical object code and an external relocation to the same `CrateInfo::new` symbol.

The performance results remain attributed to `9b63803c`. These local compilations held the crate version fixed. A normal distribution build incorporates its source revision, trains PGO and runs BOLT. Neither the distributed bytes nor hardware performance of `a325fe30` were measured here.

## Replay

Run on Python 3.10 or newer. The default command verifies native objects, the live-code control, the external relocation, both serialized input pairs, source Git blobs, and the two-token change.

```sh
sha256sum --check SHA256SUMS
python3 -ISB verify.py
```

To independently decode every IR line, reread both native metadata roots, and rerun the six Linux/macOS/Windows diagnostic cases, provide the matching LLVM 22.1 library and Rust 1.98.0 bootstrap executable. Their checksums and the original compiler banner are in `manifest.json`.

```sh
python3 -ISB verify.py --llvm /path/to/libLLVM.so.22.1-rust-1.98.0-stable --stage0 /path/to/rustc
```

`native.tar.xz` holds the two source blobs, three original compiler objects, and the two downstream objects and IR dumps. `link-inputs.tar.xz` holds both genuine bitcode files and both Rust metadata files.
