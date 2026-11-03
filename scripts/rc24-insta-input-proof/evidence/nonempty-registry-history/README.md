# A nonempty registry fingerprint from released Cargo

Both signed Linux releases returned stale native code when the private, extracted source of a locked registry package changed on disk. The signed -24 build with pristine registry sources returned a byte-identical warm and independently empty result after the same prerequisite edit. The existing Cargo source documents its assumption that verified registry tarballs and their unpacked packages are frozen. It also acknowledges that the extracted files are writable. [Released registry-source contract](https://github.com/astral-experiments/ohm-cargo/blob/abc70d60a6fd89c10d5f65cf85820d9b78d5affe/src/sources/registry/mod.rs#L169-L178)

The example publishes a tiny package to an isolated file-backed registry. Its library calls a real path-patched prerequisite, contains the literal `17u8`, and includes a genuine build-script product from `OUT_DIR` containing 83. The initial executable prints `7 17 83`. On the selected edit, the prerequisite's private implementation changes 7 to 9 with its complete public API header unchanged. In the intervention, the fixture also overwrites `17u8` with `29u8` in the extracted registry `src/lib.rs`, preserving the real file's device, inode, size and nanosecond mtime. The ctime may change. The transport `.crate`, package checksum, committed registry index, Cargo.lock, generated source and build products receive no intervention. All target records come from ordinary `cargo +ohm build --locked --offline -j1 --message-format=json`. Each history starts in its own empty target/build, registry and private rustup installation. Compiler and Cargo pathnames remain fixed within each history.

| Installed Cargo at seed and first edit | Genuine saved inputs from seed | First edited native output | Independent empty at same edit |
|---|---|---|---|
| Signed -23, both visits, with its own Rust | v2, generated file without checksum | 9 17 83 | 9 29 83 |
| Signed -23, both visits, with -24 Rust | v2, generated file without checksum | 9 17 83 | 9 29 83 |
| Signed -24, both visits | v5, generated file with BLAKE3 | 9 17 83 | 9 29 83 |
| Signed -24 seed, signed -23 first edit, unchanged -24 Rust | v5 at seed, regenerated v2 at the edit | 9 29 83 | 9 29 83 |
| Signed -24 seed, deferred-input candidate first edit | v5 at seed, both generated and package source verified at the edit in v6 | 9 29 83 | 9 29 83, exact complete executable and registry-library metadata |
| Signed -24, pristine registry source throughout | v5, generated file with BLAKE3 | 9 17 83 | 9 17 83, exact complete executable |

Both signed and source-matched -24 Cargo emitted a genuine nonempty v5 fingerprint that omitted the actual registry package source. Under the modified-source history, the release native was still `9 17 83` on the subsequent unchanged command. Installing the candidate **after** the stale target had settled also retained that result while all ordinary prerequisites stayed fresh. The next actually rebuilt prerequisite produced `8 29 83` and a complete v6 record, matching the independent empty executable byte for byte. In the signed -24 history, restoring the prerequisite value to 9 on empty, same-path builds produced complete ELF `652f4993c038b1240c170a4ff29a54ff87d309c2d0fd0ee797ac3f7b61655419` under both old and new Cargo. In the new-reader-at-edit history the malformed registry expression produced E0308 twice, preserved the last valid executable, and repair produced `8 17 83` with its independent empty ELF.

The candidate can validate the previously consumed registry bytes when it is about to skip work **after a prerequisite rebuilt**. It rebuilds a unit whose genuine older record lacks that evidence. Its ordinary initial freshness decision retains Cargo’s existing registry assumption. Signed -23 also exhibited the modified-source behavior on its own valid cache before #436. Its reader supports v2/v4 and refused the later v5 in the explicit downgrade test. [Signed -23 decoder](https://github.com/astral-experiments/ohm-cargo/blob/7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed/src/compiler/fingerprint/dep_info.rs#L138-L150) · [Signed -24 package filtering](https://github.com/astral-experiments/ohm-cargo/blob/abc70d60a6fd89c10d5f65cf85820d9b78d5affe/src/compiler/fingerprint/dep_info.rs#L518-L534)

## Reopen or run it independently

The readback reconstructs 61 real Cargo verdicts in nine isolated histories, independently parses each binary Cargo record, verifies the original package and physical metadata hashes and BLAKE3 fields, and runs all 26 distinct complete native ELF bodies on Linux x86-64. It checks all six E0308s and the exact endpoint-dependent ELF comparisons above. The first 15 visits use the source-matched old Cargo. The other 46 use the shipped old binaries. All are separate from the hardware performance cohorts. Two earlier diagnostic admission failures are retained separately in `earlier-refusals.json`. This local fixture uses raw Cargo and compiler outputs and native executable results. The corresponding eleven-command real `insta` migration separately verifies true kernel rustc invocations. [Original native migration and two-boot cost](../deferred-pilot-41736348154/README.md)

From this packaging checkout with Python 3.11+, a C compiler and an x86-64 Linux native runtime, run

```sh
q=scripts/rc24-insta-input-proof/evidence/nonempty-registry-history
python3 -IB "$q/review.py" --run-native > /tmp/registry-source-reopened.json
cmp "$q/reopened.json" /tmp/registry-source-reopened.json
```

For a fresh acquisition, set SDK23 and SDK24 to the unpacked official x86-64 Linux releases, FIXED to the matched candidate Cargo from factory 41734567724, and OUT to an existing directory with at least 20 GiB free. The command rejects pre-existing case roots and checks the actual binary hash at every installation. The matched candidate is commit `1b44b5d3dc540c491c79bbf47fae8b286e8f797a`, physical Cargo `32df98560d4ac57c4c959c762095a3afe6a3bbe62b44d8fc6e6bf8071f53a53e`. Signed -23 Cargo is `7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed` / `f7cfe387ec3bd7e2e367d80596f379349faa23530194bf7cd7ba80a33adc6dee`. Signed -24 Cargo is `abc70d60a6fd89c10d5f65cf85820d9b78d5affe` / `a4faa288657042d02767a38812c7498218dfcafc945abfe3b4a44c07323a1a24`. All source-matched Cargo builds are separate from the signed distribution's PGO/BOLT programs.

```sh
python3 -IB "$q/replay.py" "$OUT/release" --published-parent --legacy-control --signed "$SDK24" --parent "$SDK24/bin/cargo" --candidate "$FIXED"
python3 -IB "$q/replay.py" "$OUT/fixed-first" --first-clean --published-parent --signed "$SDK24" --parent "$SDK24/bin/cargo" --candidate "$FIXED"
python3 -IB "$q/replay.py" "$OUT/pristine" --published-parent --pristine-source --signed "$SDK24" --parent "$SDK24/bin/cargo" --candidate "$FIXED"
python3 -IB "$q/replay.py" "$OUT/previous" --predecessor matched23 --signed "$SDK23" --parent "$SDK23/bin/cargo" --candidate "$SDK23/bin/cargo"
python3 -IB "$q/replay.py" "$OUT/older-cargo" --predecessor cargo23 --signed "$SDK24" --parent "$SDK23/bin/cargo" --candidate "$SDK23/bin/cargo"
python3 -IB "$q/replay.py" "$OUT/downgrade" --predecessor from24 --signed "$SDK24" --parent "$SDK24/bin/cargo" --candidate "$SDK23/bin/cargo"
```
