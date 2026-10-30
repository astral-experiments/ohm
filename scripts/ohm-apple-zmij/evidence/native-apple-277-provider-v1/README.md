# External native libraries with the Apple CRC compiler change

The exact parent of Ohm Rust #277 and its one-line CRC child ran 352 native Cargo commands using the signed 1.99.0-20 Cargo, stock Xcode 16 ld, and otherwise identical Rust installations. The code contained a real `crc32w` either in the executable or in a non-inlined library. The offline reader checks an actual CRC32W encoding in the text section of all 50 distinct returned Mach-Os. The C archive functions return 17 and 29, and the Rust dependency supplies a separate value for each real edit. [Rust #277](https://github.com/astral-experiments/ohm-rust/pull/277) · [Native run](https://github.com/astral-experiments/ohm/actions/runs/41065237286)

| External library with no Rust edit | Parent | CRC change | Empty build |
| --- | --- | --- | --- |
| Higher priority archive appears | 29 | 17 | 29 |
| Selected archive becomes malformed | Cargo 101 | Prior binary | Cargo 101 |
| Both archives disappear | Cargo 101 | Prior binary | Cargo 101 |

These six parent-to-child differences occurred with default Ohm settings when the build script omitted both search directories from `rerun-if-changed`, in both placements of the CRC instruction. The parent happened to recompile and relink. With Ohm defaults disabled, both versions reused the prior executable on each of these undeclared changes. All 64 warm-versus-empty comparisons with genuine Rust edits agreed, including failures. Across the 176 corresponding command pairs, all 106 pairs which returned matching successful verdicts and values also returned identical entire executables. Fifty-two pairs failed in both builds and the other eighteen account for the undeclared cases. The test ran all 236 successful products. Both declared-directory configurations agreed with the independently empty results throughout. [Declared-input release policy](https://github.com/astral-experiments/ohm-cargo/pull/294)

Run `python3 -IB verify.py` to replay the compact evidence. The 12,043,893-byte original ZIP was artifact 12982278865, SHA-256 `453b94240c7391d4fafd6d9cc4ddec6bd04facc0e89f09598c480a66444c0ff9`. With the original artifact, `python3 -IB verify.py --raw /path/to/artifact.zip` rechecks the source of each case, each complete Cargo stream, actual compiler and linker executions, full output images, native archive members and verdicts. [Exact fixture and protocol](https://github.com/astral-experiments/ohm/tree/b4749c5d33975bd7a4c7fdb5e0ce3d358787bcd7/scripts/ohm-apple-zmij)
