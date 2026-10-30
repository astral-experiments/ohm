# Native Apple CRC tracking with a fixed Cargo 293

The independent measurement used Rust #276 444c0273 and child #277 82911b51, each with exactly one source-authenticated Cargo 735e1528 and stock Xcode ld. The source-built SDKs share the same frontend and standard libraries. Their sole SDK difference is the compiler driver. The original baseline Cargo and both Rust stage1 toolchains are optimized local builds and were built on the registered native runner without distribution PGO. Linux, signed Cargo and the separate build-script Cargo experiment contribute no clocks here.

The foreground commands inherited the runner's CI environment. Cargo disabled incremental compilation in that environment. The 32 preflight and two terminal, kernel-observed `ty_vendored --test` emitters all omitted `-C incremental`. A separate local-development experiment establishes its own inputs, native products and clocks.

## Ruff test build in CI mode

Run `cargo +ohm test -p ty_vendored --lib --features deflate --no-run --locked --offline -j4 --message-format=json` across the actual Ruff #29042 edit. Each independent paired installation started empty. The output includes the exact old/new 819-member ZIP and both real tests. Independently clean images matched same-role cached images byte for byte. The source-selected changed ZIP stubs, embedded ZIP, all full images and actual linker inputs were reopened. Across roles compare only the registered Cargo work-directory components inside witnessed N_OSO operand paths and independently verified ad-hoc signature page hashes.

| Endpoint | #276 median seconds | #277 median seconds | Median paired ratio | 96.14% paired median interval | Balanced p for 2× |
| --- | ---: | ---: | ---: | ---: | ---: |
| Historical edit | 4.5033 | 2.0921 | 2.1516× | 2.1129–2.1783× | 0.00108 |
| First unchanged, primary | 4.4952 | 2.0927 | 2.1429× | 2.1188–2.1833× | 0.00108 |
| Second unchanged, settled | 4.5159 | 2.0960 | 2.1382× | 2.1163–2.1711× | 0.00108 |
| Historical edit plus first unchanged | 9.0280 | 4.1965 | 2.1530× | 2.1223–2.1788× | 0.00108 |

The 12 orders were allocated independently and balanced six each. The interval is the third to tenth paired order statistic. The one-sided randomization compares all 924 assignments at a twofold sharp null. Cold preparation and separate instrumented controls do not enter these elapsed estimates. The predeclared first-unchanged twofold gate was **met**. Both preliminary mirrored pilot ratios are retained separately, 2.1629× and 2.1067×. Each pair charges the complete ordinary foreground Cargo invocation, including the retained work below. The reported wall endpoint is independent of occasional unavailability of a Darwin retired-instruction counter.

On each historical edit and both unchanged repeat commands, two traced preflight installations per role independently gave four full rustcs for #276 (zlib_rs twice, build_script_build and ty_vendored) versus two for #277 (build_script_build and ty_vendored). Both ran two genuine Xcode links, first for the build script and then for the test executable, and zero link-only rustcs. Both roles passed a truly invalid Rust edit, recovery and an independent final empty reference. The native linker SHA-256 is 2b48a59af70235283aa94c43eb0dd2ef80182c106db43279db936cc87426b443.

## External providers

All 392 warm/independently empty Cargo commands are represented. Both default configurations preserved higher-priority archive insertion, malformed/missing negative verdicts, ordinary Rust edits, same-inode same-timestamp replacements and both direct/transitive placements. Declared inputs and real source changes matched their independently empty references. Twelve intentionally unwatched results under explicit defaults-off differed from clean and are retained as diagnostic controls. Separately the hard bundled native archive changed from 17 to 29, failed malformed/missing and recovered to its clean executable. The prior zero-clock run 41068365290 is separate. Its measured source and clean products passed, and both actual links remained where its original rule required zero final links.

## Reopening

Run `python3 -IB verify.py` in this directory for offline verification of all projected provider verdicts, complete physical work rosters, the chronology of all 84 charged clocks, both pilot pairs, all 12 independent pairs and their statistics. To independently reconstruct these projections from the complete Actions artifacts, use `python3 -IB reopen-raw.py crc-on-293-provider.zip crc-on-293-pilots.zip crc-on-293-final.zip`. This additionally checks every original archive entry, the signed toolchain source bindings, the actual process and typed Cargo streams, the held entire native test executables, full ZIPs and disk-inode censuses. The ordinary full test-plus-correctness scope is native Apple silicon on this host. The kernel observer covered separate flanking executions and was absent from the clocked commands. [GitHub Actions run 41071825672](https://github.com/astral-experiments/ohm/actions/runs/41071825672)
