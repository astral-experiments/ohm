# Why the full Cargo comparison was refused

The historical Ruff RUF009 check changed a genuine locked external input between the release-equivalent Cargo source 7024b0d2 and repaired Cargo 4a6de785. Both used the same signed Ohm -23 rustc. This experiment required equal external bytes before admitting any instruction price. No Ruff command was scored. [Registration and worker](https://github.com/astral-experiments/ohm/actions/runs/41611363509)

Eight otherwise empty OLD Ruff builds alternated the two Cargo executables. Each recorded 1,322 physical external inputs, including the actual procedural macros, registry and Git libraries and generated build-script output files. All 16 cross-role comparisons differed on exactly 352 entries. Of these, 339 were stable within each role and different across roles (269 .rmeta, 45 .rlib and 25 .so). Of the 1,357 names in the union, another 43 varied within at least one role, including 40 generated autocfg names, a jemalloc configure log and the get-size macro and its dependent metadata. The broad Cargo source change has no fixed-input steady instruction estimate here.

A separate small control took both actual cfg-if 1.0.0 rustc commands from the upgrade (target check and an external link build). Each was replayed in both orders with and without the sole argument change, `-Z checksum-hash-algorithm=blake3`, on Ruff's authenticated locked source. The switch alone changed the crate's public and private metadata hashes in both modes. The two linked archives differed only in lib.rmeta, with identical native and lib.rmeta-link members. The stepped dep-info acquired exactly one real source checksum. The registration retains the direct args, signed driver identity, registry/lock source hashes and outputs. This explains one concrete source of the rejected full equality condition. The study did not assign all 339 differences to that flag. [Tracked compiler option](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_session/src/options.rs#L2440) · [Encoded SourceFile checksum](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_span/src/lib.rs#L1997)

Run the compact checks from this directory:

```sh
python3 -IB reopen.py
python3 -IB flag.py
```

To authenticate all eight original vector files through the worker ZIP, add `--original /absolute/path/to/original.zip` to the first command. GitHub Actions artifact 13219456755 is 3,171,164 bytes, SHA-256 `4d4174e42163408029f0b82d0c868ef567f034d8239145e5041e66769cdd8bb0`. To repeat the physical rustc control, pass `--rustup-home /absolute/path/to/private/rustup --crate /absolute/path/to/cfg-if-1.0.0.crate --new-work /absolute/path/to/unused-directory` to flag.py. Use the original signed Linux x86_64 rustup toolchain named ohm. [One-time upgrade](../README.md) · [Final reader experiment](../marginal/README.md)
