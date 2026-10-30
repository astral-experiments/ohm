# Reproduce the ordinary GNU AArch64 build

The native replay runs the public Ruff edit with one enrolled compiler. On an x86-64 Linux host, install the Rustup proxies, Python 3.11 or later, Git, strace, GNU's AArch64 cross GCC and libc development files, and qemu-user. The replay requires a fresh directory with over 12 GiB free. It fetches the locked Ruff sources and crate archives when preparing the isolated Cargo home. The seven builds then use the locked, offline registry.

Supply a directory containing the SDK's 119 files listed in `source/sdk-members.json`, including the matching host and AArch64 standard libraries, the installed Rust driver for the selected role, and the same companion Cargo in all cases. The adapter copies and rehashes each enrolled file before use. Its Git checkout, Rustup home, Cargo home, target, build directory, retained ELF images and raw kernel traces live under the new directory.

```sh
python3 -IB replay.py A /absolute/public-276-sdk /absolute/new-public-work
python3 -IB replay.py V /absolute/versioned-sdk /absolute/new-versioned-work
```

For the incremental comparison against the GNU dependency-only prerequisite, pass `N` with its corresponding SDK. Each invocation starts from the exact parent of Ruff commit `ef23c9c39eb3029bab0139c3ea7ae6d95c4131e0`, applies its entire 74-file tree, and builds the same target.

```sh
cargo +ohm build -p ruff_python_ast --target aarch64-unknown-linux-gnu --locked --offline -j4 --message-format=json
```

The replay checks every physical rustc, the three source crates' emitted marker rules, all 95 ordered native object payloads, and a separately linked AArch64 consumer. Under QEMU its three Python versions change from `3.14 3.14 3.10` to `3.15 3.15 3.11`. A contrary consumer must fail with E0308. The invalid historical tree with one deliberately unresolved identifier must fail with E0425. After repair, a new empty build at the same visible paths must produce the same complete consumer ELF and ordered objects as every successful edited phase. The replay records the complete raw Rust archives separately because rustc may change the per-session names of otherwise identical objects.

The portable replay acquires native correctness and compiler counts. The published instruction protocol additionally trains a second fresh old tree, counts every user-space instruction in the actual Cargo and rustc processes through Callgrind, and compares those counted processes with literal native exec argv and inherited jobserver state. See `registration/COUNT.md` for the complete blocked design.

To reproduce the instruction endpoint from a fresh directory, install the Ubuntu 24.04 Valgrind package containing `/usr/bin/valgrind.bin` SHA-256 `def5fdcf6ae64a4d3e6af3786b622978d8313e0734ecf3f6cbe71d8be9e274c8` and a C compiler for its small parent, child and thread calibration. This command includes the seven native checks. It records independent settled, first-edit and immediate-repeat profiles with the original counter and the original fresh edit-cycle functions. Use a different new directory for each role. A single reviewer run contributes zero observations to the registered 12-block comparisons.

```sh
python3 -IB count_ir.py V /absolute/versioned-sdk /absolute/new-counted-work
python3 -IB reopen_native.py /absolute/new-counted-work/receipts
python3 -IB reopen_counter.py /absolute/new-counted-work/receipts
```

The last command reads the native terminal, every guest profile and its matching Valgrind log, actual argv and jobserver receipt, then recomputes the per-process counts. The original function hashes are in `registration/counter-sources.json`. The settled command uses the genuine dependency search paths recorded by the same installation’s independently empty AST build.

To inspect the exact unpublished source series, use local copies of the public Rust and Cargo repositories. They must contain Rust commit `444c0273a2e2bc0b161e988d43c882349bc2d7a6` and Cargo commit `735e1528ed741015c57676dccf05dbdc0ff7bed1`. The following commands reconstruct every commit, blob and tree in a fresh private bare repository. They read the public repositories as Git object donors.

```sh
python3 -IB source/materialize.py rust /path/to/ohm-rust /path/to/new-rust.git
python3 -IB source/materialize.py cargo /path/to/ohm-cargo /path/to/new-cargo.git
```

The `V` ref contains both GNU literal-comment classifications and the versioned fallback. The `reader` ref contains the Cargo reader for that fallback. The `M-old` ref documents the previously measured unversioned intermediate. The signed Cargo compatibility qualification uses `V`. The later public #276 head changes workflow files only. The candidate result on top of that public head has the same complete compiler, tests, library and source-tool Git trees as the measured revision. See `source/clean-stack.json`.

The proposed Ohm -21 source pin is Rust `c79998a5cd143c445a4b2528f20953b176a65c5d` with Cargo `2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c`. All three Rust patches applied directly to that authenticated full tree. This retains #277’s Darwin CRC classifier and associated tests and the #278 resolver change. The unmodified -21 sources have neither the GNU classification nor the versioned Cargo reader. The instruction measurements described here cover the exact A, N and V builds with the companion reader. See `source/release21-applicability.json` for the source-only check.
