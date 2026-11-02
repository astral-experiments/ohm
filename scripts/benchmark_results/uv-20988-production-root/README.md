# Production root check after uv #20988

Together, the two trait-lookup changes reduced the ordinary workspace-root check from **6.299 s to 4.020 s** after the landed workspace-glob change in uv. All twelve pairs improved. The command was `cargo check --locked --offline -j8` on a single calibrated Linux x86-64 host. Both compilers used Ohm −22 sources, the production PGO and BOLT recipe, the CTFE literal fix and the exact signed −22 Cargo binary. [uv edit](https://github.com/astral-sh/uv/pull/20988) · [#296](https://github.com/astral-experiments/ohm-rust/pull/296) · [#306](https://github.com/astral-experiments/ohm-rust/pull/306) · [CTFE fix #318](https://github.com/astral-experiments/ohm-rust/pull/318)

| First-edit measure | Corrected stock | Corrected #296 + #306 | Paired stock / stack | Median interval |
| --- | ---: | ---: | ---: | ---: |
| Ordinary wall time | 6.299 s | 4.020 s | **1.576147×** | 1.541144–1.592815× |
| Whole-command userspace instructions | 62.199B | 34.440B | **1.805992×** | 1.805338–1.806656× |

The two arm columns show marginal medians. Paired ratios imply 36.55% less elapsed time and 44.63% fewer instructions. Each compiler had twelve independently prepared pre-edit states, split into two groups of six runs with balanced compiler order. The two group medians were 1.579930× and 1.566756× for wall time and 1.805923× and 1.806071× for instructions. The order-stratum medians were 1.572846× and 1.579972× for wall time and 1.806088× and 1.805678× for instructions, with stock-first listed first. The interval uses the 2nd and 11th of twelve paired ratios, with 99.365% nominal coverage for a median under independent matched signs. Both metrics improved in 12/12 pairs. Neither reached 2× in any pair.

The wall visit used bare Cargo. A separate restored visit counted `PERF_COUNT_HW_INSTRUCTIONS` in the Cargo process and all descendants, including its 18 rustc invocations. These totals describe the whole command. This two-arm experiment measures the combined changes and leaves the marginal effect of #306 and per-crate hardware counts to separate experiments. [Protocol](https://github.com/astral-experiments/ohm/blob/a08fbd2dc6330acc9a908657671a45611ab91478/scripts/uv-20988-ctfe-hw/protocol.json)

### Recalculate the twelve original pairs

Run this in this directory with Python 3.11 or later. It takes a few seconds and needs only the standard library.

```sh
python3 -I verify.py
```

The 108 kB packet retains 289 original JSON members, including every raw wall clock and PMU reading, real compiler PIDs and full argument lists, Cargo's 641-row product summaries, four per-visit workspace manifests, the cold-build comparisons, the source fixtures and build receipts. It also contains the preregistered protocol and a receipt identifying the full original ZIP. The verifier reads these records to recalculate the ratios and both six-pair groupings, checks the SDK and PMU provenance, and checks the recorded same-seed raw product hashes and independent-cold semantic coverage for all 70 workspace products. Independent clean builds can have different metadata layout. For each difference, the full audit decoded the definition, expansion and allocation tables along with the crate roots and dependency rows.

To compare all 289 retained members byte-for-byte with the original service upload, download that ZIP and pass its path. The ZIP is 702,281,081 bytes with SHA-256 `9c00c737e0efc29923b14f03f50a7d2452e8e18b6217795f60a3538b9f231434`. Full metadata bytes, raw Cargo transcripts and kernel event streams remain in that upload. [Original artifact](https://github.com/astral-experiments/ohm/actions/runs/41379994255/artifacts/13113749723) · [Complete original auditor](https://github.com/astral-experiments/ohm/blob/a08fbd2dc6330acc9a908657671a45611ab91478/scripts/uv-20988-ctfe-hw/audit.py)

```sh
python3 -I verify.py --original /path/to/original.zip
```

### Repeat the physical experiment

The exact scenario is uv `b60da7ad468d5bb8a6b3dee7d7e54a47981f23c7` → `1979349b68dbaa936b98c0f409c1df0598fa72f1`. The control compiler is `10d56274a98801b5ef8f80aab734e835749458e1` with incremental epoch 43310. The treatment is `4cc83ad906d8cd570c15b4508bc82ec3712cfb81` with epoch 43309. The signed Cargo SHA-256 is `3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871`. To collect new measurements, use the pinned build and benchmark workflows with their SDK qualification, cross-version cache tests, on-host PMU calibration and independent histories. Each visit applies the actual edit to an unchanged checkout of its parent. [Production builds](https://github.com/astral-experiments/ohm/actions/runs/41374825846) · [Benchmark run](https://github.com/astral-experiments/ohm/actions/runs/41379994255) · [Benchmark workflow](https://github.com/astral-experiments/ohm/blob/a08fbd2dc6330acc9a908657671a45611ab91478/.github/workflows/ci.yml)
