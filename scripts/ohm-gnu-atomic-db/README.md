# AArch64 portable-atomic on the Ruff database build loop

This baseline asks whether the usual Ruff library build, or its test executable, leaves enough work attributable to portable-atomic for a compiler optimization to halve the command's instruction count. It uses the original, independently rebuilt 119-member GNU AArch64 SDK from Ohm Rust #283 and Cargo #301. The signed -21 Linux package has a different compiler and ships only x86-64 Linux libraries. [SDK provenance and source reconstruction](../ohm-gnu-syscall/source-rebuild/)

Run the isolated screen on GitHub Actions.

```sh
gh workflow run ci.yml --repo astral-experiments/ohm --ref charlie/qa-gnu-atomic-ruff-db
```

The workers independently build the parent and actual one-file change from Ruff #27849. One runs `cargo build -p ruff_db --lib`; the other runs `cargo test -p ruff_db --lib --no-run`. Both select `--target aarch64-unknown-linux-gnu --locked --offline -j4 --message-format=json`. Two normal unchanged visits follow the edit. Each records every rustc execution, compiler classification, linker and Cargo unit. A separate settled visit registers the physical binaries and commands before one full Callgrind diagnostic. Raw profiles and independent Valgrind totals must agree. Single unpaired process counts give an attribution and a conditional ceiling if other work persists. They do not estimate the effect of a candidate. [Ruff fix](https://github.com/astral-sh/ruff/commit/49bf50b1c782a4e443ae3edce2fdb6d81c2df562)

An undefined symbol must produce E0425. Each worker builds again after a repair and from an empty private target and build directory. The test worker runs the positive AST round-trip and each new bounds test under QEMU, outside the compile observation. A final run keeps the new tests and restores the old method. Each regression test must then fail while the positive round-trip still passes. Warm and clean hashes are reported separately. Any mismatch retains both complete products for examination.
