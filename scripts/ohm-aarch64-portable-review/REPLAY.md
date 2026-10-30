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

To inspect the exact unpublished source series, use local copies of the public Rust and Cargo repositories. They must contain Rust commit `444c0273a2e2bc0b161e988d43c882349bc2d7a6` and Cargo commit `735e1528ed741015c57676dccf05dbdc0ff7bed1`. The following commands reconstruct every commit, blob and tree in a fresh private bare repository. They read the public repositories as Git object donors.

```sh
python3 -IB source/materialize.py rust /path/to/ohm-rust /path/to/new-rust.git
python3 -IB source/materialize.py cargo /path/to/ohm-cargo /path/to/new-cargo.git
```

The `V` ref contains both GNU literal-comment classifications and the versioned fallback. The `reader` ref contains the Cargo reader for that fallback. The `M-old` ref documents the previously measured unversioned intermediate. The signed Cargo compatibility qualification uses `V`. The later public #276 head changes workflow files only. The candidate result on top of that public head has the same complete compiler, tests, library and source-tool Git trees as the measured revision. See `source/clean-stack.json`.
