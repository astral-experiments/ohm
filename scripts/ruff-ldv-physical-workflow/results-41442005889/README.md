# Whole-Cargo instruction counts for variable-free LiveDebugValues

Building Ruff's workspace library after its real option edit used 4.935% fewer retired user instructions with the candidate. All six independently booted pairs favored it. The distribution-free interval for the median paired reduction was 4.915% to 4.962% (96.875% marginal coverage). The one-sided, tie-inclusive randomization test gave 1/20 over the 20 allowed allocations of three parent-first and three candidate-first boots. [Frozen assignments and decision rule](https://github.com/astral-experiments/ohm/blob/a43236131847bb5906247e46656d702e543d3c50/scripts/ruff-ldv-physical-stage/confirmation.json) · [Six worker runs and independent archive checks](https://github.com/astral-experiments/ohm/actions/runs/41442005889)

| Ordinary Cargo history | Parent median, billions of instructions | Candidate median, billions | Median paired reduction | Favorable pairs |
| --- | ---: | ---: | ---: | ---: |
| `ruff_workspace --lib`, empty | 1,850.211 | 1,803.003 | 2.549% | 6/6 |
| `ruff_workspace --lib`, option edit | 117.903 | 112.082 | 4.935% | 6/6 |
| `ruff_workspace --lib`, unchanged | 0.485438 | 0.485291 | 0.022% | 5/6 |
| Option edit plus unchanged | 118.388 | 112.567 | 4.915% | 6/6 |
| `ty_server --test e2e --no-run`, empty | 2,209.035 | 2,151.796 | 2.592% | 6/6 |
| `ty_server --test e2e --no-run`, edit | 32.006 | 31.221 | 2.455% | 6/6 |
| `ty_server --test e2e --no-run`, unchanged | 3.35639 | 3.35625 | 0.005% | 3/6 |
| E2e edit plus unchanged | 35.363 | 34.576 | 2.224% | 6/6 |

The option edit was the prespecified primary endpoint. The other rows are descriptive. Parent and candidate columns are medians of six observed counts. Each reduction uses the two counts from the same boot. The edit-plus-unchanged endpoints sum both original counts within each role before forming the ratio. Unchanged reductions ranged from −0.013% to +0.070% for the option build and −0.005% to +0.026% for the e2e build.

## Compilers and workloads

The parent is Rust `1589b5884e0a690776147e3a72223843ab83dccb`, the head of [Ohm Rust #326](https://github.com/astral-experiments/ohm-rust/pull/326). The candidate is its three-file child `531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5`, tree `e23fcbbde57dc251d92d3b052c8f7d088eac1ea9`. Both optimized stage-1 compilers contain the same register-coalescer change. Both executed with the same signed Ohm -22 Cargo, LLVM, Wild and matched standard libraries. Each kit included its own functioning source-matched rustdoc. The tested build used default Cargo entry points, optimization level 1, line-table debugging and LTO off. The counter inherited from rustup through Cargo and all children and threads. These are instruction counts on Linux x86-64. [Compiler factory and source transport](https://github.com/astral-experiments/ohm/actions/runs/41425541148) · [Source-matched documentation tools](https://github.com/astral-experiments/ohm/actions/runs/41432567050) · [Fixed-input native pass contact](https://github.com/astral-experiments/ohm/actions/runs/41428471591)

The option edit built one full `ruff_workspace` crate, and its repeat started no compiler or linker. The e2e edit built both `ty_server` and its e2e test with one real Wild link. Its repeat ran one link-only rustc and one Wild. Each role started from its own empty roots. The native checks covered 168 Cargo commands across the six boots, including 12 E0308 outcomes per workflow, repair and independently empty products. Every role/install returned the same complete option-reader and e2e executable hashes for their respective source states. The e2e roster grew from 151 to 152 tests and running the intentionally contrary expectation reported the expected diagnostic. [Ruff option edit](https://github.com/astral-sh/ruff/pull/28106) · [Ruff e2e edit](https://github.com/astral-sh/ruff/pull/27836)

The end-to-end comparison includes genuine per-installation Cargo registry directories. Five option-compiler inputs and ten e2e inputs differed in Rust metadata. The six differing archives had identical object members and symbol tables. The other nine files were completely reconstructed from typed metadata fields. Across four separate installations, every pairing changed exactly the same 607 of 1,002 `pep440_rs` definition fingerprints, including both same-compiler, different-boot comparisons. The 173 populated expansion fingerprints matched. Its upstream `serde_core` generated identical source at different physical paths. Within each installation the inputs reproduced from separate empty states and across the edit. These differences are included in the complete-toolchain result. The separate native pass experiment used fixed inputs. See the included `source-registry-metadata.tar.gz` and its original-byte verifier. [First source-native acquisition](https://github.com/astral-experiments/ohm/actions/runs/41436324816) · [Independent source-native boot](https://github.com/astral-experiments/ohm/actions/runs/41439952662)

The earlier signed diagnostic pilot reduced the two edited counts but increased instructions 1.183% on the compiler-free option repeat. Its probe wrote extra Cargo-cached diagnostics. An independent two-boot crossed test observed 5.20–5.68 million additional instructions when replaying that stream. The source-built confirmation contains no probe. All pilot observations remain excluded from its six pairs. [Signed pilot](https://github.com/astral-experiments/ohm/actions/runs/41418829562) · [Cached stderr control](https://github.com/astral-experiments/ohm/tree/c8962f0f85a2c3bd49b56f5df5200b8495bbd64c/scripts/ruff-ldv-cached-stderr/results-41426088238)

## Offline verification

The six original-result ZIPs came from separate workers that downloaded the complete original archives, checked their SHA-256 and member CRCs, and reopened the native, process and PMU records. On the coordinator, every one of the 72 original PMU members was reread from its exact archive with ETag- and length-checked HTTP ranges and matched to its native reader's digest. The underlying large binary archives are retained by GitHub Actions for 14 days. This directory retains the six independent native receipts, all 72 hardware records and the original registered analysis. The independent reader recomputes all ratios and the exact assignment test from those records.

```sh
sha256sum -c SHA256SUMS
python3 -IB verify.py --self-test
python3 -IB verify.py . > /tmp/ldv-whole-cargo-recomputed.json
cmp independent-arithmetic.json /tmp/ldv-whole-cargo-recomputed.json
```

See the source-matched workflow for a fresh native admission and six-boot dispatch. The acquisition establishes a separate working compiler and registry for each role. [Workflow and replay commands](https://github.com/astral-experiments/ohm/tree/a43236131847bb5906247e46656d702e543d3c50/scripts/ruff-ldv-physical-workflow)
