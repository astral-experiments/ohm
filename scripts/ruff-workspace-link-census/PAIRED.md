# Unchanged Ruff workspace test builds on two signed Ohm releases

One fresh x86-64 Linux worker builds Ruff `93526150df078af7dd8fc4226cdcc469539d2001` with the official -18 release, then repeats the whole protocol with -22. Each release starts with an independent Cargo home, build directory, target directory and SDK. The first installation is parked intact to free its canonical path. Both runs use the same unchanged Git checkout, workspace path, Rustup proxy, job count, flags and boot. Cargo verifies the same 498 registry archives against Cargo.lock. This experiment compares work counts and products.

```sh
cargo +ohm test --workspace --no-run --locked --offline -j8 --message-format=json
```

Each arm builds from empty, runs an ordinary unchanged command, runs another unchanged command with subprocess tracing, then records Cargo's fingerprint explanation on a third repeat. Each of the four outputs must pass `workspace_folders::single_file_workspace` in the actual ty_server e2e executable. The complete typed inventories and dirty sets guard the traced repeat. The collector records full versus link-only compiler modes and actual linker process ancestry.

Every typed file is hashed after each visit. Linked ELF files also carry section payload hashes, complete section-header values, all load segment hashes and the whole-file digest after zeroing only the GNU build-ID descriptor and the 64-bit `.rodata.sh_entsize` field. Missing, newly introduced or physically changed sections retain their raw values. The two masked fields have an independent historic source attribution in the [signed -20/-21 full-ELF comparison](https://github.com/astral-experiments/ohm/blob/8e5bcb16e04cf2ffc37c105ce672f4c7d6313d5e/scripts/packaged-release-workspace/LINUX_RESULTS.md).

The upstream release tar and all 79 actual installed files in each kit must match their frozen hashes, lengths and modes. Partial failures are uploaded. The original signed -22 single-receiver study remains available through the original `single-22` dispatch.

## Isolate the native marker reader

The separate `source-bisect-330` enrollment holds the signed -22 rustc, driver, standard library and Wild at the same physical paths and inodes throughout. It compares authenticated Linux Cargo builds from `2554a1df` and its direct child `8269d772`, each trained from empty in a new private target, build directory and Cargo home at the same logical paths. Both roles use previously built release-profile binaries that enable Ohm defaults. The actual Cargo versions and complete signed SDK inventory are reopened before use.

The selected newly linked workspace product is the real `ruff_text_size` constructors test. Its exact first-census workspace features are get-size, schemars and serde. Each role cold-builds and repeats twice; every visit runs its real `main` test and retains the full compiler and linker process tree, executable SHA and dirty unit list. No elapsed performance endpoint is registered.

The independent native consumer uses the unchanged Ruff lock revision of zmij, two search directories and a static native function returning 17, 29 or 41. Its build script watches its own source and emits both search paths. Each input mutation is compared with a separately empty build at the same physical target path, including a new higher-priority library, a same-inode/same-size/same-mtime malformed replacement, repair and both removals. A difference between an older warm executable and its independent empty counterpart is retained as a result. The experiment changes no Ruff source.
