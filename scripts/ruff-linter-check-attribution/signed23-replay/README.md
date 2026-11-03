# Released Ohm 1.99.0-23 and the Ruff #27470 check

The published Linux SDK still compiles all 12 crates after the real two-file Ruff edit to `annotate_snippets`. The complete check used **25,262,322,389 retired user instructions**. Its nine indirect consumers accounted for **22,584,647,781 (89.40%)**. The largest was `ty_python_semantic` at **14,488,988,017 (57.35%)**. The immediate unchanged check used **410,920,079 instructions** and launched zero rustcs. This is one source- and output-checked observation. [Acquisition](https://github.com/astral-experiments/ohm/actions/runs/41571911786) · [Native ledger and counts](evidence/verified.json) · [Original registration at the executed revision](https://github.com/astral-experiments/ohm/blob/fb6ec2818714032928a7a865b2b7f6dee771ac65/scripts/ruff-linter-check-attribution/SIGNED23.md)

| Actual edited compiler | Retired user instructions | Whole check |
|---|---:|---:|
| `ty_python_semantic` | 14,488,988,017 | 57.35% |
| `ty_python_core` | 1,997,989,908 | 7.91% |
| `ty_project` | 1,790,177,116 | 7.09% |
| `ty_server` | 1,511,351,580 | 5.98% |
| `ty_ide` | 1,506,651,818 | 5.96% |
| `ruff_db` | 1,177,313,801 | 4.66% |
| `ty_module_resolver` | 972,661,402 | 3.85% |
| `annotate_snippets` | 650,769,258 | 2.58% |
| `ty_site_packages` | 328,896,895 | 1.30% |
| `ty_vendored` | 133,071,191 | 0.53% |
| `ruff_ranged_value` | 107,295,383 | 0.42% |
| `ty_combine` | 76,461,366 | 0.30% |
| Cargo and the remaining processes | 520,694,654 | 2.06% |
| **Whole check** | **25,262,322,389** | **100%** |

The producer used 650,769,258 instructions. Its two direct readers, `ruff_db` and `ty_site_packages`, used 1,506,210,696 combined (5.96%). Both kernel-observed argument vectors include `--extern annotate_snippets`. The frozen unit graph gives the other nine a longer path. The inclusive rustc counters are pairwise disjoint. The residual subtracts each once from the whole counter. If those nine cost zero and all other work stayed fixed, 2,677,674,608 instructions would remain, a 9.43× upper bound. Real improvements still need a matched candidate measurement. [Actual shortest paths and complete owner budgets](evidence/verified.json)

**Workload and native controls.** The worker checked out Ruff c6c4d38bbeeae91fe59d9c277a78169db8306561 then its direct child 97065696c0e4dbe6ff43a89c73f923bf60ee231a and checked the same `Cargo.lock`, 196 registry archives and ordinary Cargo graph. It ran `cargo +ohm check -p ty_server --lib --locked --offline --message-format=json`, with eight Cargo jobs, a separate worktree target and shared dependency output. The physical rustcs by phase were 283 old, 0 old unchanged, 12 edited, 0 new unchanged, 1 on the failing E0308 edit, 12 on repair and 283 from the independent empty new state. Cargo reported 279 typed units on every successful check. The seven full compiler/Cargo histories include the registered E0308 in the producer, complete edited/unchanged/repair hash equality across all 31 workspace metadata files, seven raw equalities with the independently empty new state, and 24 differences. All 12 scored compiler argv exactly match their separate repaired, strace-observed counterparts. [Original literal commands and 12 archived metadata bodies](evidence/release-native.zip)

The native metadata decoder reopened four crates’ actual old, warm-edited and newly empty `.rmeta` bodies. For old→warm edit it found 741 changed reachable definition hashes in `annotate_snippets`, 2,746 in `ruff_db`, 512 in `ty_site_packages`, and 2,008 in `ty_server`. All four public hashes changed. Comparing warm→empty new preserved the producer’s public hash and all its individual hashes; the other three public hashes differed. All 36 calibration controls passed. The raw reader reconstructs each PID’s ancestry, the physical executables, inherited PMU eligibility, and the successful Rustup/Cargo exits from raw ledgers. The anti-corruption probes reject six independently damaged records. [Decoded definitions](evidence/verified.json) · [Verifier negative controls](evidence/mutations.txt)

**Shipped source.** The official Linux archive was 359,921,838 bytes, SHA-256 `fc85a2ca6d47711058cd89c790c8e57f1799472e38f0ee0a08b0a51d06c1ee7b`. Both the release checksum and the platform provenance were verified. The receiver rehashed all 79 installed executable/runtime/library members and bound PIDs to actual physical executables. The measured release contains Rust d57fd1515986dccecdcece8da85e651bfb4b81f9, Cargo 7024b0d2dc5f64bba72c0d6d28f537a5cd9707ed and its bundled Wild. The Rust metadata encoder is the same Git blob 2b2f08dbca687cd0352adeeffe80d38fb1a06a50 as signed -22 and the independently built experimental parent. It still records the crate-relative visibility operand. The 12 intervening Rust commits changed no metadata-encoder source. Cargo’s 16 intervening commits contain native-link and doctest fingerprint changes. Cargo #52’s head is an ancestor of shipped Cargo. Its existing semantic-metadata mechanism still leaves all nine indirect compiles on this exact edit. [Official release](https://github.com/astral-experiments/ohm/releases/tag/ohm-1.99.0-23) · [Reviewed source and binary bindings](../signed23-source.json) · [Rust encoder at the shipped commit](https://github.com/astral-experiments/ohm-rust/blob/d57fd1515986dccecdcece8da85e651bfb4b81f9/compiler/rustc_metadata/src/rmeta/encoder.rs#L2274-L2277) · [Cargo PR ancestry](pr-ancestry.json)

**Historical comparisons.** Signed -22 archive 13197916995 (SHA-256 `69a7d5a123c01327cc87d36524a5a9c17c0e8303226d2a9afba4894503329178`) gave the same seven phase counts. It carried no hardware instruction samples. Experimental Rust 259ad7069e47eaf08cf106f187b2b6393f7fd7c2 with earlier signed Cargo gave 40,048,938,104 on the edit and 412,372,919 unchanged. Those are distinct physical toolchains and workers. No comparison of the two counts is a matched release or candidate speedup. [Experimental P evidence](https://github.com/astral-experiments/ohm/blob/15e6fa8a50a723af261c7e1c0240b946882b0938/scripts/ruff-linter-check-attribution/ownership-replay/README.md)

**Replay.** Run the following from this directory with Python 3.11+ and the system `zstd`.

```sh
python3 -IB reopen.py evidence/release-native.zip 49217287b117fab24e028fc89b0aafc60849eb25036ce91ff09c9e94b79d653f /tmp/ruff-27470-signed23.json
cmp /tmp/ruff-27470-signed23.json evidence/verified.json
python3 -IB mutations.py evidence/release-native.zip
```

The 229 portable members preserve the original bytes needed for verification, including literal NUL-separated `exec` arguments, maps of physical compiler images, complete fork/clone/exit tables, PMU attestation, typed Cargo output and actual `.rmeta` witnesses. The original successful Actions archive 13201716851 is 5,310,726 bytes, SHA-256 `7a5d6693a0ae25b132005ddf4e52f2b3b61e74f99f220f9ab62f5d43ef43b449`. An earlier receiver import mistake stopped before SDK download and before the workload. Its 479-byte original and zero native work are preserved. [Per-member manifest](evidence/packet.json) · [First refused attempt](https://github.com/astral-experiments/ohm/actions/runs/41570681032) · [Its full archive](evidence/first-refusal.zip)
