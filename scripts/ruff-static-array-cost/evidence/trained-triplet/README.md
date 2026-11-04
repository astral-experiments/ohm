# Release-trained compilers on Ruff’s Unicode generator edit

**The edited check compiler used 47.130% fewer retired user instructions, a 1.89142× speedup. The whole ordinary Cargo check used 10.179% fewer.** Packing the additional tuple and character literals in C7 saved 17.151% in the edited compiler and 2.566% in the complete check relative to C5. The target fell below the preregistered 2× threshold on all six fresh boots. [Preregistered protocol](../../TRIPLET.md) · [Independent confirmation](https://github.com/astral-experiments/ohm/actions/runs/41854421768) · [Compiler PR](https://github.com/astral-experiments/ohm-rust/pull/355)

Ruff #29261 updated its locked random generator dependencies. The generated Rust changed for both the 13,490 `(u16,u16)` rows and 40,470 `char` rows. The measured edit changed 11 of 17 Cargo units. The genuine OLD build contained 20 units. All three compilers resolved the same 502 locked registry archives and reused each installed SDK, Cargo-home, target and shared-build path. The Linux jobs used signed Cargo and Wild, two Cargo build jobs, and independently source-built and release-trained rustc programs. [Ruff edit](https://github.com/astral-sh/ruff/pull/29261) · [Complete release factory pins](transports.json) · [Typed source/value hashes](../../rng-tables.json)

| Compiler | Rust source | Compiler factory |
|---|---|---|
| F5, released source baseline | [f5a51d8](https://github.com/astral-experiments/ohm-rust/commit/f5a51d8cc3e76236c2d0f17d495d59ebb03306e4) | [41737296261](https://github.com/astral-experiments/ohm/actions/runs/41737296261) |
| C5, bulk integer literals | [6c2874a](https://github.com/astral-experiments/ohm-rust/commit/6c2874a0b6a0bf3570f8959733b6f87907e5cce6) | [41742694783](https://github.com/astral-experiments/ohm/actions/runs/41742694783) |
| C7, additional tuple and char literals | [06fe634](https://github.com/astral-experiments/ohm-rust/commit/06fe634feaa39288210a6f17b8994346a5fae1c1) | [41756960897](https://github.com/astral-experiments/ohm/actions/runs/41756960897) |

## Hardware results

Each row gives the median paired percentage reduction followed by the six-boot minimum and maximum. For six independent pairs the extremes give the exact 96.875% distribution-free median interval. Every edited endpoint favored C7 on all six boots, giving a two-sided exact sign-test p of 0.03125 against equal probability of either direction. The 2× condition required the actual F5 count to exceed twice the C7 count on each new boot. The two earlier pilot boots were excluded from these estimates. [Six original rosters, counts and decisions](counts.json) · [Two reverse-order pilots](https://github.com/astral-experiments/ohm/actions/runs/41853276810)

| Ordinary Ruff edit | F5 to C7, cumulative | C5 to C7, incremental |
|---|---:|---:|
| Selected check rustc | 47.130% (47.110–47.146%) | 17.151% (17.134–17.229%) |
| Complete Cargo check | 10.179% (10.137–10.393%) | 2.566% (2.494–2.611%) |
| Selected build rustc | 42.355% (42.337–42.426%) | 14.490% (14.407–14.575%) |
| Complete Cargo build | 9.928% (9.873–9.963%) | 2.465% (2.448–2.473%) |

The untraced ordinary Cargo command and the observed compiler ran separately from the same restored ordinary OLD donor. The selected process had to execute the installed rustc on the Unicode library and retire a positive, unscaled exec-to-exit count. The original Cargo and selected rustc records, complete exec arguments and calibrations are retained.

| Fresh boot | Order | F5 check rustc | C5 check rustc | C7 check rustc | F5 / C7 |
|---|---|---:|---:|---:|---:|
| B1 | F5 → C5 → C7 | 4,927,908,193 | 3,146,058,565 | 2,606,376,883 | 1.89071× |
| B2 | C5 → C7 → F5 | 4,930,047,177 | 3,146,204,937 | 2,607,108,929 | 1.89100× |
| B3 | C7 → F5 → C5 | 4,930,277,850 | 3,145,528,799 | 2,606,576,328 | 1.89148× |
| B4 | C7 → C5 → F5 | 4,931,132,824 | 3,146,611,702 | 2,607,055,309 | 1.89146× |
| B5 | C5 → F5 → C7 | 4,930,406,823 | 3,148,275,322 | 2,606,765,453 | 1.89139× |
| B6 | F5 → C7 → C5 | 4,930,570,894 | 3,148,468,663 | 2,606,017,648 | 1.89199× |

Both opposite-order pilots met the material-effect, whole-command and safety criteria. Their cumulative check-compiler ratios were 1.89122× and 1.89194×. The smaller stage-1 software model gave 2.00013×. The trained hardware result is reported separately. [Original software and native controls](portable.json) · [Pilot and confirmation registrations](originals.json)

## Cold, settled and retained storage

On the six new boots, C7 cut complete cold OLD check/build work by medians of 7.441%/7.195% versus F5 and 1.845%/1.730% versus C5. The settled commands reported zero dirty units. Their six-boot paired changes against either prior arm stayed within 0.026%.

The following are medians of actual logical and physical bytes over six independent boots. Each target and shared tree was scanned together and each regular inode charged once, with all path aliases retained. Edited and settled rows had identical storage within every arm.

| History | F5 logical / allocated | C5 logical / allocated | C7 logical / allocated | Files per arm |
|---|---:|---:|---:|---:|
| check ordinary-edit | 94,377,870 / 95,993,856 | 71,803,855 / 73,424,896 | 64,672,016 / 66,289,664 | 699 |
| check empty-new | 43,537,398 / 44,390,400 | 32,247,375 / 33,107,968 | 28,686,833 / 29,542,400 | 374 |
| build ordinary-edit | 102,044,152 / 103,759,872 | 79,337,729 / 81,055,744 | 72,152,127 / 73,859,072 | 736 |
| build empty-new | 47,505,564 / 48,414,720 | 36,144,985 / 37,064,704 | 32,557,556 / 33,468,416 | 397 |

## Behavior and complete outputs

Each actual trained SDK first passed scalar, tuple, character, identity, layout-fallback and diagnostic probes. The ordinary edited and independently empty builds produced the same complete native reader within each compiler. The old reader and new reader had different ELF bytes. Both returned the same complete 6,002,772-byte expected stream covering 153,626 canonical Unicode names, 481 aliases and three negative cases. In every arm, u8 and u16 overflows and a u32 in a char array failed twice at the intended source bytes. Repair matched independently empty NEW. [Guard inputs](../../aggregate_probe.py) · [Portable ordinary diagnostic controls](portable-errors.json)

The offline reader opens every physical rmeta and rlib, all 13 native object members, both Rust metadata members, the ordered GNU symbol table, the GNU name table, padding and headers. The only normalized regions are seven rustc-generated temporary-name characters in the two typed occurrences of each object name, once in the archive name table and once in the Rust link record. The complete normalized edited, settled, repaired and independently empty NEW archives agree within each arm. The check rmeta and executable byte comparisons use their entire original bodies. [Typed archive reader](../../product.py)

## Offline reproduction

From this directory in a checkout of the QA evidence commit, run the following on Linux x86-64 with Python 3.11 or newer and the zstd executable installed.

```sh
python3 -IB verify.py --run-native --report /tmp/ruff-trained-rng-counts.json
cmp /tmp/ruff-trained-rng-counts.json counts.json
```

The 31,001,553-byte packet reconstructs all eight complete Actions ZIPs byte for byte (455,698,618 original bytes). Its SHA-256 is `4ad874e198a1924a6c8cccfcac2514ab2d8573d6bb169d33df584b99774ec842`. The verifier checks their original platform SHA-256 values, the frozen compiler/worker/registry sources, all bound PMU records, the full user-visible outputs and the six decision gates. Pass `--extracted DIRECTORY` to retain the exact reconstructed archives. The large compiler SDKs keep their original factory artifact names and verified SHA-256 digests in the registration. [Source and original artifact identities](originals.json) · [Lossless packet](originals.zip) · [Packet builder](pack.py) · [Offline verifier](verify.py)
