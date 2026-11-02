# Unchanged Ruff workspace test builds on two signed Ohm releases

One fresh x86-64 Linux worker builds Ruff `93526150df078af7dd8fc4226cdcc469539d2001` with the official -18 release, then repeats the whole protocol with -22. Each release starts with an independent Cargo home, build directory, target directory and SDK. The first installation is parked intact to free its canonical path. Both runs use the same unchanged Git checkout, workspace path, Rustup proxy, job count, flags and boot. Cargo verifies the same 498 registry archives against Cargo.lock. This experiment compares work counts and products.

```sh
cargo +ohm test --workspace --no-run --locked --offline -j8 --message-format=json
```

Each arm builds from empty, runs an ordinary unchanged command, runs another unchanged command with subprocess tracing, then records Cargo's fingerprint explanation on a third repeat. Each of the four outputs must pass `workspace_folders::single_file_workspace` in the actual ty_server e2e executable. The complete typed inventories and dirty sets guard the traced repeat. The collector records full versus link-only compiler modes and actual linker process ancestry.

Every typed file is hashed after each visit. Linked ELF files also carry section payload hashes, complete section-header values, all load segment hashes and the whole-file digest after zeroing only the GNU build-ID descriptor and the 64-bit `.rodata.sh_entsize` field. Missing, newly introduced or physically changed sections retain their raw values. The two masked fields have an independent historic source attribution in the [signed -20/-21 full-ELF comparison](https://github.com/astral-experiments/ohm/blob/8e5bcb16e04cf2ffc37c105ce672f4c7d6313d5e/scripts/packaged-release-workspace/LINUX_RESULTS.md).

The upstream release tar and all 79 actual installed files in each kit must match their frozen hashes, lengths and modes. Partial failures are uploaded. The original signed -22 single-receiver study remains available through the original `single-22` dispatch.
