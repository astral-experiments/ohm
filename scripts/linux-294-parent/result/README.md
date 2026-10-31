# Cargo #294 changed the result of an ordinary Ruff build on Linux

With the same signed Ohm 1.99.0-21 compiler and Wild, Cargo #294 stopped noticing a new library beside its linker. The immediate parent returned new Unicode values from Ruff’s library and rejected a malformed replacement. The signed release, a matched build of #294 and the combined three-fix Cargo kept returning the old value. The changes came from replacing Cargo alone. Every comparable independently empty build produced the changed value and rejected the malformed library. [Native run](https://github.com/astral-experiments/ohm/actions/runs/41150865959) · [One-commit Cargo difference](https://github.com/astral-experiments/ohm-cargo/compare/7277e6cdaba44c43294a07c0661fc8e69fd8e3e7...2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c)

| Existing target | Immediate parent 7277e6cd | Signed -21 2d44bd4a | Matched source 2d44bd4a | Combined b76dc800 | Each comparable empty target |
| --- | --- | --- | --- | --- | --- |
| Unchanged, library absent | 0 | 0 | 0 | 0 | 0 |
| Insert earlier valid library | 83 | 0 | 0 | 0 | 83 |
| Replace bytes in the same inode, size and mtime | 47 | 0 | 0 | 0 | 47 |
| Malform bytes in the same inode, size and mtime | Cargo 101 | 0 | 0 | 0 | Cargo 101 |
| Remove the library | 0 | 0 | 0 | 0 | 0 |

Success values come from an independently compiled executable calling `unicode_names2::character("NULL")`. The control `"NUL"` remained zero. On the parent's unchanged, valid insertion, valid replacement and removal, the signed compiler rebuilt `chacha20`, the Ruff build script and `unicode_names2`, and Wild linked once. On malformed bytes it ran the first two compilers and Wild failed before the generator ran. Signed #294, source-built #294 and the combined Cargo ran zero compilers and linkers on all five warm visits. The original command JSON counts the rustup and rustc execs separately. The offline reader pairs their exact arguments by PID and counts the actual signed rustc process once.

All four comparable roles used the same physical native compiler, driver and linker. The unmodified Cargo command gave cc `-B…/wild-ld`. GNU collect2 gave Wild `-L…/wild-ld`. With the library absent, Wild's real higher-priority `statx` returned ENOENT and Wild opened the system `libutil.a`. With the library present, both Wild and Ruff's executable build script opened the private `libutil.so` in each healthy empty control. On the warm parent insertion, compiler PIDs 4393, 4418 and 4461 built the three crates. Wild PID 4452 selected the library through worker 4455, and the generator PID 4459 opened it at runtime. Signed `-21` emitted the old v1 marker in `chacha20`'s real depfile in all four comparable roles.

The application supplied no native search flag and did not declare this file as an input. The fixture added it only beside Wild in a private SDK. This matches #294's stated choice to rely on declared inputs, and changes observable behavior relative to its own parent on a search directory Cargo adds itself. The stock Cargo and signed defaults-off comparisons linked using rust-lld, each with one real linker PID. Their empty builds ignored this private library in every state. Their warm results cannot establish how stock Cargo would handle a changed library in its own active search path. [#294’s stated contract](https://github.com/astral-experiments/ohm-cargo/pull/294)

The 60 visits used independent private targets and one fixed Ruff commit. All successful parent warm outputs matched the complete ELF and three generated Rust file hashes from the same-source, same-state empty reference. The three stale roles matched their own no-provider outputs instead. The output packet contains all four distinct full ELF images and all five distinct generated Rust file bodies, plus source depfiles, kernel events and Cargo streams. It contains no timings. The two matched native Cargo programs were built in independently empty roots from the exact adjacent trees. Their build receipts and the first rejected mixed-root build are preserved here. [Independent builds](https://github.com/astral-experiments/ohm/actions/runs/41150601667) · [Original registration and product hashes](https://github.com/astral-experiments/ohm/tree/a205283733a25a75d670108a106b93f1baa48cb2/scripts/linux-294-parent)

The original native ZIP is 4,063,239 bytes, SHA-256 `a358364839d6aceb01c738641c7de39a0c220f0d6fa2478b8d7cb4ca40388e71`. Verify its enrolled inputs, all 60 verdicts and native process identities from this directory.

```sh
python3 -IB reopen.py native.zip | cmp - verified.json
```
