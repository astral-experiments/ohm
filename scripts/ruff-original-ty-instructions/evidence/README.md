# x86-64 equality-result instructions on Ruff's RUF009 change

The historical Ruff CLI used 82.703% fewer retired user instructions for its first unchanged native build after the RUF009 edit. The actual edit used 42.289% fewer instructions. All eight separately booted Linux workers met the registered 2× threshold on the first and next three unchanged builds.

| Complete command phase | Original instructions | Patched instructions | Paired reduction | Exact 99.21875% interval |
| --- | ---: | ---: | ---: | ---: |
| Edit | 91.880B | 53.026B | 42.289% | 42.268–42.298% |
| First unchanged | 90.541B | 15.661B | 82.703% | 82.697–82.707% |
| Edit plus first unchanged | 182.420B | 68.687B | 62.347% | 62.336–62.353% |
| Second unchanged | 95.579B | 16.707B | 82.520% | 82.516–82.524% |
| Third unchanged | 89.379B | 15.370B | 82.803% | 82.800–82.804% |
| Fourth unchanged | 89.821B | 15.433B | 82.818% | 82.812–82.821% |

Each instruction column is the median of eight hosts. The reduction is the median paired reduction. The interval uses the minimum and maximum paired observations. The two-sided sign test for the registered first unchanged result gives p = 0.0078125. The three later commands are repeated observations on the same hosts.

## Workload

Ruff #19021 changed commit 710c60f7135879b05f6c05a34085cd7af5c19e7f to b00f68a23cedbd3a38fc25bac63638f0f11fc3f0. Both point to the same lockfile and portable-atomic 1.11.0. Its x86-64 atomic comparison emits `sete cl`. Current Ruff at 08cab22a1599a9f16d0cb4ceaef56a138603a6da pins 1.13.1, which emits `setne cl`. The signed -23 compiler already handles that spelling. [Ruff edit](https://github.com/astral-sh/ruff/pull/19021)

Every measurement ran `cargo +ohm build -p ruff --bin ruff --locked --offline -j4` with Cargo JSON messages. Both rustc executables were native stage-1 compilers from the same SDK factory, using the signed release’s Cargo and matching standard libraries. The hardware counter covered Cargo and its descendants and required equal time enabled and running. The runner checked both the zero and nonzero exit-status calibration. Four machines used each compiler order. [SDK factory](https://github.com/astral-experiments/ohm/actions/runs/41605530113)

## What was actually skipped

The unchanged parent launched 18 typed rustc processes. The candidate launched only the Ruff CLI compiler and ty_python_semantic. Both launched Wild once. The independent reader reconstructed those rosters from stopped-kernel executable records. The recorded portable_atomic archive and metadata digests matched across arms. Both toolchains still rejected a malformed native library and an ill-typed edit to the actual changed Ruff file.

All 350 Cargo units, their features, and their warning lists agreed on every positive command. The reader ran four RUF009 cases on the preserved original and changed executables, including cases whose verdicts reversed. Within each toolchain, the real edit changed the executable and the changed, repaired and independently clean outputs matched byte for byte.

Across the two separately built compilers, every byte outside the GNU build ID and three DWARF tables agreed. Decoding preserved every DIE and macro after substituting only the verified allocator build directory. In a separate experiment, one physical compiler retained all 66 SDK file identities across the two modes. Toggling just this assembly classification then produced byte-identical whole executables, including debug information and build IDs, on both original and changed source. [Single-compiler experiment](https://github.com/astral-experiments/ohm/actions/runs/41611540937)

## Eight independent boots

| Pair | Order | Original instructions, first unchanged | Patched instructions, first unchanged | Raw GitHub artifact |
| --- | --- | ---: | ---: | --- |
| 01 | P → C | 90,541,267,562 | 15,657,296,437 | 13219741302 |
| 02 | C → P | 90,534,955,373 | 15,664,012,185 | 13219801162 |
| 03 | C → P | 90,527,372,275 | 15,663,784,243 | 13218658998 |
| 04 | P → C | 90,544,229,769 | 15,661,034,968 | 13219736373 |
| 05 | C → P | 90,543,607,353 | 15,660,993,216 | 13219876935 |
| 06 | P → C | 90,541,122,646 | 15,660,059,858 | 13219682677 |
| 07 | P → C | 90,540,957,216 | 15,661,242,936 | 13219612789 |
| 08 | C → P | 90,540,784,925 | 15,661,456,137 | 13218634840 |

The original workflow parsed the unquoted YAML worker ID 08 as the integer 8. That job stopped before either compiler ran and its 1,526-byte artifact contains only the registration. The replacement used the originally registered 08 order and identical experiment code. It was dispatched before any of the primary workers published results. The corrected workflow accepts all eight string IDs on a fresh dispatch. [First seven and rejected numeric ID](https://github.com/astral-experiments/ohm/actions/runs/41611390234) · [Registered eighth pair](https://github.com/astral-experiments/ohm/actions/runs/41611905762)

## Reproduce

The corrected registration, measurement code and SDK references are pinned at e1518fdb6d894393affeab1dd500994d35ef6eba. Run from an authenticated OSS checkout.

```sh
gh-auto workflow run ci.yml -R astral-experiments/ohm --ref charlie/qa-historical-ruff-sete-confirm-20261103 -f reviewed_head=e1518fdb6d894393affeab1dd500994d35ef6eba -f scope=all
```

The [original boot receipts and integer counts](eight-native-builds.json) and [single-driver receipt](same-driver.json) include the immutable archive digests. While GitHub retains the originals, copy fetch.py and reopen.py to an empty directory, run fetch.py there from your authenticated checkout, then run reopen.py with this checkout’s absolute path as its only argument. The reader requires zstd and llvm-dwarfdump-18.
